"""
The script: a documentary's narration written as a play (decision 074).

Scene by scene, each with a stage direction (where we are, who is there,
what happens, the framing) and the words spoken over it, following the
approved outline chapter by chapter. A scene is one picture held while
its words are said, about `documentary.scene_seconds` long, so the
picture moves on with the story. Directions name the outline's cast
exactly, which is how each scene's still is drawn with the right model
sheets.

Written a chapter at a time, each call shown the narration before it:
a whole ten-minute script with its directions is more than one
non-streaming call can safely return, and a longer video never would be.

Each scene also has a medium (decision 086): a drawn picture, a real
painting of the period from a museum, or an animated card (a number, a
comparison, a quote, a timeline, a list, a map), so the screen isn't one
kind of picture for ten minutes. The narration is written for the ear
and for retention: short sentences, something specific in every scene,
the open loops kept open until their chapter. pipeline.documentary.editor
reads it afterwards and has the weakest chapters written again.
"""

from __future__ import annotations

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

MAX_TOKENS = 12000              # one chapter at a time
EFFORT = "medium"
# About 150 words a minute, an explainer's pace. The first film was
# written at 2.4 and voiced at 0.9 speed: 118 a minute, which dragged.
WORDS_PER_SECOND = 2.5
SHORT_OF = 0.85                 # a chapter below this share of its words is written again, once
FRAMINGS = ("extreme wide", "wide", "medium", "close-up", "extreme close-up")
CAMERA = ("push_in", "pull_out", "pan_left", "pan_right", "still")
MEDIA = ("picture", "painting", "card")
CARD_KINDS = ("none", "number", "versus", "quote", "timeline", "list", "map")

SYSTEM = """
You write the narration script of a documentary as a play: scene by
scene, each with its stage direction and the words the narrator speaks
over it. The plan (chapters, what each says and shows, the cast, the
through-line and the visual concept) is approved; follow it, one
chapter at a time as asked.

Each scene is one picture held while its narration is spoken (the
editor cuts several shots from it), so:
- `narration`: what is said over this picture: one to three spoken
  sentences, written for the ear. The words of consecutive scenes read
  as one continuous narration; never restart or summarise.
- `direction`: the stage direction for the painter: where we are, who
  is there and what they're doing, the moment caught, the time of day
  and its light. One concrete, drawable moment, never a montage or a
  diagram. No text, signs or writing in the picture. Daylight scenes are
  bright and clear; darkness only when it really is night or a closed
  room, and even then lit by something.
- `cast`: the outline's cast members in the picture, by their exact
  names. Anyone else in it is described in the direction instead.
- `framing`: extreme wide, wide, medium, close-up or extreme close-up.
  Vary it as a film editor would.
- `camera`: how the picture moves while it's on screen: push_in,
  pull_out, pan_left, pan_right or still.
- `caption`: a short on-screen label when it helps the viewer (a place
  and year, a name and title), else empty. Never the narration.
- `chapter`: the chapter's number, from 1.
- `medium`: "picture" (drawn, the usual), "painting" (a real painting of
  the period, found in a museum's collection by `art_query`; only when
  the channel allows paintings) or "card" (an animated card over the
  picture before it, described in `card`). A card is for the rare fact
  that hits harder seen than heard (a shocking number, a stark
  comparison, a map when the story moves somewhere new): three in a film
  at most, never a list of rules, a summary or a timeline the narration
  already gives. A painting or card scene still has a `direction`, drawn
  instead if no painting fits.
- `speaker`: "" when the narrator speaks; when the channel uses
  dialogue, a cast member's exact name for a line that character says
  aloud in the moment (see below).
- `art_query`: for a painting, a short museum search for it ("Dutch
  street market", "plague doctor"), else "".
- `card`: for a card scene, its `kind` and words, which match what is
  said over it:
  - number: `value` the big number ("272", "2 hours"), `heading` a few
    words above it, `caption` a line below;
  - versus: two `items`, each "label|value" ("Everett|2 hours");
  - quote: `caption` the quoted words (under 25), `heading` who said them;
  - timeline: two to five `items`, each "when|what" ("1665|Plague");
  - list: `heading` and two to four short `items`;
  - map: `heading` the place's name, `caption` a short line (a year, a
    "you are here"), `lat` and `lon` where it is. Use a map when the
    story arrives somewhere new.
  For any other medium: kind "none", the rest empty and 0.

The film's first scene speaks the chosen angle's first line (tightened if
it needs to be) over the most striking picture in the film, and the
opening chapter raises the open loops. Its last scene lands the promise.

Make it a story, not a tour:
- Someone wants something concrete today (to get the bread out, to get
  a message through, to get out before the gate shuts) and every
  chapter puts something in the way. The viewer should always know what
  is wanted, what stands in the way and what it costs to fail.
- Things happen: people act, argue, lie, help, run. A scene where
  someone only watches or remembers is a scene to cut.
- Every chapter ends on a turn that makes the next one necessary: a
  knock, a choice, a bad surprise, a question.
- Say the film's big idea once, at the end, if at all. Never restate the
  theme or explain what a moment means; never close on a moral.
- Warmth and wit are welcome, even in dark places: a dry aside, a human
  detail, a small joke a person there would have made.

Write for the ear and for retention:
- Sentences of about fifteen words on average, some much shorter.
  Contractions. Concrete nouns, names and numbers: something specific in
  every scene, never a vague line that could be in any film.
- Keep each open loop open until the chapter that answers it, and bring
  the big question back now and then, so the viewer always knows what
  they're waiting for.
- No stock phrases: "here's the thing", "it's not X, it's Y", "little
  did they know", "a testament to", "tapestry", "journey", "delve",
  "turns out", "picture this", "let that sink in", and no neat
  symmetrical closing lines. Don't repeat a striking word: once is
  vivid, five times is a tic.
- Never pad. A chapter that needs more words gets more specifics, not
  more adjectives.
- Vary the music of it: a long sentence that rolls, then a short one.
  Then a fragment. Questions the viewer would ask. Real dynamics, from
  a whisper to urgency, so a voice has something to perform.

Narration is read by a voice engine exactly as written: no dashes, no
stage directions in it, numbers and dates written the way they're said.

`description`, asked for with the last chapter: two or three sentences
for the video's YouTube description, about the person and the story,
never about how it was made. Its first sentence holds the words someone
would search to find this film.
""".strip()


