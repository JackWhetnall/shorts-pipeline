"""
Questions from elsewhere, made into bank questions (decision 061).

Two steps, so nothing is spent until it's wanted:

1. **Gather** raw questions into the `intake` table: the Open Trivia
   Database (free to download) and pub-quiz websites (reading a page's
   questions costs about half a cent). See pipeline.facts.sources.
2. **Process** them, a batch at a time, within a budget:
   - drop the ones the bank already has;
   - rewrite each as a question read aloud in a British pub quiz, in our
     own words (Haiku), dropping any that only work with options, are
     about video games, or may have changed;
   - fact-check them (Sonnet), rate how hard they are (Sonnet, the same
     rater as the bank's own), store them, and file them under every
     category they fit (pipeline.facts.scope.file_new).

About $2.50 per 1,000 raw questions, all told. Progress is kept per item,
so a stopped run carries on where it left off.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlparse

from core.logging_setup import get_logger
from pipeline.facts import bank, store

log = get_logger(__name__)

BATCH = 25
VERIFY_CHUNK = 13
VERIFY_EFFORT = "medium"       # already checked by people, and our rewrite keeps the fact
DAILY_USD = 3.00               # what the scheduler spends on it a day
# What a run's spending is counted from ("category_sort" is the filing).
OPERATIONS = ("intake_extract", "intake_rewrite", "intake_verify", "intake_rate", "category_sort",
              "category_scope")

TABLE = """
CREATE TABLE IF NOT EXISTS intake (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT '',
    raw TEXT NOT NULL,
    raw_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    note TEXT NOT NULL DEFAULT '',
    question_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (source, raw_key)
);
CREATE INDEX IF NOT EXISTS intake_status ON intake (status);
CREATE TABLE IF NOT EXISTS intake_pages (
    url TEXT PRIMARY KEY,
    read_at TEXT NOT NULL,
    found INTEGER NOT NULL DEFAULT 0
);
"""

REWRITE_SYSTEM = """
You turn quiz questions from other sources into questions for a British
pub quiz that's read aloud, written in our own words. For each numbered
question (with its answer, and the wrong options it was set with, if any):

