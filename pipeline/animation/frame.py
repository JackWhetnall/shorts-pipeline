"""
The shape of the picture an animation is made for (decision 054): a
vertical short (1080x1920) or a widescreen long video (1920x1080).

A frame isn't part of a channel's style: the same style, kit and cast make
both, so one explanation can go out as a short and as a longer widescreen
video. What differs is here: the frame's size, where titles, content and
captions sit (the compositor's layouts arrange within `content`), the size
pictures are generated at, the aspect a video model is asked for, and
what the prompts say about composition.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Frame:
    key: str
    label: str
    w: int
    h: int
    aspect_ratio: str             # as video models take it
    image: tuple                  # a generated first frame, (w, h), multiples of 16
    rules: str                    # composition, for picture prompts
    # The compositor's geometry, in pixels: the title's line, the box that
    # content is arranged in (clear of the title and the captions), and
    # where a puppet's feet stand.
    title_y: int
    content: tuple                # (left, top, right, bottom)
    floor: int

    @property
    def vertical(self) -> bool:
        return self.h > self.w

    @property
    def cx(self) -> float:
        return (self.content[0] + self.content[2]) / 2

    @property
    def cy(self) -> float:
        return (self.content[1] + self.content[3]) / 2

    @property
    def cw(self) -> float:
        return self.content[2] - self.content[0]

    @property
    def ch(self) -> float:
        return self.content[3] - self.content[1]


NO_TEXT = ("Absolutely no text, letters, numbers, signs, captions, speech bubbles, logos or "
           "watermarks anywhere.")

VERTICAL = Frame(
    key="vertical", label="Vertical short (9:16)", w=1080, h=1920, aspect_ratio="9:16",
    image=(864, 1536),
    rules=("A vertical 9:16 frame. Keep the main subject in the upper two thirds; the bottom third "
           "stays simpler and quieter (captions are laid over it) but is still part of the "
           "picture. " + NO_TEXT),
    title_y=230, content=(40, 370, 1040, 1230), floor=1250)

WIDE = Frame(
    key="wide", label="Widescreen (16:9)", w=1920, h=1080, aspect_ratio="16:9",
    image=(1536, 864),
    rules=("A widescreen 16:9 frame, composed across its width with room to breathe; the bottom "
           "strip stays simpler (captions are laid over it) but is still part of the picture. "
           + NO_TEXT),
    title_y=118, content=(110, 205, 1810, 875), floor=905)

FRAMES = {f.key: f for f in (VERTICAL, WIDE)}


def get(key) -> Frame:
    """A frame by key (or a Frame, returned as it is); vertical by default."""
    if isinstance(key, Frame):
        return key
    return FRAMES.get(key or "vertical", VERTICAL)
