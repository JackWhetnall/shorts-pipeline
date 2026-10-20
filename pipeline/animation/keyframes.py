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
import hashlib
import io
from pathlib import Path

from core import job_context
from core.paths import CACHE_DIR
from core.logging_setup import get_logger
from pipeline.animation import frame as frames, images, look as looks
from pipeline.llm import call_json

log = get_logger(__name__)

MAX_ELEMENT_REFS = 3
CHECK_SIZE = (640, 640)         # the longer side; a vertical frame comes out 360x640

# Decision 096. Every reference picture is billed at a fixed ~1,000 tokens
# whatever its size, so three or four of them cost three or four times one
# sheet holding them all: the references go as one sheet of numbered
# panels, the style on the left, the rest stacked on the right.
COMBINED_SIZE = (2048, 1152)
COMBINED_STYLE_SHARE = 0.58
COMBINED_DIR = CACHE_DIR / "reference_sheets"
PANELS = ("The one reference image is a grid of numbered panels (the number in each panel's corner). "
          "\"Image N\" below means panel N; the panels, their borders and numbers are references only "
          "and never appear in the frame.\n\n")


def combine(references: list) -> Path:
    """One sheet of numbered panels from `references` (paths, in the order
    the prompt names them), kept by what's in them so a film's pictures
    that share references share the sheet."""
    from PIL import Image, ImageDraw, ImageFont

    refs = [Path(r) for r in references]
    key = hashlib.sha1(b"".join(hashlib.sha1(r.read_bytes()).digest() for r in refs)).hexdigest()[:16]
    out = COMBINED_DIR / f"{key}.png"
    if out.exists():
        return out
    width, height = COMBINED_SIZE
    canvas = Image.new("RGB", COMBINED_SIZE, "white")
    pen = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arialbd.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    rest = refs[1:]
    left = int(width * COMBINED_STYLE_SHARE) if rest else width
    boxes = [(0, 0, left, height)] + [(left, k * height // len(rest), width, (k + 1) * height // len(rest))
                                      for k in range(len(rest))]
    for n, (ref, (x0, y0, x1, y1)) in enumerate(zip(refs, boxes), start=1):
        image = Image.open(ref).convert("RGB")
        image.thumbnail((x1 - x0 - 12, y1 - y0 - 12), Image.LANCZOS)
        canvas.paste(image, (x0 + (x1 - x0 - image.width) // 2, y0 + (y1 - y0 - image.height) // 2))
        pen.rectangle((x0, y0, x1 - 1, y1 - 1), outline="black", width=6)
        pen.rectangle((x0 + 6, y0 + 6, x0 + 70, y0 + 70), fill="black")
        pen.text((x0 + 22, y0 + 10), str(n), fill="white", font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Pictures drawn at once share a sheet, so two can make the same one at
    # the same moment: each writes its own part file, and on Windows the
    # second rename onto a sheet in use fails. Found on 20 Oct, drawing
    # three pictures with the same references. The sheets are identical,
    # so whichever landed is kept.
    import uuid
    partial = out.with_name(f"{key}.{uuid.uuid4().hex[:8]}.part.png")
    canvas.save(partial)
    try:
        partial.replace(out)
    except OSError:
        if not out.exists():
            raise
        partial.unlink(missing_ok=True)
    return out


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
        if element["kind"] == "character" and element.get("star"):
            # A recurring star changes clothes every scene (decision 124).
            lines.append(f"Image {n} is {element['name']}: the same face, hair, colouring and figure, "
                         f"dressed as this frame says.")
        elif element["kind"] == "character":
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
    lines.append(looks.frame_rules(look))
    if board.get("never"):
        # A documentary channel's "Never show" (decision 076).
        lines.append("Never show any of these: " + ", ".join(board["never"]) + ".")
    if fix:
        lines.append("Fix these problems from the last attempt: " + "; ".join(fix))
    return "\n".join(lines)


def path_for(folder: Path, shot: dict) -> Path:
    return Path(folder) / f"kf_{shot['index']:02d}.jpg"


def request(shot: dict, board: dict, look: dict, style_ref: Path, sheets: dict, folder: Path,
            model, fix: list = None, combined: bool = False) -> dict:
    """What drawing this shot's frame asks for, as images.draw_batch takes
    it (decision 094), so a storyboard can go as one batch. `combined`:
    its references as one sheet (decision 096)."""
    refs = references(shot, board, sheets)
    prompt = prompt_for(shot, board, look, refs, fix)
    paths = [style_ref] + [sheets[k] for k, _ in refs]
    if combined and len([p for p in paths if p]) > 1:
        paths, prompt = [combine([p for p in paths if p])], PANELS + prompt
    return {"key": shot["index"], "prompt": prompt, "out": path_for(folder, shot), "model": model,
            "references": paths, "size": frames.get(look.get("frame")).image,
            "operation": "animation_keyframe"}


def draw(shot: dict, board: dict, look: dict, style_ref: Path, sheets: dict, folder: Path,
         model, fix: list = None, combined: bool = False) -> Path:
    job = request(shot, board, look, style_ref, sheets, folder, model, fix, combined)
    if job["out"].exists() and not fix:
        return job["out"]
    return images.draw(job["prompt"], job["out"], model, references=job["references"],
                       size=job["size"], operation=job["operation"])


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
- a face or eyes on an object, machine or tool the shot doesn't ask to have one;
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
