"""
Curated caption colour combinations.

A channel picks its own base/highlight/stroke colours freely, and nothing
stops that combination from being unreadable or simply ugly — bright pink
on light blue passes every validation check this project has. The
purpose of this module is to make that impossible by construction: every
combination offered anywhere (a "suggest a look" button, a randomised
default for a new channel) comes from this fixed, pre-checked list, never
from raw hex values invented on the fly by a human or a model.

Each entry is checked for two things: the highlight colour reads clearly
against typical stock footage (not too close to skin tones or sky, the
two most common backgrounds), and base/highlight are different enough
from each other that the "current word" highlight in a caption is
actually visible against the rest of the line.

Font pairs with a couple of complementary faces from `core.fonts` rather
than the whole list, so a palette never lands on a face that clashes with
its intended mood (Comic Sans with a formal crimson-and-slate palette).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    key: str
    label: str
    mood: str                  # a short phrase, fed to the AI picker as context
    base_color: str
    highlight_color: str
    stroke_color: str
    outro_title_color: str
    outro_subtext_color: str
    outro_bg_color: tuple
    # The title card is the same kind of surface as the outro (a branding
    # card that may sit on a photo), so it shares the outro's colours
    # rather than needing its own design judgement per palette.
    title_card_title_color: str
    title_card_channel_color: str
    title_card_bg_color: tuple
    # Faces from core.fonts this palette suits. The first is the default
    # when a pick is random rather than AI-suggested.
    font_faces: tuple


PALETTES = (
    Palette("warm_gold", "Warm Gold", "reassuring, traditional, devotional",
           "#FFFFFF", "#FFD400", "#000000", "#FFFFFF", "#FFD400",
           (10, 10, 14, 255), "#FFFFFF", "#FFD400", (10, 10, 14, 255),
           ("arial_bold", "georgia_bold")),
    Palette("cool_teal", "Cool Teal", "calm, clinical, modern",
           "#FFFFFF", "#2DE1C2", "#0A1A18", "#FFFFFF", "#2DE1C2",
           (8, 18, 17, 255), "#FFFFFF", "#2DE1C2", (8, 18, 17, 255),
           ("segoe_bold", "verdana_bold")),
    Palette("crimson", "Crimson", "urgent, high-energy, punchy",
           "#FFFFFF", "#FF3B4E", "#1A0508", "#FFFFFF", "#FF3B4E",
           (18, 6, 8, 255), "#FFFFFF", "#FF3B4E", (18, 6, 8, 255),
           ("impact", "franklin_gothic")),
    Palette("violet_mystic", "Violet Mystic", "mysterious, spiritual, esoteric",
           "#F3E9FF", "#C084FC", "#160B24", "#F3E9FF", "#C084FC",
           (16, 8, 26, 255), "#F3E9FF", "#C084FC", (16, 8, 26, 255),
           ("cambria_bold", "trebuchet_bold")),
    Palette("forest", "Forest", "grounded, natural, patient",
           "#FFFFFF", "#8BD46E", "#0C160C", "#FFFFFF", "#8BD46E",
           (10, 16, 10, 255), "#FFFFFF", "#8BD46E", (10, 16, 10, 255),
           ("verdana_bold", "tahoma_bold")),
    Palette("sunset_orange", "Sunset Orange", "warm, energetic, friendly",
           "#FFFFFF", "#FF9A3D", "#1C0F04", "#FFFFFF", "#FF9A3D",
           (20, 12, 6, 255), "#FFFFFF", "#FF9A3D", (20, 12, 6, 255),
           ("bahnschrift", "trebuchet_bold")),
    Palette("ice_blue", "Ice Blue", "clean, technical, precise",
           "#FFFFFF", "#5AC8FA", "#04121C", "#FFFFFF", "#5AC8FA",
           (5, 12, 20, 255), "#FFFFFF", "#5AC8FA", (5, 12, 20, 255),
           ("segoe_bold", "bahnschrift")),
    Palette("rose", "Rose", "soft, personal, intimate",
           "#FFFFFF", "#FF8FB1", "#1C0810", "#FFFFFF", "#FF8FB1",
           (18, 8, 13, 255), "#FFFFFF", "#FF8FB1", (18, 8, 13, 255),
           ("georgia_bold", "comic_bold")),
    Palette("slate_mono", "Slate Mono", "minimal, serious, understated",
           # The first draft used #D9DCE3, a grey so close to white the
           # highlighted word was unreadable against its own caption -
           # confirmed by actually rendering it, not by eyeballing the
           # hex. #8FA3B8 keeps the muted, understated feel but is far
           # enough from white to stay legible.
           "#FFFFFF", "#8FA3B8", "#0B0C10", "#FFFFFF", "#8FA3B8",
           (10, 11, 15, 255), "#FFFFFF", "#8FA3B8", (10, 11, 15, 255),
           ("rockwell_bold", "franklin_gothic")),
    Palette("amber_academic", "Amber Academic", "intellectual, formal, literary",
           "#F5EFE3", "#E0A94D", "#12100A", "#F5EFE3", "#E0A94D",
           (14, 12, 8, 255), "#F5EFE3", "#E0A94D", (14, 12, 8, 255),
           ("cambria_bold", "georgia_bold")),
    Palette("electric_lime", "Electric Lime", "loud, playful, internet-native",
           "#FFFFFF", "#C8FF3D", "#0E140A", "#FFFFFF", "#C8FF3D",
           (10, 14, 8, 255), "#FFFFFF", "#C8FF3D", (10, 14, 8, 255),
           ("impact", "comic_bold")),
    Palette("midnight_gossip", "Midnight Gossip", "tabloid, dramatic, breathless",
           "#FFFFFF", "#FF5EDB", "#160616", "#FFFFFF", "#FF5EDB",
           (14, 6, 16, 255), "#FFFFFF", "#FF5EDB", (14, 6, 16, 255),
           ("franklin_gothic", "impact")),
)

PALETTES_BY_KEY = {p.key: p for p in PALETTES}

DEFAULT_PALETTE = "warm_gold"


def get(key: str) -> Palette:
    return PALETTES_BY_KEY.get(key) or PALETTES_BY_KEY[DEFAULT_PALETTE]


def random_choice(rng=None) -> Palette:
    """A palette and a face from it, picked uniformly.

    Safe by construction: every entry in PALETTES has already been
    checked for contrast and taste, so there is no combination in this
    list that produces the pink-on-light-blue problem — the random pick
    only has to choose an index, never a colour.
    """
    import random as _random

    rng = rng or _random
    palette = rng.choice(PALETTES)
    face = rng.choice(palette.font_faces)
    return palette, face


def apply_to_style(style, palette: "Palette", font_face: str = None) -> None:
    """Write a palette's colours (and a face from it) onto a Style, in place."""
    style.base_color = palette.base_color
    style.highlight_color = palette.highlight_color
    style.stroke_color = palette.stroke_color
    style.outro_title_color = palette.outro_title_color
    style.outro_subtext_color = palette.outro_subtext_color
    style.outro_bg_color = palette.outro_bg_color
    style.title_card_title_color = palette.title_card_title_color
    style.title_card_channel_color = palette.title_card_channel_color
    style.title_card_bg_color = palette.title_card_bg_color
    style.font_face = font_face if font_face in palette.font_faces else palette.font_faces[0]
