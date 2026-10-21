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
    from pipeline.documentary import kinds
    if kinds.family(kind) == "explainer":
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
any [cue] at its start, or "" if the line itself is fine. Where the scene shows a card, check every
part of it: `card` is its corrected value or items in the card's own shape (its items joined with
" ; ", each "label|value" if the card's are, or the value), `card_heading` and `card_caption` its
corrected heading and caption; each "" where that part is fine. A card that says what its line, or
any corrected line, no longer says is a fault too, and so is a caption or heading that overstates.

Then read the YouTube description the same way, against the script as you've corrected it: a
number or claim the script no longer makes, or a stock phrase ("journey", "it turns out",
"delve"), is a fault. Give it rewritten in `description`, or "" if it's fine. Read the title and
thumbnail words too, when given: one that states a figure or claim the corrected script
contradicts goes in `title` (the title rewritten, as short and as gripping) or `thumbnail_words`
(two to four words), each "" if it's fine.
""".strip()


def _facts_schema() -> dict:
    row = {"type": "object", "properties": {
        "scene": {"type": "integer"}, "problem": {"type": "string"}, "narration": {"type": "string"},
        "card": {"type": "string"}, "card_heading": {"type": "string"}, "card_caption": {"type": "string"}},
        "required": ["scene", "problem", "narration", "card", "card_heading", "card_caption"],
        "additionalProperties": False}
    return {"type": "object", "properties": {"fixes": {"type": "array", "items": row},
                                             "description": {"type": "string"},
                                             "title": {"type": "string"}, "thumbnail_words": {"type": "string"}},
            "required": ["fixes", "description", "title", "thumbnail_words"], "additionalProperties": False}


def _card_text(card: dict) -> str:
    """A card's words, each part named, so a correction can say which part
    it fixes (decision 098: captions went uncorrected when they weren't)."""
    if not card:
        return ""
    bits = [f'heading "{card["heading"]}"' if card.get("heading") else "",
            f'value "{card["value"]}"' if card.get("value") else "",
            f'caption "{card["caption"]}"' if card.get("caption") else "",
            ("items " + " ; ".join(card["items"])) if card.get("items") else ""]
    return ", ".join(b for b in bits if b)


CARDS = """
You review a film's animated cards before anything is drawn. A card is one held frame over the
picture before it, and it has to hit harder seen than heard. Each card is listed with the line
spoken over it and the lines either side, and the film's title and thumbnail words are given.

A card earns its place only as one of these:
- number: a figure that is striking on its own (big, tiny, precise or surprising), with its
  unit, that the line says;
- versus: two parallel values of the same thing, in the same unit, where the difference is the
  point: measured
  ("Moon | 384,000 km" against "Deepest hole | 12 km"; "Predicted | 100°C" against "Measured |
  180°C") or a clean either way ("North of the equator | clockwise" against "South of the
  equator | counterclockwise");
- timeline: two to five dated events the narration gives, in order;
- list: three or four short, parallel items the narration around it names;
- map or quote, as they are.

Faults, each fixed or the card turned into a picture:
- a count of 0 or 1, or any number that only states the obvious ("Times it let go: 0",
  "What decided it: 1 hemisphere", "Altitude at tasting: 0 m");
- something that isn't a number on a number card ("by the mile");
- a versus of two vague descriptions, the same thing twice, or a thing against its absence
  ("built and worked smoothly" against the same; "rich, balanced" against "flat, muted"; "red
  octagon" against "no convention");
- the same figure as another card (keep the better one);
- a figure the narration around it doesn't say;
- a figure the title or thumbnail words contradict: say so in `problem`, and leave the figure as
  the narration says it. The narration is the authority; never change a card to match the
  title (the title gets corrected elsewhere);
- clunky, vague or cryptic wording (the heading is a few plain words; the caption one short
  line saying what the number is of);
- a year written with a thousands separator ("1,913").

Prefer fixing to removing: when the lines around a weak card hold a striking figure or a real
comparison, make that the card, giving its `kind`, `heading`, `value`, `caption` and `items`
(versus items "label|value", timeline items "when|what"), all matching what's said. Only when no
good card is there, set `picture` true: the scene shows its picture instead. A good card that
breaks no rule is left alone. List only the cards that change, with the scene number and the
problem in a few words.
""".strip()


def _cards_schema() -> dict:
    fix = {"type": "object", "properties": {
        "scene": {"type": "integer"}, "problem": {"type": "string"}, "picture": {"type": "boolean"},
        "kind": {"type": "string", "enum": ["number", "versus", "timeline", "list", "map", "quote"]},
        "heading": {"type": "string"}, "value": {"type": "string"}, "caption": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}}},
        "required": ["scene", "problem", "picture", "kind", "heading", "value", "caption", "items"],
        "additionalProperties": False}
    return {"type": "object", "properties": {"fixes": {"type": "array", "items": fix}},
            "required": ["fixes"], "additionalProperties": False}


