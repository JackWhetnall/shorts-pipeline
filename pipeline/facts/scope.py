"""
What each quiz category covers, and the question bank kept to it
(decision 060).

A category was only ever a name. Its "areas" were written from the name
alone, its questions were tagged by whoever wrote them, and a renamed
category kept everything it had. Renamed from Mythology to Ancient
History, it went on asking about Bigfoot and Coyote stealing fire.

Now each category has a scope: a sentence of what it covers and one of
what it doesn't (and which of the channel's other categories that goes
to), written once from pub-quiz convention and the owner's to edit. The
scope steers the areas and every batch written for the category, and a
cheap sorting pass (`sort`) files every checked question in the bank
under the categories whose scope it actually fits. A category whose scope
is new or changed, including after a rename, is sorted again before its
next round is chosen.
"""

from __future__ import annotations

import threading

from core.logging_setup import get_logger
from pipeline.facts import store

log = get_logger(__name__)

SORT_MODEL = "claude-haiku-4-5"
# The check per category is Sonnet's: on the same questions Haiku, even
# judging twice, threw out a white dwarf and an observatory from Space.
AUDIT_MODEL = "claude-sonnet-5"
AUDIT_EFFORT = "low"
AUDIT_PASSES = 1
SORT_CHUNK = 40

TABLE = """
CREATE TABLE IF NOT EXISTS category_scope (
    category TEXT PRIMARY KEY COLLATE NOCASE,
    covers TEXT NOT NULL,
    excludes TEXT NOT NULL DEFAULT '',
    edited INTEGER NOT NULL DEFAULT 0,
    written_at TEXT NOT NULL,
    sorted_at TEXT
);
"""

SYSTEM = """
You define what one category covers in a British pub quiz, the way quiz
setters and quiz-league rounds use the name. The definition decides
which questions go in the round, so it must be strict: a question either
clearly belongs or it doesn't.

Follow the usual conventions. For example:
- Ancient History: ancient Greece, Rome and Egypt: their people, events,
  places, gods and myths. Not other cultures' myths (Mythology), not
  anything after the fall of Rome.
- Modern History: from after the fall of Rome up to about the Second
  World War, anywhere in the world. Not the ancient world; not events
  after about 1950.
- History, on its own: any period.
- Music: popular music: artists, bands, songs, albums, the charts, music
  from film and TV. Not music theory or how instruments work (Music
  Theory).
- Sport: the rules and terms of sports, famous sportspeople, teams and
  clubs, competitions, venues and records.
- Mythology: the myths, gods, heroes and legendary creatures of any
  culture. Not folklore cryptids presented as real (Bigfoot).
- Geography: countries, capitals, places, rivers, mountains, borders,
  landmarks and maps.
- General Knowledge: anything at all.

You're also given the channel's other categories. Where a kind of
question has its own category there, it belongs there and is excluded
here: say so by name. Keep to the convention even when the channel has
no category for what's excluded: such questions simply aren't asked.
Never widen a category to take them in.

- `covers`: one or two sentences, what is in.
- `excludes`: one sentence, what is out and where it goes instead.
""".strip()

SCHEMA = {"type": "object", "properties": {"covers": {"type": "string"}, "excludes": {"type": "string"}},
          "required": ["covers", "excludes"], "additionalProperties": False}

SORT_SYSTEM = """
You file pub-quiz questions into the rounds they belong in. You're given
the quiz's categories, each with what it covers and what it doesn't, then
numbered questions with their answers. For each question, list every
category a quizmaster running that round would happily ask it in, judged
strictly by the category's definition. Most questions belong in exactly
one; some in two; some in none. Use the category names exactly as given.
""".strip()

SORT_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {
    "type": "object", "properties": {"number": {"type": "integer"},
                                     "categories": {"type": "array", "items": {"type": "string"}}},
    "required": ["number", "categories"], "additionalProperties": False}}},
    "required": ["results"], "additionalProperties": False}

