"""
How hard a question really is, judged apart from whoever wrote it.

A batch writer asked for "questions near level 2" labels what it writes
level 2: "Which company issued the first credit card?" (Diners Club) and
"What word describes a barrel used to store beer?" (cask) went into an
Easy round that way. So every question is rated by a separate call that
isn't told what was asked for, on something concrete: the share of UK
adults who would get it right, and whether a typical ten-year-old could
at least make a good guess. Well-known questions of known difficulty
anchor the scale. The level follows from the share (`level_for`), and
the easy levels also need the ten-year-old: the owner's test for Easy is
"the sorts of things a ten-year-old can have at least a good guess at".
"""

from __future__ import annotations

from core.logging_setup import get_logger

log = get_logger(__name__)

CHUNK = 40

SYSTEM = """
You judge how hard pub-quiz questions are for a general British audience
watching a quiz video: ordinary adults, not quiz regulars. For each
question estimate:

- `percent`: the share of UK adults who would give the right answer,
  from 0 to 100, with no options to choose from and a few seconds to
  think. Be realistic: most people know far less than quiz writers
  assume. Something you learn at primary school or meet every day is
  90 or more; something a keen reader or a pub-quiz regular knows is
  30 or less.
- `kid`: whether a typical ten-year-old could answer it or at least make
  a good guess.


Reference points (share of UK adults who get it right):
- How many legs does a spider have? 97
- What is the capital of France? 95
- Which planet is known as the Red Planet? 85
- Who painted the Mona Lisa? 80
- What is the largest planet in the Solar System? 72
- What is the currency of Japan? 70
- Who wrote Pride and Prejudice? 60
- What is the capital of Australia? 50
- What is the chemical symbol for gold? 45
- What is the capital of Canada? 40
- In which year did the Titanic sink? 35
- What is a group of crows called? 30
- Who composed The Four Seasons? 25
- Which gas makes up most of Earth's atmosphere? 25
- Who was the first woman to win a Nobel Prize? 20
- Which country has the most time zones? 8
- What is the capital of Kazakhstan? 5

Judge each question on its own merits; the category and the level it was
written for are not given, on purpose.
""".strip()

SCHEMA = {"type": "object", "properties": {"ratings": {"type": "array", "items": {
    "type": "object",
    "properties": {"number": {"type": "integer"}, "percent": {"type": "number"}, "kid": {"type": "boolean"}},
    "required": ["number", "percent", "kid"], "additionalProperties": False}}},
    "required": ["ratings"], "additionalProperties": False}

# (lowest share, level): the level is the first band the share reaches.
BANDS = ((90, 1), (80, 2), (68, 3), (55, 4), (42, 5), (30, 6), (20, 7), (12, 8), (6, 9), (0, 10))
KID_LEVEL = 2.5          # the easiest levels need the ten-year-old too


def level_for(percent: float, kid: bool) -> float:
    level = next(level for floor, level in BANDS if percent >= floor)
    return max(level, KID_LEVEL + 0.5) if level <= KID_LEVEL and not kid else float(level)


def rate(questions: list) -> list:
    """[(percent, kid)] for [{question, answer}], None where a rating
    didn't come back. (Asked to flag giveaways too, it flagged easy
    questions: "Which country colonised Hong Kong?" A giveaway is caught
    by its wording instead, bank.gives_away.)"""
    from pipeline.llm import call_json
    out = []
    for start in range(0, len(questions), CHUNK):
        chunk = questions[start:start + CHUNK]
        listed = "\n".join(f"{i + 1}. {q['question']} Answer: {q['answer']}" for i, q in enumerate(chunk))
        data = call_json(SYSTEM, listed, SCHEMA, operation="bank_rate", max_tokens=6000, effort="low")
        got = {r.get("number"): r for r in data.get("ratings") or []}
        for i in range(len(chunk)):
            r = got.get(i + 1)
            out.append((max(0.0, min(100.0, float(r["percent"]))), bool(r["kid"])) if r else None)
    return out


def rate_bank(conn, only_unrated: bool = True, say=None) -> int:
    """Rate the bank's checked questions (the unrated ones, or all) and set
    their levels from the ratings. Returns how many were rated."""
    rows = conn.execute("SELECT id, question, answer FROM questions WHERE status = 'ok'"
                        + (" AND known_pct IS NULL" if only_unrated else "")).fetchall()
    done = 0
    for start in range(0, len(rows), CHUNK * 5):
        part = [dict(r) for r in rows[start:start + CHUNK * 5]]
        if say:
            say(f"rating how hard {start + 1}-{start + len(part)} of {len(rows)} questions are")
        ratings = rate(part)
        with conn:
            for q, rating in zip(part, ratings):
                if rating is None:
                    continue
                percent, kid = rating
                conn.execute("UPDATE questions SET known_pct = ?, kid_guess = ?, level = ? WHERE id = ?",
                             (percent, int(kid), level_for(percent, kid), q["id"]))
                done += 1
    return done
