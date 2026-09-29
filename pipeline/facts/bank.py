"""
The question bank: finished pub-quiz questions, written and checked ahead
of any round.

Stored facts (the rest of pipeline.facts) are who, where and when; a good
pub quiz is more than that: the largest, the only, the first, the
collective noun, the country a dish comes from, the thing everyone half
knows. The owner: "these are facts, not quiz questions". So the bank holds
questions proper, each:

- written in batches for one category, one area of it and one level
  (`write_batch`), in classic pub-quiz shapes, in our own words: other
  people's question banks were not copied (their terms forbid it, and it
  would be the reused content YouTube demonetises);
- fact-checked once by the independent check (pipeline.quiz.verify),
  which lists every correct answer before judging. A question that fails
  is kept, marked rejected, so it's never written again;
- de-duplicated: the same answer to the same question twice is caught by
  its answer and wording (`is_repeat`);
- levelled 1-10 on the channel's scale by its writer;
- tagged with every category it fits, and used once per channel.

A round draws from the bank first (pipeline.quiz); the writer then only
writes the hook and the patter, and the questions need no second check.
Areas keep the bank broad without showing the writer everything it has
written: "Science" is split once into areas (the human body, elements,
inventions...) and each batch goes to the area with least at that level.
(Computing superlatives from Wikidata's figures was tried and dropped: it
counted historical empires as countries and prehistoric lakes as lakes,
and filed Greenland under Europe. The writer's superlatives, checked,
are better; decision 050.)
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter

from core.logging_setup import get_logger
from pipeline.facts import store

log = get_logger(__name__)

BATCH = 25                      # questions asked for per batch
CHECK_CHUNK = 13                # questions per fact-check call
WINDOWS = (0.75, 1.25, 2.0)
ANSWERS_SHOWN = 250             # the area's existing answers shown to the writer

SYSTEM = """
You write questions for a British pub quiz's question bank: the
questions a good quizmaster asks, the kind that make a room lean in.
Each is read aloud and shown on screen; the answer comes after a short
countdown. No multiple choice. British English spelling and usage
throughout (aluminium, centre, colour, football).

Write classic pub-quiz questions, not facts turned into questions. Mix
the shapes a real quiz uses:
- superlatives and records that are settled: the largest, smallest,
  longest, highest, deepest, fastest, oldest, first;
- "which is the only..." and other one-of-a-kind facts;
- naming things: a collective noun, a word for something, a nickname, a
  capital, a currency, what something is called;
- origins and connections: which country a dish, invention or breed
  comes from; who wrote, painted, composed or discovered something
  famous;
- numbers people can actually know (how many sides, legs, players,
  strings, years);
- the surprising or satisfying: a fact that gets a laugh or an "of
  course!", something most people half know.
