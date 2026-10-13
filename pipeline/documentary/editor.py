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


WEAK_OPENING = re.compile(r"^\W*(?:\[[^\]]*\]\s*)?(you'?d think|imagine|have you ever|ever wondered|this is the "
                          r"story|what if|picture this|so,? )", re.IGNORECASE)


def explainer_checks(scenes: list) -> dict:
    """{chapter: [problem]} for an explainer's shape (decision 091): it opens
    on proof, not on a question or a wind-up, and no two chapters end on
    the same question shape (the drill film ended three on "So what...?")."""
    found: dict = {}
    if scenes:
        first = scenes[0]["narration"].strip()
        if WEAK_OPENING.match(first) or first.rstrip().endswith("?"):
            found.setdefault(scenes[0]["chapter"], []).append(
                "Open on proof, not a question or a wind-up: the strangest concrete fact or sight in the "
                "film, said plainly, in the first sentence.")
    ends, last = {}, {}
    for s in scenes:
        last[s["chapter"]] = s["narration"].strip()
    for chapter, line in sorted(last.items()):
        if line.endswith("?"):
            shape = " ".join(re.findall(r"[a-z']+", line.lower())[:2])
            if shape in ends:
                found.setdefault(chapter, []).append(
                    f'Chapter {ends[shape]} already ended on a "{shape}..." question: end this one on a '
                    f"reveal, a sharper problem or a cliffhanger instead.")
            else:
                ends[shape] = chapter
    return found


def checks(script: dict, outline: dict, angle: dict = None, kind: str = "story") -> dict:
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
    if kind == "explainer":
        for chapter, problems in explainer_checks(scenes).items():
            found.setdefault(chapter, []).extend(problems)
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


FACTS = """
You are the science editor of a YouTube explainer channel, reading a finished script before it is
voiced. Viewers of science channels check numbers and say so in the comments; one wrong figure
costs the film its credibility. Find only real problems, line by line:
- a number, ratio, date, duration or scale comparison that is wrong (work ratios out yourself:
  384,000 / 6,371 is about 60, not 6), or that contradicts another line of the script;
- a physical claim that is false or badly overstated (rock at 180 degrees Celsius does not glow);
  check the film's central claims too, not only its details: the idea the whole film argues can be
  the thing that's wrong. An absolute ("never", "always", "every", "no way out") that is only mostly
  true is a fault: say what really happens, keeping the line's punch;
- a line that doesn't make sense when read literally, or a comparison that means nothing;
- an invented character's action presented as a real present-day fact;
- a stray production word that isn't narration (reframe, payoff, cold open, chapter, beat).
Most lines are fine; leave them out. For each problem give the scene's number, the problem in a
short sentence, and `narration`: the line rewritten to fix it, the same length and voice, keeping
any [cue] at its start. Where the scene shows a card, `card` is its corrected words in the card's own
shape (its items joined with " ; ", each "label|value" if the card's are, or the value), or ""
if the card is fine. A card that says what the corrected line no longer says is a fault too.

Then read the YouTube description the same way, against the script as you've corrected it: a
number or claim the script no longer makes, or a stock phrase ("journey", "it turns out",
"delve"), is a fault. Give it rewritten in `description`, or "" if it's fine.
""".strip()


def _facts_schema() -> dict:
    row = {"type": "object", "properties": {
        "scene": {"type": "integer"}, "problem": {"type": "string"}, "narration": {"type": "string"},
        "card": {"type": "string"}},
        "required": ["scene", "problem", "narration", "card"], "additionalProperties": False}
    return {"type": "object", "properties": {"fixes": {"type": "array", "items": row},
                                             "description": {"type": "string"}},
            "required": ["fixes", "description"], "additionalProperties": False}


def _card_text(card: dict) -> str:
    if not card:
        return ""
    bits = [card.get("heading", ""), card.get("value", ""), card.get("caption", "")] + list(card.get("items") or [])
    return " / ".join(b for b in bits if b)