GENERAL = {"general knowledge", "general", "mixed bag", "trivia", "anything goes", "potluck"}

_sorting = threading.Lock()


def _table(conn) -> None:
    conn.executescript(TABLE)


def get(conn, category: str) -> dict:
    """The category's scope, or None if it hasn't been written."""
    _table(conn)
    row = conn.execute("SELECT * FROM category_scope WHERE category = ?", (category,)).fetchone()
    return dict(row) if row else None


def describe(scope: dict) -> str:
    """The scope as a line to put in a prompt."""
    if not scope:
        return ""
    text = f"Covers: {scope['covers']}"
    return f"{text} Not: {scope['excludes']}" if scope.get("excludes") else text


def write(conn, category: str, categories: list) -> dict:
    """Write a category's scope from convention (a cent) and keep it."""
    from pipeline.llm import call_json
    others = [c for c in categories if c.lower() != category.lower()]
    user = (f"Category: {category}\n"
            f"The channel's other categories: {', '.join(others) if others else '(none)'}")
    data = call_json(SYSTEM, user, SCHEMA, operation="category_scope", max_tokens=2000, effort="low")
    if not (data.get("covers") or "").strip():
        from core.errors import PipelineError
        raise PipelineError(f"empty scope for {category}", user_message=(
            f"The description of {category} came back empty. Try again."))
    return save(conn, category, data.get("covers", ""), data.get("excludes", ""), edited=False)


def save(conn, category: str, covers: str, excludes: str, edited: bool = True) -> dict:
    """Keep a scope. Its areas are worked out again from it, and the bank
    is sorted against it before its next round."""
    _table(conn)
    covers, excludes = " ".join((covers or "").split()), " ".join((excludes or "").split())
    if not covers:
        raise ValueError("a scope needs to say what the category covers")
    with conn:
        conn.execute("INSERT OR REPLACE INTO category_scope (category, covers, excludes, edited, written_at, "
                     "sorted_at) VALUES (?, ?, ?, ?, ?, NULL)", (category, covers, excludes, int(edited), store.now()))
        conn.execute("DELETE FROM bank_areas WHERE lower(category) = lower(?)", (category,))
    return get(conn, category)


def forget(conn, category: str) -> None:
    """A category renamed away: its old scope and areas go with its old
    name, so the new name gets its own."""
    _table(conn)
    with conn:
        conn.execute("DELETE FROM category_scope WHERE lower(category) = lower(?)", (category,))
        conn.execute("DELETE FROM bank_areas WHERE lower(category) = lower(?)", (category,))


def ensure(conn, category: str, categories: list) -> dict:
    return get(conn, category) or write(conn, category, categories)


# --- sorting the bank -------------------------------------------------------------

def unsorted(conn, categories: list) -> list:
    """The channel's categories whose scope is new or changed since the
    bank was last sorted against it (or that have none yet)."""
    out = []
    for name in categories:
        if name.lower() in GENERAL:
            continue
        scope = get(conn, name)
        if scope is None or not scope.get("sorted_at"):
            out.append(name)
    return out


