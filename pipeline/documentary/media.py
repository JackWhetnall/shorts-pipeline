"""
A documentary scene's picture when it isn't drawn (decision 086): a real
painting of the period, or an animated card.

Paintings come from the museums' open collections (pipeline.artwork: the
Art Institute of Chicago and the Met, public domain), searched with the
script's `art_query` and chosen by a vision model for what's being said.
A painting is set into the widescreen frame over a blurred, darkened
copy of itself rather than cropped to a sliver, then treated like any
still: the camera moves across it and the editor cuts shots from it. One
that can't be found falls back to being drawn, so a scene is never empty.

A card's storyboard picture is a still of the card once it has built;
the video films the card itself (pipeline.documentary.cards).
"""

from __future__ import annotations

from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

FRAME = (1536, 864)             # a drawn still's size, so every picture is treated alike


def compose(image, size: tuple = FRAME):
    """A painting set into a widescreen frame: the work whole, over a
    blurred, darkened copy of itself."""
    from PIL import Image, ImageEnhance, ImageFilter
    w, h = size
    iw, ih = image.size
    cover = max(w / iw, h / ih) * 1.08
    back = image.resize((int(iw * cover), int(ih * cover)), Image.BICUBIC)
    left, top = (back.width - w) // 2, (back.height - h) // 2
    back = back.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(28))
    back = ImageEnhance.Brightness(back).enhance(0.42)
    fit = min((w * 0.92) / iw, (h * 0.9) / ih)
    fw, fh = int(iw * fit), int(ih * fit)
    work = image.resize((fw, fh), Image.LANCZOS)
    shadow = Image.new("RGBA", (fw + 40, fh + 40), (0, 0, 0, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(shadow).rectangle((20, 26, fw + 20, fh + 26), fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    frame = back.convert("RGBA")
    frame.alpha_composite(shadow, ((w - fw) // 2 - 20, (h - fh) // 2 - 20))
    frame.paste(work, ((w - fw) // 2, (h - fh) // 2))
    return frame.convert("RGB")


def painting(scene: dict, out: Path) -> str:
    """Find, choose and frame a painting for a scene. Returns its credit
    line; raises PipelineError when nothing fits (the scene is drawn)."""
    from pipeline import artwork
    query = scene.get("art_query") or ""
    candidates = artwork.search(query) if query else []
    work = artwork.pick(candidates, scene["narration"], wide=True) if candidates else None
    if work is None:
        raise PipelineError(f"no painting for {query!r}", user_message="No painting fitted this scene.")
    compose(artwork._download(work)).save(out, quality=92)
    return artwork.credit(work)


def card_still(channel, scene: dict, out: Path) -> Path:
    from pipeline.documentary import cards
    return cards.preview(scene["card"], cards.style_for(channel), out)


def make(channel, scenes: list, folder: Path, only: list = None) -> tuple:
    """({index: picture path}, {index: credit}, [indices to draw instead])
    for the scenes that aren't drawn: paintings and cards."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    made, credits, draw_instead = {}, {}, []
    for i, scene in enumerate(scenes):
        if only is not None and i not in only:
            continue
        medium = scene.get("medium", "picture")
        if medium == "painting":
            out = folder / f"art_{i:02d}.jpg"
            try:
                credits[i] = painting(scene, out)
                made[i] = out
            except PipelineError as exc:
                log.info(f"  [documentary] scene {i + 1}: {exc.user_message} Drawn instead.")
                draw_instead.append(i)
        elif medium == "card" and scene.get("card"):
            out = folder / f"card_{i:02d}.jpg"
            try:
                made[i] = card_still(channel, scene, out)
            except Exception as exc:  # noqa: BLE001 - a card that won't build is drawn instead
                log.warning(f"  [documentary] scene {i + 1}: card failed ({exc}); drawn instead")
                draw_instead.append(i)
    return made, credits, draw_instead
