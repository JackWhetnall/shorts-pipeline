"""
Example pictures for every look: the same four subjects drawn in each, at
the look's defaults, so looks can be compared side by side before one is
chosen (Settings -> Animation shows them on each look's card).

The subjects are fixed and chosen to show what matters when picking a
style: a person in a place, a face lit close, an animal in nature, an
everyday interior. Kept with the presets (looks/samples/, in git), since
they're part of what a look is; `draw` makes any that are missing, or all
of them again with `force` (about 1 cent each).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core import job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR
from pipeline.animation import images, look as looks, models

log = get_logger(__name__)

SAMPLES_DIR = looks.LOOKS_DIR / "samples"
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


def path(look_key: str, n: int) -> Path:
    return SAMPLES_DIR / f"{look_key}_{n + 1}.jpg"


def available(look_key: str) -> list:
    """(index, label, path) for each example this look has on disk."""
    return [(n, SUBJECTS[n][0], path(look_key, n)) for n in range(len(SUBJECTS))
            if path(look_key, n).exists()]


def _draw_one(look_key: str, n: int) -> Path:
    from PIL import Image

    look = looks.resolve(SimpleNamespace(look=look_key))
    from pipeline.animation.bible import frame_prompt
    full = CACHE_DIR / "look_samples" / f"{look_key}_{n + 1}_full.jpg"
    images.draw(frame_prompt(SUBJECTS[n][1], look), full,
                models.image_model(models.BIBLE_IMAGE_MODEL), operation="animation_look_sample")
    image = Image.open(full).convert("RGB")
    image = image.resize(SIZE, Image.LANCZOS)
    out = path(look_key, n)
    image.save(out, format="JPEG", quality=86, optimize=True, progressive=True)
    full.unlink(missing_ok=True)
    log.info(f"  [animation] example {n + 1} for {look['label']}")
    return out


def draw(look_keys=None, force: bool = False) -> list:
    """Draw the examples that are missing (or all of them, with `force`)
    for these looks (every look by default). Returns the new paths."""
    keys = [k for k in (look_keys or looks.presets()) if k in looks.presets()]
    todo = [(k, n) for k in keys for n in range(len(SUBJECTS))
            if force or not path(k, n).exists()]
    if not todo:
        return []
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    def one(item):
        try:
            return _draw_one(*item)
        except PipelineError as exc:
            # One refused picture shouldn't cost the other thirty-nine; it
            # stays missing, and the next run draws it.
            log.warning(f"  [animation] example {item[1] + 1} for {item[0]} failed: {exc}")
            return None
    # images.draw paces every call to the account's per-minute limit.
    return [p for p in job_context.parallel_map(one, todo, max_workers=4) if p]