Avoid dry lookups nobody could reason out or enjoy (where an obscure
person was born, a company's founding year, a minor award).

Each question:
- `question`: one self-contained sentence, under 25 words, plain and
  grammatical, asking exactly one thing. No "which of these".
- `answer`: as shown on the board, 1-4 words.
- `alternatives`: other wordings that are also right ("USA" for "United
  States"), or none.
- `note`: one short line the host could add after the answer, as certain
  as the answer, or empty.
- Exactly one right answer, which you are certain of and which will not
  change: no current office holders, champions, record holders that
  change, populations, prices or "the latest" anything. A superlative or
  "only" only when there is no dispute at all (never the Nile against the
  Amazon).
- `level` on this 1-10 scale:
  - 1-2: almost every adult knows it;
  - 3-4: most adults would get it: everyday general knowledge;
  - 5-6: a regular at the pub quiz would; about a third of adults;
  - 7-8: keen quizzers and fans of the category; about one in ten;
  - 9-10: specialists, or the rare person who knows an obscure but real,
    checkable fact. Still fair: never a trick.
- `shape`: one or two words for its kind (superlative, only, name, origin,
  who, number, first, word...).
- `tags`: every category from the list given that this question also
  belongs in, besides the one it was written for (often none).

Never repeat a fact already in the bank (its answers are listed), and
never write two questions whose answers give each other away.
""".strip()

SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {
    "type": "object",
    "properties": {"question": {"type": "string"}, "answer": {"type": "string"},
                   "alternatives": {"type": "array", "items": {"type": "string"}},
                   "note": {"type": "string"}, "level": {"type": "number"},
                   "shape": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
    "required": ["question", "answer", "alternatives", "note", "level", "shape", "tags"],
    "additionalProperties": False}}},
    "required": ["questions"], "additionalProperties": False}

AREAS_SYSTEM = """
List the areas a pub quiz on this category covers: distinct, broad
enough for dozens of questions each, together covering the whole
category the way a good quiz would. 10 to 18 areas, a few words each.
""".strip()

AREAS_SCHEMA = {"type": "object", "properties": {"areas": {"type": "array", "items": {"type": "string"}}},
                "required": ["areas"], "additionalProperties": False}

GENERAL = {"general knowledge", "general", "mixed bag", "trivia", "anything goes", "potluck"}


# --- telling questions apart ----------------------------------------------------------

STOPWORDS = frozenset("""a an the of in on at to for from by with and or is was are were which what who
whom whose where when how many much does did do its it this that these those as be been name called
known""".split())


def answer_key(answer: str) -> str:
    """An answer reduced to what makes it that answer: no case, no
    punctuation, no leading "the", and no plural ("Earthquakes" is
    "Earthquake")."""
    text = re.sub(r"[^a-z0-9 ]", "", (answer or "").lower())
    words = re.sub(r"^(the|a|an) ", "", " ".join(text.split())).split()
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
                    for w in words)


def _keywords(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOPWORDS and len(w) > 2}


def malformed(question: str) -> bool:
    """A question that doesn't read as one: no question mark, or the
    "What is the name of ... called?" kind of double ask."""
    words = re.findall(r"[a-z]+", question.lower())
    return not question.rstrip().endswith("?") or words.count("called") > 1 or (
        bool(words) and words[-1] == "called" and bool({"name", "term", "word"} & set(words[:6])))


def same_answer(a: str, b: str) -> bool:
    """The same answer, however written: equal once reduced, or one the
    other with words left off ("The Pacific", "Pacific Ocean")."""
    a, b = set(answer_key(a).split()), set(answer_key(b).split())
    return bool(a and b) and (a == b or a <= b or b <= a)


def is_repeat(question: str, answer: str, existing: list) -> bool:
    """The same fact asked again: the same answer, and a question about the
    same thing (most of its key words shared). "Paris" answering the
    capital of France and the city of the Louvre are two questions."""
    words = _keywords(question)
    for other_question, other_answer in existing:
        if not same_answer(other_answer, answer):
            continue
        other = _keywords(other_question)
        if not words or not other or len(words & other) / min(len(words), len(other)) >= 0.5:
            return True
    return False


def _existing(conn, answer_keys: set) -> list:
    """Stored questions whose answers share a word with any of these."""
    rows = set()
    for key in answer_keys:
        for word in {w for w in key.split() if len(w) > 2} or {key}:
            rows |= {(r[0], r[1]) for r in conn.execute(
                "SELECT question, answer FROM questions WHERE ' ' || answer_key || ' ' LIKE ?",
                (f"% {word} %",))}
    return list(rows)


# --- writing ---------------------------------------------------------------------------

def areas(conn, category: str) -> list:
    """The category's areas, worked out once (about half a cent)."""
    row = conn.execute("SELECT areas FROM bank_areas WHERE lower(category) = lower(?)", (category,)).fetchone()
    if row:
        return json.loads(row[0])
    from pipeline.llm import call_json
    found = call_json(AREAS_SYSTEM, f"Category: {category}", AREAS_SCHEMA, operation="bank_areas",
                      max_tokens=1500, effort="low")
    names = [" ".join(a.split()) for a in found.get("areas") or [] if a.strip()][:18] or [category]
    with conn:
        conn.execute("INSERT OR REPLACE INTO bank_areas (category, areas) VALUES (?, ?)",
                     (category, json.dumps(names)))
    return names


def _least_stocked_area(conn, category: str, level: float) -> str:
    names = areas(conn, category)
    counts = Counter(r[0] for r in conn.execute(
        "SELECT q.area FROM questions q JOIN question_tags t ON t.question_id = q.id "
        "WHERE t.category = ? AND abs(q.level - ?) <= 1.5", (category, level)))
    return min(names, key=lambda a: (counts.get(a, 0), random.random()))


def write_batch(conn, category: str, level: float, categories: list, count: int = BATCH,
                area: str = None) -> dict:
    """Write, check and store a batch of questions for a category near a
    level. Returns {"written", "kept", "rejected", "repeats"}."""
    from pipeline import quiz
    from pipeline.llm import SystemBlock, call_json

    area = area or _least_stocked_area(conn, category, level)
    known = [r[0] for r in conn.execute(
        "SELECT q.answer FROM questions q JOIN question_tags t ON t.question_id = q.id "
        "WHERE t.category = ? AND q.area = ? ORDER BY q.id DESC LIMIT ?", (category, area, ANSWERS_SHOWN))]
    user = (f"Category: {category}\nArea: {area}\nLevel: {level:g} on the 1-10 scale; spread the batch "
            f"about a point either side.\nQuestions: {count}\n"
            f"Categories a question can also be tagged with: {', '.join(c for c in categories if c != category)}\n")
    if known:
        user += f"\nAlready in the bank for this area (answers; don't ask these facts again):\n{'; '.join(known)}\n"
    data = call_json([SystemBlock(SYSTEM, cacheable=True)], user, SCHEMA, operation="bank_write",
                     max_tokens=12000, effort="medium")
    fresh, repeats, batch = [], 0, []
    existing = _existing(conn, {answer_key(q.get("answer", "")) for q in data.get("questions") or []})
    for q in data.get("questions") or []:
        question, answer = " ".join((q.get("question") or "").split()), " ".join((q.get("answer") or "").split())
        if not question or not answer or len(answer) > 60 or malformed(question):
            continue
        if is_repeat(question, answer, existing + batch):
            repeats += 1
            continue
        batch.append((question, answer))
        fresh.append({**q, "question": question, "answer": answer, "spoken_answer": answer})
    verdicts = []
    for start in range(0, len(fresh), CHECK_CHUNK):
        chunk = fresh[start:start + CHECK_CHUNK]
        verdicts += quiz.verify(category, f"level {level:g}", chunk, operation="bank_verify")
    kept = rejected = 0
    for q, verdict in zip(fresh, verdicts):
        status = "ok" if verdict == "ok" else "rejected"
        kept += status == "ok"
        rejected += status != "ok"
        add(conn, q, category, area, status, verdict, "written", categories)
    log.info(f"  [bank] {category} / {area} near {level:g}: {kept} kept, {rejected} rejected, "
             f"{repeats} repeats")
    return {"written": len(data.get("questions") or []), "kept": kept, "rejected": rejected,
            "repeats": repeats}


def add(conn, q: dict, category: str, area: str, status: str, verdict: str, source: str,
        categories: list = ()) -> int:
    """Store one question, tagged with its category and any others it fits."""
    known = {c.lower(): c for c in categories}
    tags = {category} | {known[t.lower()] for t in q.get("tags") or [] if t.lower() in known}
    level = max(1.0, min(10.0, float(q.get("level") or 5)))
    with conn:
        qid = conn.execute(
            "INSERT INTO questions (question, answer, alternatives, note, level, shape, area, source, "
            "status, verdict, answer_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (q["question"], q["answer"], json.dumps(q.get("alternatives") or []), (q.get("note") or "").strip(),
             level, (q.get("shape") or "").strip().lower()[:30], area, source, status, verdict,
             answer_key(q["answer"]), store.now())).lastrowid
        conn.executemany("INSERT OR IGNORE INTO question_tags (question_id, category) VALUES (?, ?)",
                         [(qid, t) for t in tags])
    return qid


# --- asking ----------------------------------------------------------------------------

def pool(conn, channel_key: str, category: str) -> list:
    """Checked questions for a category (all of them for general
    knowledge) this channel hasn't used."""
    base = ("SELECT DISTINCT q.* FROM questions q {join} WHERE q.status = 'ok' AND q.id NOT IN "
            "(SELECT question_id FROM question_used WHERE channel = ?)")
    if category.strip().lower() in GENERAL:
        rows = conn.execute(base.format(join=""), (channel_key,))
    else:
        rows = conn.execute(base.format(join="JOIN question_tags t ON t.question_id = q.id "
                                             "AND lower(t.category) = lower(?)"), (category, channel_key))
    return [dict(r) for r in rows]


def for_round(conn, channel_key: str, category: str, level: float, count: int,
              exclude: set = frozenset(), seed=None) -> list:
    """Up to `count` unused checked questions near a level, one per
    answer, with a spread of shapes and areas. Fewer when the bank is
    short there: the caller decides."""
    rows = [r for r in pool(conn, channel_key, category) if r["id"] not in exclude]
    rng = random.Random(seed)
    for window in WINDOWS:
        chosen = _spread([r for r in rows if abs(r["level"] - level) <= window], count, rng)
        if len(chosen) >= count:
            return chosen
    return chosen


def _spread(rows: list, count: int, rng) -> list:
    rows = list(rows)
    rng.shuffle(rows)
    out, answers, shapes, places = [], set(), Counter(), Counter()
    for cap in (max(2, count // 3), count):
        for r in rows:
            if len(out) == count:
                return out
            if r in out or r["answer_key"] in answers or shapes[r["shape"]] >= cap or places[r["area"]] >= cap:
                continue
            out.append(r)
            answers.add(r["answer_key"])
            shapes[r["shape"]] += 1
            places[r["area"]] += 1
    return out


def mark_used(conn, channel_key: str, ids: list, round_name: str = "") -> None:
    with conn:
        conn.executemany("INSERT OR IGNORE INTO question_used (question_id, channel, round, used_at) "
                         "VALUES (?, ?, ?, ?)", [(i, channel_key, round_name, store.now()) for i in ids])


# --- figures ---------------------------------------------------------------------------

def counts(conn, channel_key: str, category: str, levels: list) -> dict:
    """{label: unused checked questions within a point of its level}."""
    rows = pool(conn, channel_key, category)
    return {label: sum(1 for r in rows if abs(r["level"] - level) <= 1.0) for label, level in levels}


def spent_today() -> float:
    """What writing and checking the bank has cost in the last 24 hours."""
    import time
    from core import costs
    since = time.time() - 86400
    total = 0.0
    for r in costs.read_records():
        if (r.get("operation") or "").startswith("bank_") and float(r.get("ts") or 0) >= since:
            total += float(r.get("cost_usd") or 0)
    return total
