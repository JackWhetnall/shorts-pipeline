"""
The editor's pass over a documentary script (decision 086).

A script that does what its outline says can still lose viewers: long
written sentences, a striking word used nine times, a chapter that drifts
with nothing new in it, an opening that doesn't say what the title
promised. The first Lincoln film had all four. This reads the script the
way an editor would, in two parts:

- checks that need no model: average sentence length per chapter, the
  stock phrases that mark narration as AI-written, words worn out by
  repetition, the first line against the angle's hook, two cards in a
  row;
- one critic call that scores each chapter for momentum and specificity
  and says what would make the weakest better.

Then up to two chapters, the ones with the most against them, are written
again with those notes. About five cents in all. The notes are kept on
the script (`edits`) so the owner can see what was changed and why.
"""

from __future__ import annotations

import re
from collections import Counter

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import call_json

log = get_logger(__name__)

MAX_REWRITES = 2
SENTENCE_WORDS = 20             # a chapter averaging more reads like writing, not speech
CRITIC_EFFORT = "low"
CRITIC_MAX_TOKENS = 6000
GOOD_ENOUGH = 7                 # chapters the critic scores this or more are left alone

STOP = set("""
about above after again against because before being below between could doing during
every further having other their there these those through under until where which while
would should still whose everything something nothing anyone someone people little never
always really almost another without within across around""".split())


