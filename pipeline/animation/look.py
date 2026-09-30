"""
How a compiled style (pipeline.animation.style) is put into words for
the picture and video models, and the frame rate it's drawn at.

A look is the drawing half of a compiled style: its medium, light,
palette, people, motion and grade. Everything a model is told about
style comes from here, so every picture on a channel is described the
same way.
"""

from __future__ import annotations

import re

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
CADENCE_FPS = {"ones": 24, "twos": 12, "threes": 8}

# Written for every frame, whatever the style: the captions sit in the
# bottom third, and image and video models can't be trusted with words.
FRAME_RULES = (
    "A vertical 9:16 frame. Keep the main subject in the upper two thirds; the bottom third "
    "stays simpler and quieter (captions are laid over it) but is still part of the picture. "
    "Absolutely no text, letters, numbers, signs, captions, speech bubbles, logos or "
    "watermarks anywhere.")

def frame_rules(look: dict) -> str:
    """Composition and no-text rules for the frame the look is being made
    for (a vertical short by default)."""
    from pipeline.animation import frame as frames
    return frames.get(look.get("frame")).rules


MOTION_RULES = (
    "Keep every character exactly on-model and the art style identical to the first frame "
    "from start to end: no morphing, no melting, no new people or objects appearing, no text. "
    "One clear action, readable at a glance.")


def scaled_grade(grade: dict, strength: float) -> dict:
    """The grade at `strength`: 0 is neutral (no change), 1 the style's own."""
    neutral = {"contrast": 1.0, "saturation": 1.0, "warmth": 0.0, "grain": 0.0,
               "vignette": 0.0, "sharpen": 0.0}
    out = {}
    for name, zero in neutral.items():
        value = float(grade.get(name, zero))
        out[name] = round(zero + (value - zero) * strength, 4)
    # Upscaled frames always want a touch of sharpening, finish or not.
    out["sharpen"] = max(out["sharpen"], 0.15)
    return out


def style_text(look: dict) -> str:
    """The style, as every picture prompt states it."""
    parts = [f"Art style: {look['image']}."]
    if look.get("light"):
        parts.append(f"Light: {look['light']}.")
    if look.get("people"):
        parts.append(f"Characters: {look['people']}.")
    if look.get("palette"):
        parts.append("Colour palette built from " + ", ".join(look["palette"]) + ".")
    if look.get("notes"):
        parts.append(f"Channel style notes: {look['notes']}.")
    if look.get("avoid"):
        parts.append(f"Never: {look['avoid']}.")
    return " ".join(parts)


def energy_text(energy: int) -> str:
    if energy < 34:
        return "Calm and restrained: small, deliberate movements and a slow, smooth camera."
    if energy < 67:
        return "Natural, purposeful movement and a steady, motivated camera move."
    return ("Lively and expressive: strong poses, clear anticipation and follow-through, "
            "a dynamic camera.")


def motion_text(look: dict) -> str:
    """The style of motion, as every video prompt states it."""
    return f"{look['motion']}. {energy_text(look.get('energy', 50))} {MOTION_RULES}"


def cadence_fps(look: dict) -> int:
    return CADENCE_FPS.get(look.get("cadence"), 12)