- `keep`: false if it only works with options in front of you ("which of
  these"), is true/false, needs a picture, is about video games, anime or
  comics, is American trivia few people in Britain would meet, or has an
  answer that may have changed (current office holders, champions,
  records likely to be broken, populations, "the latest"). Otherwise
  true.
- `question`: one sentence of under 25 words, asking exactly one thing,
  British English. Write it freshly: never reuse the original's wording or
  sentence shape; ask about the same fact from your own angle.
- `answer`: as shown on the board, 1 to 4 words, the same fact as given.
- `alternatives`: other wordings that are also right, or none.
- `note`: one short line the host could add after the answer, as certain
  as the answer, or empty.
- `shape`: one or two words for its kind (superlative, only, name,
  origin, who, number, first, word...).
- `area`: two to four words for what part of its subject it's about
  ("Rivers of Europe", "The planets", "Tudor kings").
""".strip()

REWRITE_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {
    "type": "object", "properties": {
        "number": {"type": "integer"}, "keep": {"type": "boolean"}, "question": {"type": "string"},
        "answer": {"type": "string"}, "alternatives": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"}, "shape": {"type": "string"}, "area": {"type": "string"}},
    "required": ["number", "keep", "question", "answer", "alternatives", "note", "shape", "area"],
    "additionalProperties": False}}},
    "required": ["results"], "additionalProperties": False}


def _table(conn) -> None:
    conn.executescript(TABLE)


def _key(question: str) -> str:
    """The same raw question twice (from two pages of one site) is held once."""
    return " ".join(sorted(bank._keywords(question))) or question.lower()


def add_raw(conn, source: str, items: list, origin: str = "") -> int:
    """Hold raw questions for processing. Returns how many were new."""
    _table(conn)
    added = 0
    with conn:
        for item in items:
            question, answer = (item.get("question") or "").strip(), (item.get("answer") or "").strip()
            if not question or not answer:
                continue
            added += conn.execute(
                "INSERT OR IGNORE INTO intake (source, origin, raw, raw_key, created_at) VALUES (?, ?, ?, ?, ?)",
                (source, item.get("origin") or origin, json.dumps(item, ensure_ascii=False),
                 _key(question) + "|" + bank.answer_key(answer), store.now())).rowcount
    return added


# --- gathering ------------------------------------------------------------------------

def gather_opentdb(conn, say=None) -> str:
    """Download the Open Trivia Database into intake (free; ten minutes)."""
    from pipeline.facts.sources import opentdb
    items = opentdb.fetch(say)
    added = add_raw(conn, opentdb.SOURCE, items, origin="https://opentdb.com")
    return f"Open Trivia DB: {len(items)} questions read, {added} new to process."


def gather_web(conn, say=None, sleep=time.sleep) -> str:
    """Read the pub-quiz sites in config/quiz_sources.txt into intake."""
    from pipeline.facts.sources import web
    _table(conn)
    seen = {r[0] for r in conn.execute("SELECT url FROM intake_pages")}
    pages = total = 0
    for url, text in web.crawl(web.starting_pages(), seen, say, sleep):
        found = web.extract(text)
        domain = urlparse(url).netloc.removeprefix("www.")
        added = add_raw(conn, f"web:{domain}", found, origin=url)
        with conn:
            conn.execute("INSERT OR REPLACE INTO intake_pages (url, read_at, found) VALUES (?, ?, ?)",
                         (url, store.now(), len(found)))
        pages += 1
        total += added
    return f"Quiz websites: {pages} pages read, {total} new questions to process."


# --- processing ----------------------------------------------------------------------

def pending(conn) -> int:
    _table(conn)
    return conn.execute("SELECT COUNT(*) FROM intake WHERE status = 'new'").fetchone()[0]


def summary(conn) -> list:
    """[{source, new, added, rejected, skipped, duplicate}] per source."""
    _table(conn)
    rows = {}
    for source, status, n in conn.execute("SELECT source, status, COUNT(*) FROM intake GROUP BY source, status"):
        rows.setdefault(source, {"source": source})[status] = n
    return sorted(rows.values(), key=lambda r: r["source"])


def spent_since(since: float) -> float:
    from core import costs
    return sum(float(r.get("cost_usd") or 0) for r in costs.read_records()
               if float(r.get("ts") or 0) >= since and r.get("operation") in OPERATIONS)


def process(conn, categories: list, budget_usd: float, say=None) -> str:
    """Process held questions a batch at a time until none are left or
    `budget_usd` is spent. `categories`: every quiz channel's, to file
    them under."""
    _table(conn)
    started = time.time()
    done = {"added": 0, "rejected": 0, "skipped": 0, "duplicate": 0}
    while spent_since(started) < budget_usd:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, source, origin, raw FROM intake WHERE status = 'new' ORDER BY id LIMIT ?", (BATCH,))]
        if not rows:
            break
        for status, n in _batch(conn, rows, categories).items():
            done[status] = done.get(status, 0) + n
        if say:
            say(f"Processed {sum(done.values())} imported questions: {done['added']} into the bank "
                f"(${spent_since(started):.2f} so far, {pending(conn)} still to do)")
    left = pending(conn)
    if done["added"]:
        # Make rounds from them now (pipeline.facts.rounds): local, free.
        from core.channels import load_channels
        from pipeline.facts import rounds
        for channel in load_channels(validate=False).values():
            if channel.format == "quiz" and not channel.archived:
                rounds.assemble(conn, channel)
    return (f"Imported {done['added']} questions into the bank; {done['rejected']} failed the fact check, "
            f"{done['skipped']} didn't suit, {done['duplicate']} were already there. "
            + (f"{left} still to do." if left else "All done."))


def _mark(conn, item_id: int, status: str, note: str = "", question_id: int = None) -> None:
    conn.execute("UPDATE intake SET status = ?, note = ?, question_id = ? WHERE id = ?",
                 (status, note[:200], question_id, item_id))


def _batch(conn, rows: list, categories: list) -> dict:
    from pipeline import quiz
    from pipeline.facts import rate, scope
    from pipeline.llm import call_json
    counts = {"added": 0, "rejected": 0, "skipped": 0, "duplicate": 0}
    raws = [json.loads(r["raw"]) for r in rows]

    # Already in the bank as it's given?
    existing = bank._existing(conn, {bank.answer_key(x["answer"]) for x in raws})
    live = []
    with conn:
        for row, raw in zip(rows, raws):
            if bank.is_repeat(raw["question"], raw["answer"], existing):
                _mark(conn, row["id"], "duplicate", "already in the bank")
                counts["duplicate"] += 1
            else:
                live.append((row, raw))
    if not live:
        return counts

    listed = "\n".join(
        f"{i + 1}. {raw['question']} Answer: {raw['answer']}"
        + (f" (set with the wrong options: {', '.join(raw['wrong'])})" if raw.get("wrong") else "")
        for i, (_, raw) in enumerate(live))
    data = call_json(REWRITE_SYSTEM, listed, REWRITE_SCHEMA, operation="intake_rewrite",
                     model="claude-haiku-4-5", max_tokens=8000, effort=None)
    rewritten = {r.get("number"): r for r in data.get("results") or []}

    fresh, batch_seen = [], []
    existing += bank._existing(conn, {bank.answer_key(r.get("answer", "")) for r in rewritten.values()})
    with conn:
        for i, (row, raw) in enumerate(live):
            r = rewritten.get(i + 1)
            if r is None:
                continue                # no answer for it: stays new, tried again next run
            question, answer = " ".join((r.get("question") or "").split()), " ".join((r.get("answer") or "").split())
            if not r.get("keep") or not question or not answer:
                _mark(conn, row["id"], "skipped", "doesn't suit a pub quiz read aloud")
                counts["skipped"] += 1
            elif len(answer) > 60 or bank.malformed(question) or bank.gives_away(question, answer):
                _mark(conn, row["id"], "skipped", "the rewritten question didn't hold up")
                counts["skipped"] += 1
            elif bank.is_repeat(question, answer, existing + batch_seen):
                _mark(conn, row["id"], "duplicate", "already in the bank")
                counts["duplicate"] += 1
            else:
                batch_seen.append((question, answer))
                fresh.append((row, raw, {**r, "question": question, "answer": answer, "spoken_answer": answer,
                                         "origin": row["origin"]}))
    if not fresh:
        return counts

    questions = [q for _, _, q in fresh]
    verdicts = []
    for start in range(0, len(questions), VERIFY_CHUNK):
        chunk = questions[start:start + VERIFY_CHUNK]
        verdicts += quiz.verify("General Knowledge", "any", chunk, operation="intake_verify", effort=VERIFY_EFFORT)
    passed = [q for q, v in zip(questions, verdicts) if v == "ok"]
    ratings = dict(zip(map(id, passed), rate.rate(passed, operation="intake_rate"))) if passed else {}

    new_ids = []
    for (row, raw, q), verdict in zip(fresh, verdicts):
        rating = ratings.get(id(q))
        if verdict == "ok" and rating:
            percent, kid = rating
            q = {**q, "level": rate.level_for(percent, kid), "known_pct": percent, "kid_guess": int(kid)}
            status = "ok"
        else:
            status = "rejected"
        qid = bank.add(conn, q, "", (q.get("area") or raw.get("category") or "").strip()[:60], status,
                       verdict, row["source"])
        with conn:
            _mark(conn, row["id"], "added" if status == "ok" else "rejected", verdict, qid)
        counts["added" if status == "ok" else "rejected"] += 1
        if status == "ok":
            new_ids.append(qid)
    if new_ids and categories:
        try:
            scope.file_new(conn, new_ids, categories)
        except Exception as exc:  # noqa: BLE001 - in the bank unfiled; refiling a category finds them
            log.warning(f"  [intake] couldn't file the imported questions into categories ({exc})")
    return counts
