"""
The kit for composited styles (decisions 052, 053): every object,
character and backdrop a channel's videos use, drawn once in its style
and kept; the surface they stand on; and its host in a few poses.

Objects and characters are cut-outs (transparent), drawn from the view
the style needs (from above for a tabletop, standing at an angle on a
board, face on for a canvas or a stage). Backdrops fill the frame. All
are filed by key, so a channel's felt brain is the same felt brain in
every video and costs nothing after the first. The storyboard is shown
the kit's keys and reuses them.

Kept with the channel's style: channels/<key>/animation/<style>/.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from PIL import Image

from core import job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import slugify
from pipeline.animation import bible, frame as frames, images, look as looks, models
from pipeline.scenes import props

log = get_logger(__name__)

OBJECT_SIDE = 820          # big enough for the hero layout at full size
NARRATOR_HEIGHT = 1000
SURFACE_SIZE = (1008, 1792)
POSES = {
    "talk": "standing, facing the viewer, arms relaxed at the sides",
    "point": "pointing with one arm stretched out to the right side, looking towards it",
    "shrug": "shrugging, both palms up, eyebrows raised",
    "think": "one hand on the chin, looking up, thinking",
}
_lock = threading.Lock()


def _folder(channel_key: str, look: dict, part: str) -> Path:
    return bible.folder(channel_key, look) / part


def view(fmt: dict) -> str:
    return fmt.get("view") or "front"


def _index_path(channel_key: str, look: dict, where: str) -> Path:
    return _folder(channel_key, look, f"kit_{where}") / "kit.json"


def index(channel_key: str, look: dict, where: str, every_frame: bool = False) -> dict:
    """{key: {"name", "kind", "description", "file"}} drawn so far. A
    backdrop drawn for a widescreen frame is filed as "key@wide" beside the
    vertical one; those copies are listed only with `every_frame`."""
    try:
        data = json.loads(_index_path(channel_key, look, where).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if every_frame else {k: v for k, v in data.items() if "@" not in k}


def _slot(key: str, spec: dict, f) -> str:
    """Where a thing is filed: a backdrop fills the frame, so each frame
    shape has its own; everything else serves both."""
    return key if spec.get("kind") != "backdrop" or f.vertical else f"{key}@{f.key}"


def prompt_for(spec: dict, fmt: dict, look: dict) -> str:
    name = spec["name"]
    description = spec.get("description") or name
    if spec.get("kind") == "backdrop":
        return (fmt.get("backdrop") or "A backdrop: {scene}.").replace("{scene}", description) + \
            f" {looks.style_text(look)}"
    who = (f"A single character, {name}: {description}. Draw them as the style says people "
           f"look: {look.get('people') or 'simple and expressive'}."
           if spec.get("kind") == "character" else f"A single {name}: {description}.")
    return (f"{who} {fmt['kit_view']} {looks.style_text(look)} "
            f"One subject only, no text, letters or numbers on it.")


def objects(channel, look: dict, fmt: dict, wanted: dict, model=None) -> dict:
    """{key: picture} for everything in `wanted` ({key: {"name", "kind",
    "description"}}), drawing what this channel doesn't have yet."""
    where = view(fmt)
    f = frames.get(fmt.get("frame"))
    folder = _folder(channel.key, look, f"kit_{where}")
    have = index(channel.key, look, where, every_frame=True)
    slots = {k: _slot(k, v, f) for k, v in wanted.items()}
    todo = [(slots[k], v) for k, v in wanted.items()
            if not (slots[k] in have and (folder / have[slots[k]]["file"]).exists())]
    model = model or models.image_model(channel.animation.image_model)

    def draw(item):
        key, spec = item
        backdrop = spec.get("kind") == "backdrop"
        raw = folder / f".{slugify(key, 'thing')}_raw.{'jpg' if backdrop else 'png'}"
        try:
            images.draw(prompt_for(spec, fmt, look), raw, model,
                        size=_drawn_size(f) if backdrop else (1024, 1024),
                        transparent=not backdrop, operation="animation_kit")
            if backdrop:
                out = folder / f"{slugify(key, 'backdrop')}.jpg"
                Image.open(raw).convert("RGB").resize((f.w, f.h), Image.LANCZOS).save(out, quality=92)
            else:
                out = folder / f"{slugify(key, 'object')}.png"
                out.write_bytes(props.clean(raw.read_bytes(), max_side=OBJECT_SIDE))
            return key, spec, out
        except PipelineError as exc:
            log.warning(f"  [animation] couldn't draw {spec['name']}: {exc}")
            return key, spec, None
        finally:
            raw.unlink(missing_ok=True)

    if todo:
        folder.mkdir(parents=True, exist_ok=True)
        log.info(f"  [animation] drawing {len(todo)} new thing(s) for the kit")
        for key, spec, out in job_context.parallel_map(draw, todo, max_workers=3):
            if out is None:
                continue
            with _lock:
                have = index(channel.key, look, where, every_frame=True)
                have[key] = {"name": spec["name"], "kind": spec.get("kind", "object"),
                             "description": spec.get("description", ""), "file": out.name}
                _index_path(channel.key, look, where).write_text(json.dumps(have, indent=1),
                                                                 encoding="utf-8")
    have = index(channel.key, look, where, every_frame=True)
    return {k: folder / have[slots[k]]["file"] for k in wanted
            if slots[k] in have and (folder / have[slots[k]]["file"]).exists()}


