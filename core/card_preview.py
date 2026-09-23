"""
What a channel's title and outro cards will actually look like.

Same reasoning as `core.caption_preview`: a hex string and a slider don't
say whether a colour holds up against the channel's own background
picture (or the flat colour, if it has none), or how long text wraps.
This calls `pipeline.assemble.render_title_card` / `render_outro`
directly — the same functions a real render uses — so there is nothing
here that can drift from what a video actually shows.
"""

from __future__ import annotations

import io

from PIL import Image

from core.paths import FRAME_HEIGHT as H, FRAME_WIDTH as W

PREVIEW_WIDTH = 405  # matches core.caption_preview's own preview width

SAMPLE_TITLE = "Sample Subtopic Title Goes Here"
SAMPLE_TOPIC = "Sample Topic"
SAMPLE_OUTRO_SUBTEXT = "Subscribe for more"


def _encode(frame) -> bytes:
    height = int(H * PREVIEW_WIDTH / W)
    out = io.BytesIO()
    Image.fromarray(frame).convert("RGB").resize(
        (PREVIEW_WIDTH, height), Image.LANCZOS).save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_title_card(style, channel_display_name: str, channel_key: str = "",
                      show_topic: bool = False,
                      background_blur: int = None, background_dim: int = None) -> bytes:
    """Imports `pipeline.assemble` lazily — it pulls in moviepy, which the
    settings page shouldn't pay for just being opened.

    `background_blur`/`background_dim`, when given, override the
    channel's saved background edit for this one frame — so dragging
    those sliders shows what pressing their own Apply button would
    produce, before it has been pressed.
    """
    from pipeline import assemble

    frame = assemble.render_title_card(
        channel_display_name, SAMPLE_TITLE, style, channel_key,
        topic_title=SAMPLE_TOPIC if show_topic else "",
        background_blur=background_blur, background_dim=background_dim)
    return _encode(frame)


def render_outro(style, channel_display_name: str, outro_subtext: str,
                 channel_key: str = "",
                 background_blur: int = None, background_dim: int = None) -> bytes:
    from pipeline import assemble

    frame = assemble.render_outro(
        channel_display_name, outro_subtext or SAMPLE_OUTRO_SUBTEXT, style, channel_key,
        background_blur=background_blur, background_dim=background_dim)
    return _encode(frame)