def sort(conn, categories: list, say=None) -> dict:
    """File every checked question in the bank that's tagged with any of
    the channel's categories under the categories it fits, by their
    scopes, then checks each category's questions against its own
    definition (`audit`). About a cent per 40 questions for the sort
    (Haiku) and two for the check (Sonnet). Tags for categories
    outside this channel's are left alone. Returns {"checked", "removed",
    "added"}."""
    named = [c for c in categories if c.lower() not in GENERAL]
    if not named:
        return {"checked": 0, "removed": 0, "added": 0}
    with _sorting:
        scopes = {name: ensure(conn, name, categories) for name in named}
        listed = "\n".join(f"- {name}: {describe(scopes[name])}" for name in named)
        by_lower = {name.lower(): name for name in named}
        marks = ",".join("?" * len(named))
        rows = [dict(r) for r in conn.execute(
            f"SELECT DISTINCT q.id, q.question, q.answer FROM questions q JOIN question_tags t "
            f"ON t.question_id = q.id WHERE q.status = 'ok' AND t.category COLLATE NOCASE IN ({marks})",
            named)]
        removed = added = 0
        verdicts = _verdicts(rows, listed, say)
        with conn:
            for q in rows:
                if q["id"] not in verdicts:
                    continue            # no answer for it, even asked again: left as it was
                fits = {by_lower[c.lower()] for c in verdicts[q["id"]] if c.lower() in by_lower}
                have = {r[0] for r in conn.execute(
                    f"SELECT category FROM question_tags WHERE question_id = ? AND category COLLATE NOCASE "
                    f"IN ({marks})", (q["id"], *named))}
                fit_lower, have_lower = {f.lower() for f in fits}, {h.lower() for h in have}
                for tag in have:
                    if tag.lower() not in fit_lower:
                        conn.execute("DELETE FROM question_tags WHERE question_id = ? AND category = ?",
                                     (q["id"], tag))
                        removed += 1
                for name in fits:
                    if name.lower() not in have_lower:
                        conn.execute("INSERT OR IGNORE INTO question_tags (question_id, category) VALUES (?, ?)",
                                     (q["id"], name))
                        added += 1
        skipped = len(rows) - len(verdicts)
        if skipped:
            log.warning(f"  [scope] {skipped} question(s) got no answer and were left as they were")
        # Then each category on its own, against its definition alone: the
        # sort above keeps too much (decision 060).
        for name in named:
            removed += audit(conn, name, say)
        with conn:
            conn.executemany("UPDATE category_scope SET sorted_at = ? WHERE category = ?",
                             [(store.now(), name) for name in named])
        log.info(f"  [scope] sorted {len(rows)} questions: {removed} taken out of a category, {added} added to one")
        return {"checked": len(rows), "removed": removed, "added": added}


AUDIT_SYSTEM = """
You check the questions filed under one pub-quiz round against that
round's definition. For each, say whether a quizmaster running this round
would happily ask it here.

It belongs if it's about the round's subject, including the people,
discoveries, events, places and records that go with it: an astronomer
in Space, a singer's birth name in Music, a famous driver in Sport, an
ancient Alexandrian scholar in Ancient History.

It doesn't belong if it's about something the definition leaves out (say
so even if it's a good question): another culture, period or field than
the round covers, or a subject that only shares a word with it (a
pop song naming a biblical king isn't Ancient History).
""".strip()

AUDIT_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {
    "type": "object", "properties": {"number": {"type": "integer"}, "belongs": {"type": "boolean"}},
    "required": ["number", "belongs"], "additionalProperties": False}}},
    "required": ["results"], "additionalProperties": False}