def _figure(card: dict) -> str:
    """A card's figure, normalised, for spotting the same one twice."""
    value = (card or {}).get("value") or ""
    return " ".join(value.lower().replace(",", "").split())


def review_cards(script: dict, packaging: dict = None) -> tuple:
    """(the script with its cards fixed or made pictures, [{scene, problem}])
    (decision 113): cards that showed 0s and 1s, a versus of two
    descriptions, "by the mile" as a number, and the same figure twice. One
    call for all of a film's cards; then, whatever it said, a figure shown
    twice keeps only its first card."""
    asked = cards_prompt(script, packaging)
    data = call_json(CARDS, asked, _cards_schema(), operation="documentary_cards", max_tokens=8000,
                     effort="medium") if asked else {}
    return apply_cards(script, data)


def cards_prompt(script: dict, packaging: dict = None) -> str:
    """What the card review reads: each card with the lines around it, or
    "" for a film without cards."""
    scenes = script["scenes"]
    cards = [i for i, s in enumerate(scenes) if s.get("medium") == "card" and s.get("card")]
    if not cards:
        return ""
    listed = []
    for i in cards:
        before = scenes[i - 1]["narration"] if i > 0 else ""
        after = scenes[i + 1]["narration"] if i + 1 < len(scenes) else ""
        listed.append(f"Scene {i}: [card: {_card_text(scenes[i]['card'])}]\n  said over it: {scenes[i]['narration']}"
                      f"\n  before: {before}\n  after: {after}")
    packaged = ""
    if packaging:
        packaged = (f"The title: {packaging.get('title', '')}\n"
                    f"The thumbnail words: {(packaging.get('thumbnail') or {}).get('words', '')}\n\n")
    return packaged + "The cards:\n\n" + "\n\n".join(listed)


def apply_cards(script: dict, data: dict) -> tuple:
    """(the script with a card review's fixes made, [{scene, problem}]),
    then one figure, one card, whatever the review said."""
    from pipeline.documentary import script as scripts
    scenes = [dict(s) for s in script["scenes"]]
    cards = [i for i, s in enumerate(scenes) if s.get("medium") == "card" and s.get("card")]
    notes = []
    if cards:
        for row in (data or {}).get("fixes") or []:
            i = row.get("scene")
            if i not in cards:
                continue
            problem = " ".join(str(row.get("problem") or "").split())
            if row.get("picture"):
                scenes[i] = {**scenes[i], "medium": "picture", "card": {}}
            else:
                card = scripts.clean_card({k: row.get(k) for k in ("kind", "heading", "value", "caption", "items")}
                                          | {"lat": scenes[i]["card"].get("lat", 0),
                                             "lon": scenes[i]["card"].get("lon", 0)})
                if not card:
                    continue
                scenes[i] = {**scenes[i], "card": card}
            notes.append({"scene": i, "problem": problem})
    # Whatever the review said: one figure, one card.
    seen = set()
    for i, s in enumerate(scenes):
        if s.get("medium") != "card" or not s.get("card"):
            continue
        figure = _figure(s["card"])
        if figure and figure in seen:
            scenes[i] = {**s, "medium": "picture", "card": {}}
            notes.append({"scene": i, "problem": "the same figure as an earlier card"})
        elif figure:
            seen.add(figure)
    return {**script, "scenes": scenes}, notes


def fact_check(script: dict, packaging: dict = None) -> tuple:
    """(the script with wrong lines rewritten, [{scene, problem}]): one
    call over the whole narration, for explainers (decision 091). The first
    explainer needed nine lines fixed by hand: sixty times closer said as
    "six and a half", a 180-degree bit "glowing red", a prompt word left in."""
    data = call_json(FACTS, facts_prompt(script, packaging), _facts_schema(),
                     operation="documentary_fact_check", max_tokens=8000, effort="medium")
    return apply_facts(script, data, packaging)


def facts_prompt(script: dict, packaging: dict = None) -> str:
    """What the fact check reads: every line numbered, with its card, then
    the description, title and thumbnail words."""
    lines = [f"{i}. {s['narration']}" + (f"  [card: {_card_text(s.get('card'))}]" if s.get("card") else "")
             for i, s in enumerate(script["scenes"])]
    described = f"\n\nThe YouTube description:\n{script['description']}" if script.get("description") else ""
    if packaging:
        # A title said "ten thousand hooks per inch" over cards saying 300 (decision 113).
        described += (f"\n\nThe title it goes out with: {packaging.get('title', '')}"
                      f"\nIts thumbnail words: {(packaging.get('thumbnail') or {}).get('words', '')}")
    return "The script:\n" + "\n".join(lines) + described


