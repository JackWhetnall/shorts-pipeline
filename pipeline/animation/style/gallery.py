"""
The starting points' example pictures (style/examples/<id>.jpg, in git):
each drawn by the same preview a channel gets (style.preview), on the
starting point's own subject, so the gallery shows what the system really
makes rather than something painted to look like it.

Drawn under a channel of their own ("_style_gallery"), whose kit is
throwaway; about 10 cents a composited style and 3 a generated one.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.animation import style
from pipeline.animation.style import preview

log = get_logger(__name__)

EXAMPLES_DIR = style.HERE / "examples"
GALLERY_CHANNEL = "_style_gallery"


def path(sid: str) -> Path:
    return EXAMPLES_DIR / f"{sid}.jpg"


def settings_for(sid: str):
    from core.channels import Animation
    sp = style.starting_point(sid)
    return sp, Animation(enabled=True, style=dict(sp["answers"]))


def draw(ids=None, force: bool = False) -> list:
    """Draw the missing examples (all of them again, with `force`)."""
    from PIL import Image

    ids = [s["id"] for s in style.starting_points() if not ids or s["id"] in ids]
    made = []
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for sid in ids:
        if path(sid).exists() and not force:
            continue
        sp, settings = settings_for(sid)
        channel = SimpleNamespace(key=GALLERY_CHANNEL, animation=settings,
                                  channel_display_name="", style_prompt="", topics=[],
                                  avoid_imagery=[])
        try:
            still = preview.still(channel, settings, subject=sp["subject"], hint=sp.get("hint", ""))
        except PipelineError as exc:
            log.warning(f"  [animation] no example for {sid}: {exc}")
            continue
        Image.open(still).convert("RGB").resize((540, 960), Image.LANCZOS).save(
            path(sid), quality=86, optimize=True, progressive=True)
        made.append(path(sid))
        log.info(f"  [animation] example for {sp['label']}")
    return made


def clear_cache() -> None:
    shutil.rmtree(preview.folder_for(GALLERY_CHANNEL), ignore_errors=True)