def audit(conn, category: str, say=None) -> int:
    """Take out of `category` the questions its definition doesn't cover,
    judged against that one definition alone (sorting into a dozen
    categories at once left the Bible and Chinese legends in Ancient
    History). With AUDIT_PASSES above one, each question is judged that many
    times, in a different order and company, and goes only if every one
    says it doesn't belong. (Taking it out on any "no", under a "when in
    doubt, it goes" instruction, threw out Edwin Hubble from Space and
    Kylie Minogue from Music.) About two cents per 40 questions. Returns
    how many were taken out."""
    import random
    from pipeline.llm import call_json
    defined = describe(get(conn, category))
    if not defined:
        return 0
    rows = [dict(r) for r in conn.execute(
        "SELECT q.id, q.question, q.answer FROM questions q JOIN question_tags t ON t.question_id = q.id "
        "WHERE q.status = 'ok' AND t.category = ? COLLATE NOCASE ORDER BY q.id", (category,))]
    votes: dict = {}
    for n in range(AUDIT_PASSES):
        order = list(rows)
        random.Random(n).shuffle(order)
        for start in range(0, len(order), SORT_CHUNK):
            chunk = order[start:start + SORT_CHUNK]
            if say:
                say(f"checking {category} ({n + 1} of {AUDIT_PASSES}): {start + 1}-{start + len(chunk)} "
                    f"of {len(rows)}")
            text = "\n".join(f"{i + 1}. {q['question']} Answer: {q['answer']}" for i, q in enumerate(chunk))
            data = call_json(AUDIT_SYSTEM, f"The round: {category}\n{defined}\n\nThe questions:\n{text}",
                             AUDIT_SCHEMA, operation="category_audit", model=AUDIT_MODEL, max_tokens=4000,
                             effort=AUDIT_EFFORT)
            verdicts = {r.get("number"): r.get("belongs") for r in data.get("results") or []}
            for i, q in enumerate(chunk):
                if verdicts.get(i + 1) is False:
                    votes[q["id"]] = votes.get(q["id"], 0) + 1
    out_of_scope = {qid for qid, n in votes.items() if n >= AUDIT_PASSES}
    with conn:
        conn.executemany("DELETE FROM question_tags WHERE question_id = ? AND category = ? COLLATE NOCASE",
                         [(qid, category) for qid in out_of_scope])
    log.info(f"  [scope] {category}: {len(out_of_scope)} of {len(rows)} questions didn't belong and were taken out")
    return len(out_of_scope)


def _verdicts(rows: list, listed: str, say=None) -> dict:
    """{question id: [category names]} for the questions answered for.
    A long batch's answer sometimes stops short of its last questions
    (seven in a row were once left filed under the wrong category): those
    are asked again in smaller batches, twice."""
    from pipeline.llm import call_json
    out, todo, size = {}, list(rows), SORT_CHUNK
    for attempt in range(3):
        if not todo:
            break
        missed = []
        for start in range(0, len(todo), size):
            chunk = todo[start:start + size]
            if say:
                say(f"sorting questions into categories ({len(out) + start + 1}-{len(out) + start + len(chunk)}"
                    f" of {len(rows)})" if attempt == 0 else f"asking again about {len(chunk)} skipped questions")
            text = "\n".join(f"{i + 1}. {q['question']} Answer: {q['answer']}" for i, q in enumerate(chunk))
            data = call_json(SORT_SYSTEM, f"The categories:\n{listed}\n\nThe questions:\n{text}", SORT_SCHEMA,
                             operation="category_sort", model=SORT_MODEL, max_tokens=6000, effort=None)
            answered = {r.get("number"): r.get("categories") or [] for r in data.get("results") or []}
            for i, q in enumerate(chunk):
                if i + 1 in answered:
                    out[q["id"]] = answered[i + 1]
                else:
                    missed.append(q)
        todo, size = missed, max(5, size // 3)
    return out


def outside(conn, quiz: dict) -> list:
    """The questions of a written round that its category's scope no
    longer covers (written before it was sorted), as their wording."""
    from pipeline import quiz as quiz_mod
    category = quiz_mod.base_category((quiz or {}).get("category", ""))
    if not category or category.lower() in GENERAL:
        return []
    return [q["question"] for q in (quiz or {}).get("questions") or []
            if q.get("bank_id") and not conn.execute(
                "SELECT 1 FROM question_tags WHERE question_id = ? AND category = ? COLLATE NOCASE",
                (q["bank_id"], category)).fetchone()]


def sort_if_needed(conn, categories: list, say=None) -> bool:
    """Sort the bank if any of the channel's categories needs it. True if
    it did."""
    if not unsorted(conn, categories):
        return False
    sort(conn, categories, say)
    return True


def sort_in_background(categories: list) -> None:
    """Sort soon, without holding up the page that changed a scope. The
    next round's choosing sorts first anyway if this hasn't finished."""
    def body():
        try:
            sort_if_needed(store.connect(), categories)
        except Exception:  # noqa: BLE001 - a round sorts again before it's chosen
            log.exception("  [scope] sorting the question bank failed")
    threading.Thread(target=body, name="scope-sort", daemon=True).start()