def sentences(text: str) -> list:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def overused(scenes: list, cast_words: set = frozenset()) -> list:
    """[(word, count)] for content words used far more than a narrator
    would: at least six times, and more than once per 180 words."""
    words = [w.lower().strip(".,;:!?\"'()") for s in scenes for w in s["narration"].split()]
    total = len(words)
    limit = max(6, total // 180)
    counts = Counter(w for w in words if len(w) >= 5 and w not in STOP and w not in cast_words
                     and not w.isdigit())
    return [(w, n) for w, n in counts.most_common(8) if n > limit]


def restated(scenes: list) -> list:
    """[(phrase, count)] for three-word phrases a film keeps coming back
    to, word for word. The first One Day In History film restated one idea
    (the law that kept the apprentice in London) in a dozen wordings,
    which only the critic can hear; this catches the verbatim kind."""
    import re as _re
    grams = Counter()
    for s in scenes:
        words = _re.findall(r"[a-z']+", s["narration"].lower())
        for a, b, c in zip(words, words[1:], words[2:]):
            if sum(1 for w in (a, b, c) if len(w) > 3 and w not in STOP) >= 1:
                grams[f"{a} {b} {c}"] += 1
    return [(g, n) for g, n in grams.most_common(5) if n >= 4]


def checks(script: dict, outline: dict, angle: dict = None) -> dict:
    """{chapter number: [problem]} from the checks that need no model."""
    from pipeline.script_gen import _AI_TELLS
    found: dict = {}
    scenes = script["scenes"]
    by_chapter: dict = {}
    for s in scenes:
        by_chapter.setdefault(s["chapter"], []).append(s)
    for number, rows in by_chapter.items():
        said = sentences(" ".join(r["narration"] for r in rows))
        if said:
            average = sum(len(x.split()) for x in said) / len(said)
            if average > SENTENCE_WORDS:
                found.setdefault(number, []).append(
                    f"Sentences average {average:.0f} words; for the ear, about 15, some much shorter.")
        for r in rows:
            match = _AI_TELLS.search(r["narration"])
            if match:
                found.setdefault(number, []).append(f'Stock phrase "{match.group(0)}": say it plainly.')
        for a, b in zip(rows, rows[1:]):
            if a.get("medium") == "card" and b.get("medium") == "card":
                found.setdefault(number, []).append("Two cards in a row: put a picture between them.")
    cast_words = {w.lower() for m in outline.get("cast") or [] for w in m["name"].split()}
    for word, count in overused(scenes, cast_words):
        worst = max(by_chapter, key=lambda n: sum(r["narration"].lower().count(word) for r in by_chapter[n]))
        found.setdefault(worst, []).append(f'"{word}" is used {count} times in the film: vary it or cut it.')
    for phrase, count in restated(scenes):
        worst = max(by_chapter, key=lambda n: sum(r["narration"].lower().count(phrase) for r in by_chapter[n]))
        found.setdefault(worst, []).append(f'"{phrase}" comes back {count} times: say the idea once and let '
                                           f'the story show it.')
    hook = (angle or {}).get("hook", "")
    if hook and scenes:
        want = {w.lower().strip(".,!?") for w in hook.split() if len(w) > 4}
        have = {w.lower().strip(".,!?") for w in " ".join(s["narration"] for s in scenes[:2]).split()}
        if want and len(want & have) < 0.4 * len(want):
            found.setdefault(scenes[0]["chapter"], []).append(
                f"The film must open with the chosen first line (or close to it): {hook}")
    return found


CRITIC = """
You are the story editor of a YouTube documentary channel, reading a
script before it is voiced. Viewers leave the moment a film stops giving
them something new, and a chapter that only fills time costs the whole
film. Score each chapter from 1 to 10:
{momentum}
- `specificity`: names, numbers, concrete details and vivid true moments,
  rather than lines that could be in any film?
- `voice`: does it sound like a person talking, with rhythm and dynamics
  a narrator can perform (and lines of dialogue that sound spoken), not
  like writing? Restating the theme or moralising scores low.
Then, for each chapter, `fix`: one or two sentences saying exactly what
would make it better (or "" if nothing). Be demanding: 9 and 10 are rare.
""".strip()


def critic_schema() -> dict:
    row = {"type": "object", "properties": {
        "chapter": {"type": "integer"}, "momentum": {"type": "integer"},
        "specificity": {"type": "integer"}, "voice": {"type": "integer"}, "fix": {"type": "string"}},
        "required": ["chapter", "momentum", "specificity", "voice", "fix"], "additionalProperties": False}
    return {"type": "object", "properties": {"chapters": {"type": "array", "items": row}},
            "required": ["chapters"], "additionalProperties": False}


def critic_text(kind: str = "story") -> str:
    from pipeline.documentary import kinds
    return CRITIC.replace("{momentum}", kinds.CRITIC_MOMENTUM.get(kind, kinds.CRITIC_MOMENTUM["story"]))


def critique(script: dict, outline: dict, angle: dict = None, kind: str = "story") -> dict:
    """{chapter: {"score", "fix"}} from one critic call."""
    lines = []
    for i, c in enumerate(outline["chapters"], start=1):
        lines.append(f"\nChapter {i}: {c['title']}")
        lines += [s["narration"] for s in script["scenes"] if s["chapter"] == i]
    promise = (angle or {}).get("promise") or outline.get("promise", "")
    user = (f"The film's promise: {promise}\n" if promise else "") + "The script:\n" + "\n".join(lines)
    data = call_json(critic_text(kind), user, critic_schema(), operation="documentary_critic",
                     max_tokens=CRITIC_MAX_TOKENS, effort=CRITIC_EFFORT)
    out = {}
    for row in data.get("chapters") or []:
        try:
            number = int(row["chapter"])
        except (KeyError, TypeError, ValueError):
            continue
        parts = [max(1, min(10, int(row.get(k) or 5))) for k in ("momentum", "specificity", "voice")]
        out[number] = {"score": round(sum(parts) / 3, 1), "fix": " ".join(str(row.get("fix") or "").split())}
    return out


def edit(channel, title: str, outline: dict, script: dict, angle: dict = None) -> dict:
    """The script with its weakest chapters written again, and `edits`
    saying which and why. A critic that can't be reached leaves the
    script as it is (the checks still count)."""
    from pipeline.documentary import script as scripts
    problems = checks(script, outline, angle)
    try:
        from pipeline.documentary import kinds
        reviews = critique(script, outline, angle, kinds.of(channel))
    except PipelineError as exc:
        log.warning(f"  [documentary] the editor's read failed ({exc}); checks only")
        reviews = {}
    chapters = range(1, len(outline["chapters"]) + 1)

    def badness(n: int) -> float:
        score = reviews.get(n, {}).get("score", 8)
        return len(problems.get(n, [])) * 1.5 + max(0.0, GOOD_ENOUGH - score)

    worst = [n for n in sorted(chapters, key=badness, reverse=True) if badness(n) > 0][:MAX_REWRITES]
    edits = []
    for n in sorted(worst):
        notes = problems.get(n, []) + ([reviews[n]["fix"]] if reviews.get(n, {}).get("fix") else [])
        if not notes:
            continue
        note = "An editor's notes on this chapter; fix them: " + " ".join(notes)
        try:
            script = scripts.rewrite_chapter(channel, title, outline, script, n, note, angle)
        except PipelineError as exc:
            log.warning(f"  [documentary] couldn't rewrite chapter {n} ({exc}); kept as it was")
            continue
        edits.append({"chapter": n, "why": notes, "score": reviews.get(n, {}).get("score")})
        log.info(f"  [documentary] chapter {n} rewritten: {'; '.join(notes)[:200]}")
    script = {**script, "edits": edits,
              "review": {str(n): reviews[n]["score"] for n in reviews}}
    return script