def schema() -> dict:
    card = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": list(CARD_KINDS)}, "heading": {"type": "string"},
        "value": {"type": "string"}, "caption": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
        "lat": {"type": "number"}, "lon": {"type": "number"}},
        "required": ["kind", "heading", "value", "caption", "items", "lat", "lon"],
        "additionalProperties": False}
    scene = {"type": "object", "properties": {
        "chapter": {"type": "integer"}, "direction": {"type": "string"},
        "cast": {"type": "array", "items": {"type": "string"}},
        "framing": {"type": "string", "enum": list(FRAMINGS)},
        "camera": {"type": "string", "enum": list(CAMERA)},
        "caption": {"type": "string"}, "narration": {"type": "string"},
        "medium": {"type": "string", "enum": list(MEDIA)}, "art_query": {"type": "string"},
        "card": card, "speaker": {"type": "string"}},
        "required": ["chapter", "direction", "cast", "framing", "camera", "caption", "narration",
                     "medium", "art_query", "card", "speaker"],
        "additionalProperties": False}
    return {"type": "object", "properties": {
        "scenes": {"type": "array", "items": scene}, "description": {"type": "string"}},
        "required": ["scenes", "description"], "additionalProperties": False}


def outline_text(outline: dict, angle: dict = None) -> str:
    chapters = "\n".join(f"{i}. {c['title']} (about {c['minutes']:g} min)\n   Says: {c['says']}\n"
                         + (f"   Turns on: {c['turn']}\n" if c.get("turn") else "")
                         + f"   Shows: {c['shows']}" for i, c in enumerate(outline["chapters"], start=1))
    cast = "\n".join(f"- {m['name']} ({m['kind']}): {m['description']}" for m in outline.get("cast") or [])
    loops = "\n".join(f"- {q}" for q in outline.get("open_loops") or [])
    from pipeline.documentary.outline import angle_text
    head = angle_text(angle or {})
    return ((f"{head}\n\n" if head else "")
            + (f"Promise: {outline['promise']}\n" if outline.get("promise") else "")
            + (f"What they want today: {outline['want']}\n" if outline.get("want") else "")
            + (f"Open loops (raised in the opening, answered later):\n{loops}\n" if loops else "")
            + f"Through-line: {outline.get('through_line', '')}\n"
            f"Visual concept: {outline.get('visual_concept', '')}\n\nChapters:\n{chapters}\n\n"
            f"Cast:\n{cast or '(none)'}")


DIALOGUE = """
This channel's films use dialogue. In most chapters, a few scenes are a
character speaking aloud in the moment: `speaker` is their exact cast
name, `narration` is only what they say (one or two short sentences,
plain words of the period, never explaining the plot, never "as you
know"), and the picture shows them saying it. Only characters in the
cast speak; the person the viewer plays never does. The narrator speaks
every other scene and never quotes a line a character has just said.
""".strip()