def aspects(pictures: dict) -> dict:
    out = {}
    for key, path in pictures.items():
        with Image.open(path) as im:
            out[key] = im.width / max(1, im.height)
    return out


def surface(channel, look: dict, fmt: dict) -> Path:
    """The surface the style's pieces stand on (a tabletop, a board, a
    whiteboard, a model landscape), drawn once for each frame shape."""
    f = frames.get(fmt.get("frame"))
    suffix = "" if f.vertical else f"_{f.key}"
    path = bible.folder(channel.key, look) / f"surface_{fmt['key']}{suffix}.jpg"
    if path.exists():
        return path
    raw = path.with_suffix(".raw.jpg")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Emptiness said twice: an art direction like "marker drawing" otherwise
    # invites doodles onto the board (a widescreen whiteboard came back
    # covered in them).
    images.draw(f"{fmt['surface']}\nArt direction: {look['image']}. {look.get('light', '')}.\n"
                f"It must be completely empty: nothing drawn, written, placed or doodled on it "
                f"anywhere; only the bare surface itself.",
                raw, models.image_model(models.BIBLE_IMAGE_MODEL), size=_drawn_size(f),
                operation="animation_surface")
    Image.open(raw).convert("RGB").resize((f.w, f.h), Image.LANCZOS).save(path, quality=92)
    raw.unlink(missing_ok=True)
    return path


def _drawn_size(f) -> tuple:
    """The size a whole-frame picture is generated at, for this frame."""
    return SURFACE_SIZE if f.vertical else (SURFACE_SIZE[1], SURFACE_SIZE[0])


def narrator(channel, look: dict, fmt: dict) -> dict:
    """{pose and pose_open: picture} for the host, drawn once: the
    channel's first cast member if it has one, else the style's."""
    folder = _folder(channel.key, look, "narrator")
    cast = bible.cast_members(channel)
    who = (f"{cast[0]['name']}: {cast[0].get('description') or ''}" if cast
           else fmt.get("narrator") or "a simple host character")
    stamp = folder / "who.txt"
    if stamp.exists() and stamp.read_text(encoding="utf-8") != who:
        for old in folder.glob("*.png"):
            old.unlink()
        (folder / "cropped.txt").unlink(missing_ok=True)
    folder.mkdir(parents=True, exist_ok=True)
    stamp.write_text(who, encoding="utf-8")
    model = models.image_model(models.BIBLE_IMAGE_MODEL)
    base = folder / "talk.png"
    face_on = ("Full body, face on, whole figure visible with a margin, isolated on a "
               "transparent background, no shadow.")
    if not base.exists():
        _draw_pose(f"The host of an animated explainer: {who}. {POSES['talk']}, mouth closed. "
                   f"{face_on} {looks.style_text(look)} No text.", base, model)
    for pose, words in POSES.items():
        path = folder / f"{pose}.png"
        if not path.exists():
            _draw_pose(f"Exactly the same character as the reference picture (same design, "
                       f"proportions, colours and line), now {words}, mouth closed. Same framing "
                       f"and size on the canvas. {face_on} No text.", path, model, [base])
        open_path = folder / f"{pose}_open.png"
        if not open_path.exists():
            _draw_pose("Exactly the same picture of the same character in the same pose and "
                       "position; only the mouth is open, as if in the middle of a word. "
                       "Transparent background. No text.", open_path, model, [path])
    _crop_together(folder)
    return {p.stem: p for p in folder.glob("*.png")}


def _crop_together(folder: Path) -> None:
    """Every pose cropped to the box that holds all of them: the figure
    fills its height on screen, and stays put as the pose changes."""
    marker = folder / "cropped.txt"
    pictures = sorted(folder.glob("*.png"))
    names = "\n".join(p.name for p in pictures)
    if not pictures or (marker.exists() and marker.read_text(encoding="utf-8") == names):
        return
    box = None
    for p in pictures:
        with Image.open(p) as im:
            b = im.convert("RGBA").getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                         max(box[2], b[2]), max(box[3], b[3]))
    if box:
        pad = 12
        for p in pictures:
            with Image.open(p) as im:
                im = im.convert("RGBA")
                crop = im.crop((max(0, box[0] - pad), max(0, box[1] - pad),
                                min(im.width, box[2] + pad), min(im.height, box[3] + pad)))
            crop.save(p)
    marker.write_text(names, encoding="utf-8")


def _draw_pose(prompt: str, out: Path, model, references=()) -> Path:
    raw = out.with_name(f".{out.stem}_raw.png")
    images.draw(prompt, raw, model, references=references, size=images.PORTRAIT,
                transparent=True, operation="animation_narrator")
    out.write_bytes(props.clean(raw.read_bytes(), max_side=NARRATOR_HEIGHT, trim=False))
    raw.unlink(missing_ok=True)
    return out
