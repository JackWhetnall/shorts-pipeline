"""
Keyframes: each shot's first frame, drawn with its references, and
looked at before anything is animated.

A keyframe costs a few cents and the shot animated from it about ten
times that, so this is where mistakes are cheapest to catch. Every frame
is drawn with the channel's style frame first and the model sheet of each
recurring character or place in it, then all of them are shown to a
vision model in one call beside those references: the wrong subject, a
character off-model, a frame in a different medium, writing, broken
anatomy or a subject sitting where the captions go. Those are redrawn
once with the problems named. What still fails is kept and noted; the
frame check on the finished video and the publish gate have the last
word.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from core import job_context
from core.logging_setup import get_logger
from pipeline.animation import images, look as looks
from pipeline.llm import call_json

log = get_logger(__name__)

MAX_ELEMENT_REFS = 3
CHECK_SIZE = (360, 640)


def references(shot: dict, board: dict, sheets: dict) -> list:
    """(key, element) for the sheets this shot's frame is drawn with:
    characters first, then places, then objects, at most three."""
    order = {"character": 0, "place": 1, "object": 2}
    keys = [k for k in shot["elements"] if k in sheets]
    keys.sort(key=lambda k: order.get(board["elements"][k]["kind"], 3))
    return [(k, board["elements"][k]) for k in keys[:MAX_ELEMENT_REFS]]


def prompt_for(shot: dict, board: dict, look: dict, refs: list, fix: list = None) -> str:
    lines = ["Image 1 is an art-style reference sheet of unrelated studies: match its medium, "
             "rendering, line, texture, palette and light exactly, and copy none of its studies "
             "into the frame."]
    for n, (key, element) in enumerate(refs, start=2):
        if element["kind"] == "character":
            lines.append(f"Image {n} is {element['name']}: draw them exactly as shown there, "
                         f"with the same face, hair, clothes, colours and proportions.")
        elif element["kind"] == "place":
            lines.append(f"Image {n} shows {element['name']}: keep its layout, materials and "
                         f"colours.")
        else:
            lines.append(f"Image {n} shows the {element['name']}: draw it the same.")
    lines.append(f"\nThe frame: a {shot['framing']} shot. {shot['image']}")
    described = [board["elements"][k] for k in shot["elements"] if k in board["elements"]]
    if described:
        lines.append("Who and what is in it: " + " ".join(
            f"{e['name']}: {e['description']}" for e in described if e.get("description")))
    if board.get("colour_script"):
        lines.append(f"The film's colour script, for this moment's light: {board['colour_script']}")
    lines.append(looks.style_text(look))
    lines.append(looks.FRAME_RULES)
    if fix:
        lines.append("Fix these problems from the last attempt: " + "; ".join(fix))
    return "\n".join(lines)


def path_for(folder: Path, shot: dict) -> Path:
    return Path(folder) / f"kf_{shot['index']:02d}.jpg"


def draw(shot: dict, board: dict, look: dict, style_ref: Path, sheets: dict, folder: Path,
         model, fix: list = None) -> Path:
    refs = references(shot, board, sheets)
    out = path_for(folder, shot)
    if out.exists() and not fix:
        return out
    return images.draw(prompt_for(shot, board, look, refs, fix), out, model,
                       references=[style_ref] + [sheets[k] for k, _ in refs],
                       operation="animation_keyframe")


def draw_all(shots: list, board: dict, look: dict, style_ref: Path, sheets: dict, folder: Path,
             model) -> dict:
    """{shot index: keyframe path} for every shot that starts from its own
    frame (a continued take starts from the last frame of the one before)."""
    todo = [s for s in shots if not s.get("continues")]
    paths = job_context.parallel_map(
        lambda s: draw(s, board, look, style_ref, sheets, folder, model), todo, max_workers=3)
    return {s["index"]: p for s, p in zip(todo, paths)}


def thumbnail(path: Path, size=CHECK_SIZE) -> tuple:
    from PIL import Image

    image = Image.open(path).convert("RGB")
    image.thumbnail(size, Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=82)
    return "image/jpeg", base64.b64encode(out.getvalue()).decode()


CHECK = """
These are the first frames of an animated short, about to be animated (which is expensive).
First comes the channel's style reference sheet (unrelated studies in its style: frames must
match its style, never its content), then a reference sheet for each recurring character or
place, then each shot's first frame with what it should show.

For each shot, list only real problems that would spoil it:
- it doesn't show what the shot asks for: the wrong subject, a named element missing, the wrong
  action or pose;
- it's off-style: plainly a different medium from the style reference (photographic or 3D when
  the reference is painted, say), or it copies one of the reference sheet's studies;
- a recurring character is off-model: a different face, hair, clothes or colours from their sheet;
- it has text, letters, numbers, signs or gibberish writing anywhere;
- broken anatomy: extra or missing fingers or limbs, a melted or doubled face;
- the main subject sits in the bottom third or is cropped awkwardly.
Small imperfections are fine. ok is false only for the problems above; say each one in a short
sentence the artist can act on.
""".strip()


def _check_schema() -> dict:
    return {"type": "object", "properties": {"shots": {"type": "array", "items": {
        "type": "object", "properties": {
            "index": {"type": "integer"}, "ok": {"type": "boolean"},
            "problems": {"type": "array", "items": {"type": "string"}}},
        "required": ["index", "ok", "problems"], "additionalProperties": False}}},
        "required": ["shots"], "additionalProperties": False}


def check(shots: list, frames: dict, board: dict, style_ref: Path, sheets: dict) -> dict:
    """{shot index: [problems]} for the frames that need redrawing."""
    todo = [s for s in shots if s["index"] in frames]
    if not todo:
        return {}
    pictures = [("text", "The style reference:"), thumbnail(style_ref, (300, 533))]
    used = {k for s in todo for k in s["elements"] if k in sheets}
    for key in sorted(used):
        pictures += [("text", f"Reference sheet: {board['elements'][key]['name']}"),
                     thumbnail(sheets[key], (480, 320))]
    for s in todo:
        pictures += [("text", f"Shot {s['index']} should show ({s['framing']}): {s['image']}"),
                     thumbnail(frames[s["index"]])]
    data = call_json(CHECK, "Check every shot above.", _check_schema(), images=pictures,
                     operation="animation_keyframe_check", max_tokens=6000)
    wanted = {s["index"] for s in todo}
    return {r["index"]: [p for p in r.get("problems") or [] if p]
            for r in data.get("shots") or []
            if r.get("index") in wanted and not r.get("ok") and r.get("problems")}
