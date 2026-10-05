"""
Questions from elsewhere, made into bank questions (decision 061).

Two steps, so nothing is spent until it's wanted:

1. **Gather** raw questions into the `intake` table: the Open Trivia
   Database (free to download) and pub-quiz websites (reading a page's
   questions costs about 3 cents, long pages being read in parts). See pipeline.facts.sources.
2. **Process** them, a batch at a time, within a budget:
   - drop the ones the bank already has;
   - rewrite each as a question read aloud in a British pub quiz, in our
     own words (Haiku), dropping any that only work with options, are
     about video games, or may have changed;
   - fact-check them (Sonnet), rate how hard they are (Sonnet, the same
     rater as the bank's own), store them, and file them under every
     category they fit (pipeline.facts.scope.file_new).

About $2.50 per 1,000 raw questions at full price, all told, and half
that in the hourly run, which uses batch prices (pipeline.llm.batched). Progress is kept per item,
so a stopped run carries on where it left off.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from urllib.parse import urlparse

from core.logging_setup import get_logger
from pipeline.facts import bank, store

log = get_logger(__name__)

BATCH = 25
PROCESS_MODEL = "claude-sonnet-5"
PROCESS_EFFORT = "low"
# What the scheduler spends on it a day. Was $3 at full price; the hourly
# run pays batch prices (half), so this processes as many as before.
DAILY_USD = 1.50
# What a run's spending is counted from ("category_sort" is the filing).
OPERATIONS = ("intake_extract", "intake_process", "category_scope")

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

PROCESS_SYSTEM = """
You turn quiz questions from other sources into questions for a British
pub quiz that's read aloud, check them, judge how hard they are, and file
them into the quiz's rounds. For each numbered question (with its answer,
and the wrong options it was set with, if any):