def apply_facts(script: dict, data: dict, packaging: dict = None) -> tuple:
    """(the script with a fact check's fixes made, [{scene, problem}]):
    the API's answer or the newsroom's fact checker's, in FACTS's shape."""
    scenes = script["scenes"]
    fixed, notes = [dict(s) for s in scenes], []
    for row in data.get("fixes") or []:
        i, text = row.get("scene"), " ".join(str(row.get("narration") or "").split())
        if not isinstance(i, int) or not 0 <= i < len(fixed):
            continue
        card = fixed[i].get("card")
        new = str(row.get("card") or "").strip()
        heading = " ".join(str(row.get("card_heading") or "").split())
        caption = " ".join(str(row.get("card_caption") or "").split())
        if not text and not (card and (new or heading or caption)):
            continue
        if text:
            fixed[i]["narration"] = text
        if card and (heading or caption):
            card = {**card, **({"heading": heading} if heading else {}), **({"caption": caption} if caption else {})}
            fixed[i]["card"] = card
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
    retitle = {k: " ".join(str(data.get(k) or "").split()) for k in ("title", "thumbnail_words")}
    retitle = {k: v for k, v in retitle.items() if v}
    if packaging and retitle:
        out["packaging_fix"] = retitle
        notes.append({"scene": -2, "problem": "the title or thumbnail words: " + "; ".join(retitle.values())})
    return out, notes


FINAL = """
You decide a film's last line, the one the viewer leaves with. After it, the last picture is
held in silence and the film fades out. The last line has to close the film well: it makes sense
on its own to someone who has just watched, and leaves them with something from the film. It
doesn't have to repeat the title's question or its answer. Good closers include:
- the film's answer, said plainly ("Clocks turn clockwise because that's the way shadows fell
  on sundials north of the equator.");
- a "now you know": one more interesting thing the film has set up, landing it;
- a "next time you..." that turns what the film taught into something the viewer can notice or
  try ("Next time you're on a plane, try the tomato juice and see if you can taste the
  difference." "Next time you see a Velcro shoe, remember it all started with a burr on a dog.").
Short (under twenty five words) and final when spoken aloud.

A last line fails when it's cryptic, an image that only makes sense if you squint ("Look at your
shoe. A weed is still holding on."); an instruction without the context that makes it make sense
("Order the tomato juice."); a riddle, a question, a pat moral or a "subscribe"; or a "next time
on this channel" pointing at another video. First write `takeaway`: what this viewer should leave
with, in one plain sentence. Then judge the current last line honestly against the above: keep it
if it closes the film well. If not, write the line that should end this film, following on from
the line before it, in the channel's voice, using only facts and causes the narration gives.
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
    schema = {"type": "object", "properties": {"takeaway": {"type": "string"}, "keep": {"type": "boolean"},
                                               "line": {"type": "string"}, "why": {"type": "string"}},
              "required": ["takeaway", "keep", "line", "why"], "additionalProperties": False}
    data = call_json(FINAL, user, schema, operation="documentary_last_line", max_tokens=6000, effort="medium")
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


def edit(channel, title: str, outline: dict, script: dict, angle: dict = None, packaging: dict = None) -> dict:
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
    cards = []
    try:
        script, cards = review_cards(script, packaging or angle)
    except PipelineError as exc:
        log.warning(f"  [documentary] the cards weren't reviewed ({exc}); kept as written")
    for c in cards:
        log.info(f"  [documentary] card in scene {c['scene'] + 1}: {c['problem'][:160]}")
    facts = []
    if film_kinds.fact_checked(film_kinds.of(channel)):
        try:
            script, facts = fact_check(script, packaging or angle)
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
        script = pictures.plan(outline, script, film_kinds.family(film_kinds.of(channel)))
        planned = script["pictures"]
        log.info(f"  [documentary] pictures planned: {len(planned['changes'])} changed, "
                 f"{planned['shown_again']} shown again")
    except PipelineError as exc:
        log.warning(f"  [documentary] the picture editor failed ({exc}); the rules alone applied")
        script = {**script, "scenes": pictures.validate(outline, script["scenes"])}
    script = {**script, "edits": edits, "facts": facts, "ending": ending, "restated": restated, "cards": cards,
              "review": {str(n): reviews[n]["score"] for n in reviews}}
    return script