def fact_check(script: dict) -> tuple:
    """(the script with wrong lines rewritten, [{scene, problem}]): one
    call over the whole narration, for explainers (decision 091). The first
    explainer needed nine lines fixed by hand: sixty times closer said as
    "six and a half", a 180-degree bit "glowing red", a prompt word left in."""
    scenes = script["scenes"]
    lines = [f"{i}. {s['narration']}" + (f"  [card: {_card_text(s.get('card'))}]" if s.get("card") else "")
             for i, s in enumerate(scenes)]
    described = f"\n\nThe YouTube description:\n{script['description']}" if script.get("description") else ""
    data = call_json(FACTS, "The script:\n" + "\n".join(lines) + described, _facts_schema(),
                     operation="documentary_fact_check", max_tokens=8000, effort="medium")
    fixed, notes = [dict(s) for s in scenes], []
    for row in data.get("fixes") or []:
        i, text = row.get("scene"), " ".join(str(row.get("narration") or "").split())
        if not isinstance(i, int) or not 0 <= i < len(fixed) or not text:
            continue
        fixed[i]["narration"] = text
        card = fixed[i].get("card")
        new = str(row.get("card") or "").strip()
        if card and new:
            if card.get("items"):
                # "label|value" items keep their shape; a list's items are plain lines.
                paired = all("|" in x for x in card["items"])
                items = [x.strip() for x in new.split(";") if x.strip() and ("|" in x or not paired)][:5]
                card = {**card, "items": items if len(items) >= 2 else card["items"]}
            elif card.get("kind") == "number" and len(new) <= 16 and re.search(r"\d", new):
                # Only a number: one correction put "Rock turns ductile near|" on a card.
                card = {**card, "value": new}
            fixed[i]["card"] = card
        notes.append({"scene": i, "problem": " ".join(str(row.get("problem") or "").split())})
    out = {**script, "scenes": fixed}
    better = " ".join(str(data.get("description") or "").split())
    if better and script.get("description"):
        out["description"] = better
        notes.append({"scene": -1, "problem": "the description"})
    return out, notes


FINAL = """
You decide a documentary's last line, the one the viewer leaves with. After it, the last picture
is held in silence and the film fades out. A strong last line is short (under fifteen words),
sounds final when spoken aloud, and lands the film's idea in a concrete image, often a callback to
the opening or the title. It is never a question, a summary, a moral, a call to action ("so next
time...", "subscribe") or "and that's why". Judge the current last line honestly: if it's strong,
keep it. If not, write the line that should end this film, following straight on from the line
before it, in the channel's voice, adding no new fact.
""".strip()


def final_line(channel, title: str, script: dict) -> tuple:
    """(the script with its last line made an ending, the note or ""): one
    small call (decision 092). The first explainer ended on a line that
    restated the twist and stopped, with nothing after it."""
    scenes = script["scenes"]
    if not scenes:
        return script, ""
    opening = " ".join(s["narration"] for s in scenes[:3])
    closing = "\n".join(f"{'LAST LINE: ' if k == len(scenes) - 1 else ''}{s['narration']}"
                         for k, s in list(enumerate(scenes))[-6:])
    user = (f"The channel's brief: {channel.style_prompt}\n\nThe film: {title}\n\nHow it opens: {opening}"
            f"\n\nHow it ends:\n{closing}")
    schema = {"type": "object", "properties": {"keep": {"type": "boolean"}, "line": {"type": "string"},
                                               "why": {"type": "string"}},
              "required": ["keep", "line", "why"], "additionalProperties": False}
    data = call_json(FINAL, user, schema, operation="documentary_last_line", max_tokens=3000, effort="low")
    line = " ".join(str(data.get("line") or "").split())
    if data.get("keep") or not line or line.endswith("?"):
        return script, ""
    fixed = [dict(s) for s in scenes]
    fixed[-1]["narration"] = line
    return {**script, "scenes": fixed}, " ".join(str(data.get("why") or "").split())


RESTATED = """
You are the script editor of a YouTube documentary, reading its narration for one fault only:
lines that say again what the film has already said, adding nothing. Viewers feel it as padding
and leave. A line restates when its point was already made by an earlier line, whatever the
wording ("Space empties out as you climb" after "Clear the atmosphere and resistance falls to
nothing"). It does not restate if it adds a new fact, number, example or consequence; and one
deliberate callback to the film's central question in a chapter is fine.

For each restating line give its `scene`, the `earlier` scene that made the point, and
`narration`: the line rewritten to move the film on instead, with the next concrete detail,
example or consequence the story needs there. Never invent a fact: a new fact must be well
established and checkable; if you aren't sure, use an everyday example or a consequence of what
the film has already said. Keep the same length and voice, keep any [cue] at
its start, and make it fit the lines either side and the picture it's spoken over. At most
{most}, the worst first; most films have only a few.
""".strip()
RESTATED_MAX = 10


