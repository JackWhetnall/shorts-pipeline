"""
What a channel's captions will actually look like.

The Look settings were six hex strings and a number in text boxes. You
could tell `#FFD400` was yellow-ish, but not whether a 4px stroke held up
against bright footage, whether 68px wrapped a four-word group onto two
lines, or what Bahnschrift did to a long word. The only way to find out
was to spend a script, a voiceover and a render.

So this renders one frame the way `pipeline.assemble` renders every frame
— the same `layout_caption` and `render_word_overlay`, the same
`group_words` chunking, the same font resolution — over a real frame from
the footage library. Not a mock-up of the caption: the caption.

It has to live in `core` rather than a web helper because `pipeline` must
not import Flask and `web` must not reach past `core` into rendering
internals.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image

from core.logging_setup import get_logger
from core.paths import CACHE_DIR, FRAME_HEIGHT as H, FRAME_WIDTH as W

# Duplicated from pipeline.assemble rather than imported: importing it at
# module scope would pull moviepy into every process that touches this.
CAPTION_Y = int(H * 0.72)

log = get_logger(__name__)

# Wide enough to wrap at the default size, and with one long word, since
# wrapping and a long word are the two things a preview needs to expose.
SAMPLE_TEXT = "Every ordinary moment carries something worth noticing"
# Which word is lit. Third: far enough in to sit mid-line.
HIGHLIGHT_INDEX = 2

PREVIEW_WIDTH = 405                     # 1080 / 2.667; retina-sharp at ~270 CSS px
BACKDROP_PATH = CACHE_DIR / "caption_preview_backdrop.jpg"

# How many library clips to consider for the backdrop. The brightest one
# behind the caption band is chosen, because bright footage is the case
# white captions fail on — a preview over a dark clip would tell you
# every colour works.
BACKDROP_CANDIDATES = 12


def _backdrop() -> Image.Image:
    """A real library frame if there is one, otherwise a plain gradient.

    A flat grey would make any colour look legible. Real footage is what
    the captions have to survive, so the preview is worth much less
    without it. Cached to one file: picking and decoding a frame per
    keystroke would make the live preview feel broken.
    """
    if BACKDROP_PATH.exists():
        try:
            return Image.open(BACKDROP_PATH).convert("RGB").resize((W, H))
        except OSError:
            BACKDROP_PATH.unlink(missing_ok=True)

    try:
        from core import footage_stats
        from pipeline.footage import store

        clips = store.all_clips()
        if clips:
            # Deterministic sample, then the brightest of it. Deterministic
            # because a backdrop that changed between two keystrokes would
            # make it impossible to compare two colour choices; brightest
            # because that is the frame a caption has to survive.
            sample = random.Random(0).sample(
                clips, min(BACKDROP_CANDIDATES, len(clips)))
            best, best_brightness = None, -1.0
            for clip in sample:
                try:
                    frame = Image.open(
                        footage_stats.clip_thumbnail(clip.filename)).convert("RGB")
                except Exception:          # noqa: BLE001 - try the next clip
                    continue
                brightness = _caption_band_brightness(frame)
                if brightness > best_brightness:
                    best, best_brightness = frame, brightness
            if best is not None:
                image = best.resize((W, H))
                BACKDROP_PATH.parent.mkdir(parents=True, exist_ok=True)
                image.save(BACKDROP_PATH, quality=85)
                return image
    except Exception as exc:               # noqa: BLE001 - preview is cosmetic
        log.debug("No library frame for the caption preview: %s", exc)

    return _gradient()


def _caption_band_brightness(frame: Image.Image) -> float:
    """Mean luminance of the strip the captions sit in.

    The whole-frame average is the wrong measure: a clip can be bright at
    the top and black where the text goes.
    """
    top = int(frame.height * (CAPTION_Y / H))
    band = frame.crop((0, top, frame.width, frame.height)).convert("L")
    return sum(band.getdata()) / max(1, band.width * band.height)


def _gradient() -> Image.Image:
    """The fallback backdrop: dark at the top, mid-grey at the bottom.

    Mid-grey behind the caption band specifically, because that is the
    tone a white caption and a black stroke both have to fight.
    """
    image = Image.new("RGB", (W, H))
    pixels = image.load()
    for y in range(H):
        value = int(18 + (y / H) * 120)
        for x in range(W):
            pixels[x, y] = (value, value, int(value * 1.05))
    return image


def clear_backdrop_cache() -> None:
    BACKDROP_PATH.unlink(missing_ok=True)


def render(style, pacing, text: str = SAMPLE_TEXT) -> bytes:
    """One PNG frame: sample narration captioned with `style`.

    Imports `pipeline.assemble` lazily. It pulls in moviepy, which costs
    around a second on first import, and the settings page should not pay
    that just for being opened.
    """
    from pipeline import assemble
    from pipeline.plan import WordTiming

    words = text.split()
    # Fabricated timings at a plausible speaking rate, purely so
    # group_words chunks the sample the way it would chunk real narration.
    timings = [WordTiming(word=w, start=i * 0.42, end=i * 0.42 + 0.36)
               for i, w in enumerate(words)]
    groups = assemble.group_words(timings, pacing)
    group = groups[0] if groups else timings

    frame = _backdrop().convert("RGBA")
    layout = assemble.layout_caption([w.word for w in group], style)
    caption = Image.fromarray(layout.image)

    index = min(HIGHLIGHT_INDEX, len(group) - 1)
    if index >= 0 and index < len(layout.boxes):
        overlay = Image.fromarray(
            assemble.render_word_overlay(group[index].word, layout.boxes[index], style))
        x, y, _, _ = layout.boxes[index]
        caption.alpha_composite(overlay, (max(0, int(x) - style.stroke_width - 2),
                                          max(0, int(y) - style.stroke_width)))

    frame.alpha_composite(caption, (assemble.CAPTION_LEFT, assemble.CAPTION_Y))

    height = int(H * PREVIEW_WIDTH / W)
    out = io.BytesIO()
    frame.convert("RGB").resize((PREVIEW_WIDTH, height), Image.LANCZOS).save(
        out, format="PNG", optimize=True)
    return out.getvalue()
