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
"""

from __future__ import annotations

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

MAX_TOKENS = 12000              # one chapter at a time
EFFORT = "medium"
WORDS_PER_SECOND = 2.4          # a documentary narrator, a touch slower than a short's
FRAMINGS = ("extreme wide", "wide", "medium", "close-up", "extreme close-up")
CAMERA = ("push_in", "pull_out", "pan_left", "pan_right", "still")

SYSTEM = """
You write the narration script of a documentary as a play: scene by
scene, each with its stage direction and the words the narrator speaks
over it. The plan (chapters, what each says and shows, the cast, the
through-line and the visual concept) is approved; follow it, one
chapter at a time as asked.

Each scene is one illustrated picture, held while its narration is
spoken, so:
- `narration`: what is said over this picture: one to three spoken
  sentences, written for the ear. The words of consecutive scenes read
  as one continuous narration; never restart or summarise.
- `direction`: the stage direction for the painter: where we are, who
  is there and what they're doing, the moment caught, the light. One
  concrete, drawable moment, never a montage or a diagram. No text,
  signs or writing in the picture.
- `cast`: the outline's cast members in the picture, by their exact
  names. Anyone else in it is described in the direction instead.
- `framing`: extreme wide, wide, medium, close-up or extreme close-up.
  Vary it as a film editor would.
- `camera`: how the picture moves while it's on screen: push_in,
  pull_out, pan_left, pan_right or still.
- `caption`: a short on-screen label when it helps the viewer (a place
  and year, a name and title), else empty. Never the narration.
- `chapter`: the chapter's number, from 1.

The film's first scene is the hook: a picture and a line that put the
viewer inside the moment. Its last lands the through-line. Narration is
read by a voice engine exactly as written: no dashes, no stage
directions in it, numbers and dates written the way they're said.

`description`, asked for with the last chapter: two or three sentences
for the video's YouTube description, about the person and the story,
never about how it was made.
""".strip()


def schema() -> dict:
    scene = {"type": "object", "properties": {
        "chapter": {"type": "integer"}, "direction": {"type": "string"},
        "cast": {"type": "array", "items": {"type": "string"}},
        "framing": {"type": "string", "enum": list(FRAMINGS)},
        "camera": {"type": "string", "enum": list(CAMERA)},
        "caption": {"type": "string"}, "narration": {"type": "string"}},
        "required": ["chapter", "direction", "cast", "framing", "camera", "caption", "narration"],
        "additionalProperties": False}
    return {"type": "object", "properties": {
        "scenes": {"type": "array", "items": scene}, "description": {"type": "string"}},
        "required": ["scenes", "description"], "additionalProperties": False}


def outline_text(outline: dict) -> str:
    chapters = "\n".join(f"{i}. {c['title']} (about {c['minutes']:g} min)\n   Says: {c['says']}\n"
                         f"   Shows: {c['shows']}" for i, c in enumerate(outline["chapters"], start=1))
    cast = "\n".join(f"- {m['name']} ({m['kind']}): {m['description']}" for m in outline.get("cast") or [])
    return (f"Through-line: {outline.get('through_line', '')}\n"
            f"Visual concept: {outline.get('visual_concept', '')}\n\nChapters:\n{chapters}\n\n"
            f"Cast:\n{cast or '(none)'}")


def _system(channel) -> list:
    return [SystemBlock(SYSTEM, cacheable=True),
            SystemBlock(f"The channel's brief for its writers:\n\n{channel.style_prompt}")]


def _chapter(channel, title: str, outline: dict, number: int, before: list, note: str = "") -> dict:
    """One chapter's scenes, written knowing the narration before it."""
    doc = channel.documentary
    chapter = outline["chapters"][number - 1]
    seconds = float(chapter["minutes"]) * 60
    scenes = max(2, round(seconds / float(doc.scene_seconds)))
    so_far = "\n".join(f"[{s['chapter']}] {s['narration']}" for s in before)
    user = (f"The video: {title}\n\n{outline_text(outline)}\n\n"
            + (f"The narration so far, chapter by chapter:\n{so_far}\n\n" if so_far else "")
            + f"Write chapter {number} of {len(outline['chapters'])} now: about "
              f"{round(seconds * WORDS_PER_SECOND)} words of narration in about {scenes} scenes, "
              f"continuing straight on from the narration so far.")
    if number == len(outline["chapters"]):
        user += " This is the last chapter: also write the `description`."
    else:
        user += " Leave `description` empty."
    if note:
        user += f"\n\nThe owner asks: {note}"
    data = call_json(_system(channel), user, schema(), operation="documentary_script",
                     max_tokens=MAX_TOKENS, effort=EFFORT)
    out = clean(data, outline)
    for s in out["scenes"]:
        s["chapter"] = number
    return out


def write(channel, title: str, outline: dict, note: str = "") -> dict:
    """The whole script from the approved outline, a chapter at a time.
    About ten cents for ten minutes."""
    scenes, description = [], ""
    for number in range(1, len(outline["chapters"]) + 1):
        part = _chapter(channel, title, outline, number, scenes, note)
        scenes += part["scenes"]
        description = part["description"] or description
    return {"scenes": scenes, "description": description}


def rewrite_chapter(channel, title: str, outline: dict, script: dict, chapter: int, note: str) -> dict:
    """One chapter's scenes written again with the owner's note, the rest
    kept. Returns the whole script."""
    before = [s for s in script["scenes"] if s["chapter"] < chapter]
    fresh = _chapter(channel, title, outline, chapter, before, note or "a better version")["scenes"]
    out = before + fresh + [s for s in script["scenes"] if s["chapter"] > chapter]
    return {**script, "scenes": out}


def clean(data: dict, outline: dict) -> dict:
    names = {m["name"].lower(): m["name"] for m in outline.get("cast") or []}
    count = len(outline["chapters"])
    scenes = []
    for s in data.get("scenes") or []:
        narration = " ".join(str(s.get("narration") or "").split())
        direction = " ".join(str(s.get("direction") or "").split())
        if not narration or not direction:
            continue
        scenes.append({
            "chapter": min(count, max(1, int(s.get("chapter") or 1))),
            "direction": direction,
            "cast": [names[n.strip().lower()] for n in s.get("cast") or [] if n.strip().lower() in names],
            "framing": s.get("framing") if s.get("framing") in FRAMINGS else "medium",
            "camera": s.get("camera") if s.get("camera") in CAMERA else "push_in",
            "caption": " ".join(str(s.get("caption") or "").split())[:80],
            "narration": narration})
    if not scenes:
        raise PipelineError("script had no scenes",
                            user_message="The script came back without any scenes. Try again.")
    return {"scenes": scenes, "description": str(data.get("description") or "").strip()}


def words(script: dict) -> int:
    return sum(len(s["narration"].split()) for s in script["scenes"])