DELIVERY = """
The voice reads delivery cues. A line may begin with one cue in square
brackets when it changes how the line is said: [whispers], [softly],
[tense], [urgent], [warm], [wry], [sadly], [shocked], [sighs], [laughs
softly], [shouting]. Use them where a good narrator would change gear,
about one scene in four, never two in a row, never anything but these.
""".strip()


def _system(channel) -> list:
    from core import lessons
    from pipeline import artwork, tts
    extra = "" if artwork.allowed(channel) else ("\n\nThis channel doesn't show paintings: never use "
                                                 "the painting medium.")
    if getattr(channel.documentary, "dialogue", False):
        extra += "\n\n" + DIALOGUE
    else:
        extra += "\n\nThis channel doesn't use dialogue: `speaker` is always \"\"."
    if voice_model(channel) in tts.TAGGED_MODELS:
        extra += "\n\n" + DELIVERY
    taught = lessons.for_prompt(channel.key)
    return [SystemBlock(SYSTEM, cacheable=True),
            SystemBlock(f"The channel's brief for its writers:\n\n{channel.style_prompt}{extra}"
                        + (f"\n\n{taught}" if taught else ""))]


RATE_RANGE = (1.8, 3.2)         # words a second a measurement must fall in to be believed
RATE_FILMS = 5                  # the latest films a channel's rate is measured on


def words_per_second(channel) -> float:
    """How fast this channel's films are really narrated, pauses included:
    words over running time on its latest films, scaled to its voice's
    speed now; WORDS_PER_SECOND until it has made one. One Day In History's
    narrator ran at 2.9 a second, so a film planned at 2.5 came out 10.9
    minutes long instead of 14 (decision 086)."""
    import json
    import statistics
    from core import gallery
    root = gallery.resolve_output_dir(channel.output_dir) / gallery.LONGFORM_DIR
    found = []
    for path in root.glob("*/*_report.json") if root.exists() else ():
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        numbers = report.get("numbers") or {}
        if report.get("documentary") and numbers.get("words") and numbers.get("video_seconds"):
            rate = numbers["words"] / numbers["video_seconds"]
            rate *= float(channel.speed or 1.0) / float(numbers.get("speed") or 1.0)
            found.append((path.stat().st_mtime, rate))
    rates = [r for _, r in sorted(found)[-RATE_FILMS:] if RATE_RANGE[0] <= r <= RATE_RANGE[1]]
    return round(statistics.median(rates), 3) if rates else WORDS_PER_SECOND


def _chapter(channel, title: str, outline: dict, number: int, before: list, note: str = "",
             angle: dict = None) -> dict:
    """One chapter's scenes, written knowing the narration before it."""
    doc = channel.documentary
    chapter = outline["chapters"][number - 1]
    seconds = float(chapter["minutes"]) * 60
    scenes = max(2, round(seconds / float(doc.scene_seconds)))
    so_far = "\n".join(f"[{s['chapter']}] {s['narration']}" for s in before)
    target = round(seconds * words_per_second(channel))
    each = max(12, round(target / scenes))
    user = (f"The video: {title}\n\n{outline_text(outline, angle)}\n\n"
            + (f"The narration so far, chapter by chapter:\n{so_far}\n\n" if so_far else "")
            + f"Write chapter {number} of {len(outline['chapters'])} now: {target} words of narration "
              f"in all, in about {scenes} scenes of about {each} words each, continuing straight on "
              f"from the narration so far. The length matters: the chapter has {chapter['minutes']:g} "
              f"minutes of the film to fill.")
    if number == len(outline["chapters"]):
        user += " This is the last chapter: also write the `description`."
    else:
        user += " Leave `description` empty."
    if note:
        user += f"\n\nThe owner asks: {note}"
    out = None
    for attempt in range(2):
        data = call_json(_system(channel), user, schema(), operation="documentary_script",
                         max_tokens=MAX_TOKENS, effort=EFFORT)
        out = clean(data, outline, paintings=_paintings(channel),
                    dialogue=bool(getattr(channel.documentary, "dialogue", False)))
        got = words(out)
        if got >= SHORT_OF * target:
            break
        # The first film came out 919 words for a ten-minute plan (6.4
        # minutes): the writer keeps a chapter short unless told it is.
        log.info(f"  [documentary] chapter {number} came back {got} words of {target}; asking again")
        user += (f"\n\nYour last version of this chapter was {got} words; it needs about {target}. "
                 f"Write it again at full length: more scenes and fuller narration, not padding.")
    for s in out["scenes"]:
        s["chapter"] = number
    return out