- `keep`: false if it only works with options in front of you ("which of
  these", "which came first"), is true/false, needs a picture, is about
  video games, anime or comics, is American trivia few people in Britain
  would meet, or has an answer that may have changed (current office
  holders, champions, records likely to be broken, populations, "the
  latest"). A question set with options may be kept only if the same
  fact can be asked with one clear right answer and no options.
- `question`: one sentence of under 25 words, asking exactly one thing,
  British English, never mentioning "these", "the following" or "the
  others". Write it freshly: don't reuse the original's wording or
  sentence shape; ask about the same fact from your own angle.
- `answer`: as shown on the board, 1 to 4 words, the same fact as given.
- `alternatives`: other wordings that are also right, or none.
- `note`: one short line the host could add after the answer, as certain
  as the answer, or empty.
- `shape`: one or two words for its kind (superlative, only, name,
  origin, who, number, first, word...).
- `area`: two to four words for what part of its subject it's about
  ("Rivers of Europe", "The planets", "Tudor kings").
- `correct`: true only if you are certain the answer is right, it is the
  only right answer to your question as worded, and it won't change.
- `percent` and `kid`: how hard it is, judged as below.
- `categories`: every one of the rounds listed whose definition it fits
  (several, one, or none).

How hard: `percent` is the share of UK adults who would give the right
answer with no options and a few seconds to think, 0 to 100. Be
realistic: most people know far less than quiz writers assume. `kid` is
whether a typical ten-year-old could answer it or make a good guess.
{references}
""".strip()

PROCESS_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {
    "type": "object", "properties": {
        "number": {"type": "integer"}, "keep": {"type": "boolean"}, "question": {"type": "string"},
        "answer": {"type": "string"}, "alternatives": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"}, "shape": {"type": "string"}, "area": {"type": "string"},
        "correct": {"type": "boolean"}, "percent": {"type": "number"}, "kid": {"type": "boolean"},
        "categories": {"type": "array", "items": {"type": "string"}}},
    "required": ["number", "keep", "question", "answer", "alternatives", "note", "shape", "area", "correct",
                 "percent", "kid", "categories"],
    "additionalProperties": False}}},
    "required": ["results"], "additionalProperties": False}

LEANS_ON_OPTIONS = re.compile(r"\b(these|the following|the others|of the following|which one of)\b", re.I)
TOO_CLOSE = 0.8                # a website's question reworded less than this is too close to it


def _system() -> str:
    """The prompt, with the rater's own reference points (pipeline.facts.
    rate), so imported questions are levelled on the same scale."""
    from pipeline.facts import rate
    references = rate.SYSTEM[rate.SYSTEM.index("Reference points"):rate.SYSTEM.index("Judge each")].strip()
    return PROCESS_SYSTEM.replace("{references}", references)


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
    return conn.execute("SELECT COUNT(*) FROM intake WHERE status IN ('new', 'working')").fetchone()[0]


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
        rows = _claim(conn)
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


CLAIM_STALE = 3600            # seconds before a claimed batch nobody finished is free again


def _claim(conn) -> list:
    """The next batch, claimed so another process (the app's hourly run,
    a run by hand) doesn't work on the same questions: two once did, and
    paid twice for the same rows."""
    import time as clock
    stale = clock.time() - CLAIM_STALE
    with conn:
        conn.execute("UPDATE intake SET status = 'new' WHERE status = 'working' AND CAST(note AS REAL) < ?", (stale,))
        rows = [dict(r) for r in conn.execute(
            "SELECT id, source, origin, raw FROM intake WHERE status = 'new' ORDER BY id LIMIT ?", (BATCH,))]
        conn.executemany("UPDATE intake SET status = 'working', note = ? WHERE id = ? AND status = 'new'",
                         [(str(clock.time()), r["id"]) for r in rows])
    return rows


def _mark(conn, item_id: int, status: str, note: str = "", question_id: int = None) -> None:
    conn.execute("UPDATE intake SET status = ?, note = ?, question_id = ? WHERE id = ?",
                 (status, note[:200], question_id, item_id))


def _batch(conn, rows: list, categories: list) -> dict:
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

    named = [c for c in categories if c.lower() not in scope.GENERAL]
    rounds_listed = "\n".join(f"- {name}: {scope.describe(scope.ensure(conn, name, categories))}" for name in named)
    listed = "\n".join(
        f"{i + 1}. {raw['question']} Answer: {raw['answer']}"
        + (f" (set with the wrong options: {', '.join(raw['wrong'])})" if raw.get("wrong") else "")
        for i, (_, raw) in enumerate(live))
    data = call_json(_system(), f"The rounds:\n{rounds_listed or '(none)'}\n\nThe questions:\n{listed}",
                     PROCESS_SCHEMA, operation="intake_process", model=PROCESS_MODEL, max_tokens=12000,
                     effort=PROCESS_EFFORT)
    done = {r.get("number"): r for r in data.get("results") or []}
    by_lower = {name.lower(): name for name in named}

    existing += bank._existing(conn, {bank.answer_key(r.get("answer", "")) for r in done.values()})
    batch_seen = []
    with conn:
        for i, (row, raw) in enumerate(live):
            r = done.get(i + 1)
            if r is None:
                _mark(conn, row["id"], "new")         # no answer for it: tried again next run
                continue
            question = " ".join((r.get("question") or "").split())
            answer = " ".join((r.get("answer") or "").split())
            close = difflib.SequenceMatcher(None, question.lower(), raw["question"].lower()).ratio()
            if not r.get("keep") or not question or not answer:
                _mark(conn, row["id"], "skipped", "doesn't suit a pub quiz read aloud")
                counts["skipped"] += 1
            elif len(answer) > 60 or bank.malformed(question) or bank.gives_away(question, answer) \
                    or LEANS_ON_OPTIONS.search(question):
                _mark(conn, row["id"], "skipped", "the rewritten question didn't hold up")
                counts["skipped"] += 1
            elif row["source"].startswith("web:") and close >= TOO_CLOSE:
                # A website's wording is never kept (decision 061).
                _mark(conn, row["id"], "skipped", "too close to the site's own wording")
                counts["skipped"] += 1
            elif bank.is_repeat(question, answer, existing + batch_seen):
                _mark(conn, row["id"], "duplicate", "already in the bank")
                counts["duplicate"] += 1
            else:
                batch_seen.append((question, answer))
                percent = max(0.0, min(100.0, float(r.get("percent") or 0)))
                ok = bool(r.get("correct"))
                q = {**r, "question": question, "answer": answer, "origin": row["origin"],
                     "level": rate.level_for(percent, bool(r.get("kid"))), "known_pct": percent,
                     "kid_guess": int(bool(r.get("kid")))}
                qid = bank.add(conn, q, "", (r.get("area") or raw.get("category") or "").strip()[:60],
                               "ok" if ok else "rejected", "ok" if ok else "not certain", row["source"])
                if ok:
                    fits = {by_lower[c.lower()] for c in r.get("categories") or [] if c.lower() in by_lower}
                    conn.executemany("INSERT OR IGNORE INTO question_tags (question_id, category) VALUES (?, ?)",
                                     [(qid, name) for name in fits])
                _mark(conn, row["id"], "added" if ok else "rejected", "" if ok else "not certain", qid)
                counts["added" if ok else "rejected"] += 1
    return counts
