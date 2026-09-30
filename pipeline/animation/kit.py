"""
The kit for composited formats (decision 052): every object a channel's
videos use, drawn once in its look and kept, the surface its tabletop
stands on, and its narrator in a few poses.

Objects are cut-outs (transparent), drawn from the view the format needs
(from above for a tabletop, face on for a canvas), and filed by name, so
a channel's felt brain is the same felt brain in every video and costs
nothing after the first. The storyboard is shown the kit's names and
reuses them.

Kept with the channel's bible: channels/<key>/animation/<look>/.
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
from pipeline.animation import bible, images, look as looks, models
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


def _index_path(channel_key: str, look: dict, view: str) -> Path:
    return _folder(channel_key, look, f"kit_{view}") / "kit.json"


def index(channel_key: str, look: dict, view: str) -> dict:
    """{key: {"name", "description", "file"}} of the objects drawn so far."""
    try:
        return json.loads(_index_path(channel_key, look, view).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _view(fmt: dict) -> str:
    return "top" if fmt.get("continuity") == "move" else "front"


def object_prompt(name: str, description: str, fmt: dict, look: dict) -> str:
    return (f"A single {name}: {description}. {fmt['kit_view']} "
            f"{looks.style_text(look)} One object only, no text, letters or numbers on it.")


def objects(channel, look: dict, fmt: dict, wanted: dict, model=None) -> dict:
    """{key: picture} for every object in `wanted` ({key: {"name",
    "description"}}), drawing the ones this channel doesn't have yet."""
    view = _view(fmt)
    folder = _folder(channel.key, look, f"kit_{view}")
    have = index(channel.key, look, view)
    todo = [(k, v) for k, v in wanted.items()
            if not (k in have and (folder / have[k]["file"]).exists())]
    model = model or models.image_model(channel.animation.image_model)

    def draw(item):
        key, spec = item
        raw = folder / f".{key}_raw.png"
        try:
            images.draw(object_prompt(spec["name"], spec.get("description") or spec["name"], fmt,
                                      look), raw, model, size=(1024, 1024), transparent=True,
                        operation="animation_kit")
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
        log.info(f"  [animation] drawing {len(todo)} new object(s) for the kit")
        for key, spec, out in job_context.parallel_map(draw, todo, max_workers=3):
            if out is None:
                continue
            with _lock:
                have = index(channel.key, look, view)
                have[key] = {"name": spec["name"], "description": spec.get("description", ""),
                             "file": out.name}
                _index_path(channel.key, look, view).write_text(json.dumps(have, indent=1),
                                                                encoding="utf-8")
    have = index(channel.key, look, view)
    return {k: folder / have[k]["file"] for k in wanted
            if k in have and (folder / have[k]["file"]).exists()}


def aspects(pictures: dict) -> dict:
    out = {}
    for key, path in pictures.items():
        with Image.open(path) as im:
            out[key] = im.width / max(1, im.height)
    return out


def surface(channel, look: dict, fmt: dict) -> Path:
    """The tabletop's surface for this look, drawn once."""
    path = bible.folder(channel.key, look) / f"surface_{fmt['key']}.jpg"
    if path.exists():
        return path
    text = fmt["surface"].format(surface=look.get("surface") or
                                 "a clean, warm-white surface with a very subtle texture")
    raw = path.with_suffix(".raw.jpg")
    images.draw(f"{text}\nArt direction: {look['light']}.", raw,
                models.image_model(models.BIBLE_IMAGE_MODEL), size=SURFACE_SIZE,
                operation="animation_surface")
    Image.open(raw).convert("RGB").resize((1080, 1920), Image.LANCZOS).save(path, quality=92)
    raw.unlink(missing_ok=True)
    return path


def narrator(channel, look: dict, fmt: dict) -> dict:
    """{pose and pose_open: picture} for the canvas narrator, drawn once:
    the channel's first cast member if it has one, else the format's."""
    folder = _folder(channel.key, look, "narrator")
    cast = bible.cast_members(channel)
    who = (f"{cast[0]['name']}: {cast[0].get('description') or ''}" if cast
           else fmt.get("narrator", "a simple narrator character"))
    stamp = folder / "who.txt"
    if stamp.exists() and stamp.read_text(encoding="utf-8") != who:
        for old in folder.glob("*.png"):
            old.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    stamp.write_text(who, encoding="utf-8")
    model = models.image_model(models.BIBLE_IMAGE_MODEL)
    base = folder / "talk.png"
    view = fmt["kit_view"].replace("A single flat icon", "A single character")
    if not base.exists():
        _draw_pose(f"The narrator of an animated explainer: {who}. Full body, {POSES['talk']}, "
                   f"mouth closed. {view} {looks.style_text(look)} No text.", base, model)
    for pose, words in POSES.items():
        path = folder / f"{pose}.png"
        if not path.exists():
            _draw_pose(f"Exactly the same character as the reference picture (same design, "
                       f"proportions, colours and line), full body, now {words}, mouth closed. "
                       f"Same framing and size on the canvas. {view} No text.", path, model,
                       [base])
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


def narrator_size(pictures: dict) -> float:
    """Height to width of the narrator's canvas."""
    first = next(iter(pictures.values()))
    with Image.open(first) as im:
        return im.height / max(1, im.width)