def _paintings(channel) -> bool:
    from pipeline import artwork
    return artwork.allowed(channel)


def voice_model(channel) -> str:
    """The ElevenLabs model this documentary channel is voiced with."""
    from pipeline import tts
    return getattr(channel.documentary, "voice_model", "") or tts.ELEVENLABS_MODEL


def write(channel, title: str, outline: dict, note: str = "", angle: dict = None) -> dict:
    """The whole script from the approved outline, a chapter at a time.
    About ten cents for ten minutes."""
    scenes, description = [], ""
    for number in range(1, len(outline["chapters"]) + 1):
        part = _chapter(channel, title, outline, number, scenes, note, angle)
        scenes += part["scenes"]
        description = part["description"] or description
    return {"scenes": scenes, "description": description}


def rewrite_chapter(channel, title: str, outline: dict, script: dict, chapter: int, note: str,
                    angle: dict = None) -> dict:
    """One chapter's scenes written again with the owner's note, the rest
    kept. Returns the whole script."""
    before = [s for s in script["scenes"] if s["chapter"] < chapter]
    fresh = _chapter(channel, title, outline, chapter, before, note or "a better version", angle)["scenes"]
    out = before + fresh + [s for s in script["scenes"] if s["chapter"] > chapter]
    return {**script, "scenes": out}


def clean_card(raw) -> dict:
    """A card's fields, checked: {} if it can't be shown."""
    raw = raw or {}
    kind = raw.get("kind") if raw.get("kind") in CARD_KINDS else "none"
    text = lambda k, n: " ".join(str(raw.get(k) or "").split())[:n]  # noqa: E731
    items = [" ".join(str(i).split())[:60] for i in raw.get("items") or [] if str(i).strip()]
    card = {"kind": kind, "heading": text("heading", 60), "value": text("value", 24),
            "caption": text("caption", 160), "items": items[:5]}
    if kind == "map":
        try:
            lat, lon = float(raw.get("lat")), float(raw.get("lon"))
        except (TypeError, ValueError):
            return {}
        if not (-80 <= lat <= 84 and -180 <= lon <= 180) or (lat == 0 and lon == 0) or not card["heading"]:
            return {}
        card.update(lat=round(lat, 3), lon=round(lon, 3))
    ok = {"none": False, "number": bool(card["value"]), "versus": len(items) >= 2,
          "quote": bool(card["caption"]), "timeline": len(items) >= 2, "list": len(items) >= 2,
          "map": True}[kind]
    return card if ok else {}


def clean(data: dict, outline: dict, paintings: bool = True, dialogue: bool = False) -> dict:
    names = {m["name"].lower(): m["name"] for m in outline.get("cast") or []}
    speakers = {m["name"].lower(): m["name"] for m in outline.get("cast") or []
                if m.get("kind", "character") == "character"}
    count = len(outline["chapters"])
    scenes = []
    for s in data.get("scenes") or []:
        narration = " ".join(str(s.get("narration") or "").split())
        direction = " ".join(str(s.get("direction") or "").split())
        if not narration or not direction:
            continue
        medium = s.get("medium") if s.get("medium") in MEDIA else "picture"
        card = clean_card(s.get("card")) if medium == "card" else {}
        query = " ".join(str(s.get("art_query") or "").split())[:60]
        if medium == "card" and not card:
            medium = "picture"
        if medium == "painting" and not (paintings and query):
            medium = "picture"
        scene = {
            "chapter": min(count, max(1, int(s.get("chapter") or 1))),
            "direction": direction,
            "cast": [names[n.strip().lower()] for n in s.get("cast") or [] if n.strip().lower() in names],
            "framing": s.get("framing") if s.get("framing") in FRAMINGS else "medium",
            "camera": s.get("camera") if s.get("camera") in CAMERA else "push_in",
            "caption": " ".join(str(s.get("caption") or "").split())[:80],
            "narration": narration, "medium": medium}
        if medium == "card":
            scene["card"] = card
        if medium == "painting":
            scene["art_query"] = query
        speaker = speakers.get(str(s.get("speaker") or "").strip().lower(), "") if dialogue else ""
        if speaker:
            scene["speaker"] = speaker
            if speaker not in scene["cast"]:
                scene["cast"].append(speaker)
        scenes.append(scene)
    if not scenes:
        raise PipelineError("script had no scenes",
                            user_message="The script came back without any scenes. Try again.")
    return {"scenes": scenes, "description": str(data.get("description") or "").strip()}


def words(script: dict) -> int:
    return sum(len(s["narration"].split()) for s in script["scenes"])
