"""
Example pictures for every material (the style grammar's "What is it all
made of?"): the same four subjects drawn in each, at its defaults, so
materials can be compared side by side while choosing (decision 053).

The subjects are fixed and chosen to show what matters when picking a
medium: a person in a place, a face lit close, an animal in nature, an
everyday interior. Kept with the grammar (style/materials/, in git),
since they're part of what an option means; `draw` makes any that are
missing, or all of them again with `force` (about 1 cent each).
"""

from __future__ import annotations

from pathlib import Path

from core import job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR
from pipeline.animation import images, models, style

log = get_logger(__name__)

SAMPLES_DIR = style.HERE / "materials"
SIZE = (540, 960)                 # what the settings page shows; drawn at 864x1536

SUBJECTS = (
    ("A person in a place",
     "A young woman in a long red scarf stands on a windswept hilltop at dusk, looking out over "
     "a small valley town where the first windows are lighting up; her scarf and hair lift in "
     "the wind, clouds glowing above."),
    ("A face, lit close",
     "An old man with a white beard sits in a dark room, holding a small glowing lantern in both "
     "hands close to his face; its warm light catches his eyes and the lines of his smile."),
    ("An animal in nature",
     "A red fox trots across a snowy forest clearing between tall pines in early morning light, "
     "its breath misting, soft snow falling, pale sunbeams slanting through the trees."),
    ("An everyday interior",
     "A child sits at a kitchen table doing homework in late-afternoon sun, chin in hand, while a "
     "ginger cat watches from the windowsill beside a row of potted plants and a steaming mug."),
)


def materials() -> list:
    return [o["id"] for o in style.grammar()["by_id"]["material"]["options"] if not o.get("custom")]


def material_look(material: str) -> dict:
    """What a picture prompt needs to draw in this material, alone. A
    material that only makes sense on its own ground (minimal maths
    graphics, on black) says so in `sample`, for its examples only."""
    sets = style.q_option("material", material).get("sets") or {}
    image = sets.get("image", "") + (f"; {sets['sample']}" if sets.get("sample") else "")
    return {"image": image, "light": sets.get("light", ""),
            "palette": sets.get("palette") or [], "avoid": sets.get("avoid", "photorealism"),
            "label": style.q_option("material", material).get("label", material)}


def path(material: str, n: int) -> Path:
    return SAMPLES_DIR / f"{material}_{n + 1}.jpg"


def available(material: str) -> list:
    """(index, label, path) for each example this material has on disk."""
    return [(n, SUBJECTS[n][0], path(material, n)) for n in range(len(SUBJECTS))
            if path(material, n).exists()]


def _draw_one(material: str, n: int) -> Path:
    from PIL import Image

    from pipeline.animation.bible import frame_prompt
    look = material_look(material)
    full = CACHE_DIR / "look_samples" / f"{material}_{n + 1}_full.jpg"
    images.draw(frame_prompt(SUBJECTS[n][1], look), full,
                models.image_model(models.BIBLE_IMAGE_MODEL), operation="animation_look_sample")
    image = Image.open(full).convert("RGB").resize(SIZE, Image.LANCZOS)
    out = path(material, n)
    image.save(out, format="JPEG", quality=86, optimize=True, progressive=True)
    full.unlink(missing_ok=True)
    log.info(f"  [animation] example {n + 1} for {look['label']}")
    return out


def draw(keys=None, force: bool = False) -> list:
    """Draw the examples that are missing (or all of them, with `force`)
    for these materials (every one by default). Returns the new paths."""
    keys = [k for k in (keys or materials()) if k in materials()]
    todo = [(k, n) for k in keys for n in range(len(SUBJECTS))
            if force or not path(k, n).exists()]
    if not todo:
        return []
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    def one(item):
        try:
            return _draw_one(*item)
        except PipelineError as exc:
            # One refused picture shouldn't cost the rest; it stays
            # missing, and the next run draws it.
            log.warning(f"  [animation] example {item[1] + 1} for {item[0]} failed: {exc}")
            return None
    # images.draw paces every call to the account's per-minute limit.
    return [p for p in job_context.parallel_map(one, todo, max_workers=4) if p]