def restatements(script: dict) -> tuple:
    """(the script with lines that only repeat an earlier point rewritten,
    [{scene, earlier}]): one small call (decision 093). The checks above
    catch a phrase said word for word; the owner heard the drill film make
    the same points again in new words ("repeats itself a couple of
    times"), which only a reader catches."""
    scenes = script["scenes"]
    lines = [f"{i}. [chapter {s['chapter']}] {s['narration']}"
             + (f"   (picture: {' '.join(s.get('direction', '').split()[:14])})" if s.get("medium") != "card" else "")
             for i, s in enumerate(scenes)]
    schema = {"type": "object", "properties": {"repeats": {"type": "array", "items": {
        "type": "object", "properties": {"scene": {"type": "integer"}, "earlier": {"type": "integer"},
                                         "narration": {"type": "string"}},
        "required": ["scene", "earlier", "narration"], "additionalProperties": False}}},
        "required": ["repeats"], "additionalProperties": False}
    data = call_json(RESTATED.replace("{most}", str(RESTATED_MAX)), "The narration:\n" + "\n".join(lines), schema,
                     operation="documentary_restated", max_tokens=8000, effort="low")
    fixed, notes = [dict(s) for s in scenes], []
    for row in (data.get("repeats") or [])[:RESTATED_MAX]:
        i, j = row.get("scene"), row.get("earlier")
        # The lines are shown to it as "[chapter 3] ..."; it once copied that in.
        text = re.sub(r"^\[chapter \d+\]\s*", "", " ".join(str(row.get("narration") or "").split()), flags=re.I)
        if isinstance(i, int) and isinstance(j, int) and 0 <= j < i < len(fixed) and text and i != len(fixed) - 1:
            fixed[i]["narration"] = text
            notes.append({"scene": i, "earlier": j})
    return {**script, "scenes": fixed}, notes


def edit(channel, title: str, outline: dict, script: dict, angle: dict = None) -> dict:
    """The script with its weakest chapters written again, and `edits`
    saying which and why. A critic that can't be reached leaves the
    script as it is (the checks still count)."""
    from pipeline.documentary import script as scripts
    from pipeline.documentary import kinds as film_kinds
    problems = checks(script, outline, angle, film_kinds.of(channel))
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
    # Before the fact check, so the lines it writes are checked too.
    restated = []
    try:
        script, restated = restatements(script)
    except PipelineError as exc:
        log.warning(f"  [documentary] repeated points weren't looked for ({exc})")
    if restated:
        log.info(f"  [documentary] {len(restated)} line(s) that repeated an earlier point rewritten")
    facts = []
    if film_kinds.of(channel) == "explainer":
        try:
            script, facts = fact_check(script)
        except PipelineError as exc:
            log.warning(f"  [documentary] the fact check failed ({exc}); the script is unchecked")
        for f in facts:
            where = "the description" if f["scene"] < 0 else f"scene {f['scene'] + 1}"
            log.info(f"  [documentary] {where} corrected: {f['problem'][:160]}")
    ending = ""
    try:
        script, ending = final_line(channel, title, script)
    except PipelineError as exc:
        log.warning(f"  [documentary] the last line wasn't looked at ({exc})")
    if ending:
        log.info(f"  [documentary] last line rewritten: {ending[:160]}")
    # Every picture looked at together (decision 092).
    from pipeline.documentary import pictures
    try:
        script = pictures.plan(outline, script, film_kinds.of(channel))
        planned = script["pictures"]
        log.info(f"  [documentary] pictures planned: {len(planned['changes'])} changed, "
                 f"{planned['shown_again']} shown again")
    except PipelineError as exc:
        log.warning(f"  [documentary] the picture editor failed ({exc}); the rules alone applied")
        script = {**script, "scenes": pictures.validate(outline, script["scenes"])}
    script = {**script, "edits": edits, "facts": facts, "ending": ending, "restated": restated,
              "review": {str(n): reviews[n]["score"] for n in reviews}}
    return script
