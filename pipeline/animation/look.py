"""
A channel's look for generated animation: a preset
(pipeline/animation/looks/*.json) plus the channel's own notes, palette
and sliders, resolved into what the picture and video models are told and
what the finish lays over the result.

A preset is an art direction, not a filter: the medium and how it's
rendered, its light, how its camera behaves, how things move in it, the
frame rate it's drawn at (stop-motion on threes, painted styles on
twos), and its grade and grain. Everything a model is told about style
comes from here, so every shot on a channel is described the same way.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

LOOKS_DIR = Path(__file__).resolve().parent / "looks"
DEFAULT_LOOK = "storybook_gouache"
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
CADENCE_FPS = {"ones": 24, "twos": 12, "threes": 8}
# Paper-based media keep their texture fixed to the page; filmed and
# rendered ones get grain that moves.
PAPER = {"storybook_gouache", "paper_cutout", "ink_watercolour", "risograph", "engraving"}

# Written for every frame, whatever the look: the captions sit in the
# bottom third, and image and video models can't be trusted with words.
FRAME_RULES = (
    "A vertical 9:16 frame. Keep the main subject in the upper two thirds; the bottom third "
    "stays simpler and quieter (captions are laid over it) but is still part of the picture. "
    "Absolutely no text, letters, numbers, signs, captions, speech bubbles, logos or "
    "watermarks anywhere.")

MOTION_RULES = (
    "Keep every character exactly on-model and the art style identical to the first frame "
    "from start to end: no morphing, no melting, no new people or objects appearing, no text. "
    "One clear action, readable at a glance.")


@lru_cache(maxsize=1)
def presets() -> dict:
    """Every look preset, in a stable order (by label)."""
    looks = {}
    for path in sorted(LOOKS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        looks[data["key"]] = data
    return dict(sorted(looks.items(), key=lambda kv: kv[1]["label"]))


def resolve(animation) -> dict:
    """The full look for a channel's animation settings (core.channels.
    Animation, or anything with the same attributes). Unknown values fall
    back to the preset's own, so a removed preset or a hand-edited file
    can't stop a render."""
    base = presets().get(getattr(animation, "look", "")) or presets()[DEFAULT_LOOK]
    look = copy.deepcopy(base)
    look["notes"] = " ".join(str(getattr(animation, "style_notes", "") or "").split())
    palette = [c for c in (getattr(animation, "palette", None) or []) if HEX_RE.match(str(c))]
    if palette:
        look["palette"] = palette
    cadence = getattr(animation, "cadence", "") or base.get("cadence", "twos")
    look["cadence"] = cadence if cadence in CADENCE_FPS else "twos"
    finish = max(0, min(100, int(getattr(animation, "finish", 100)))) / 100
    look["grade"] = _scaled(base.get("grade") or {}, finish)
    look["texture"] = "paper" if base["key"] in PAPER else "film"
    look["energy"] = max(0, min(100, int(getattr(animation, "energy", 50))))
    look["pace"] = max(0, min(100, int(getattr(animation, "pace", 50))))
    look["identity"] = identity(look)
    return look


def _scaled(grade: dict, strength: float) -> dict:
    """The grade at `strength`: 0 is neutral (no change), 1 the look's own."""
    neutral = {"contrast": 1.0, "saturation": 1.0, "warmth": 0.0, "grain": 0.0,
               "vignette": 0.0, "sharpen": 0.0}
    out = {}
    for name, zero in neutral.items():
        value = float(grade.get(name, zero))
        out[name] = round(zero + (value - zero) * strength, 4)
    # Upscaled frames always want a touch of sharpening, finish or not.
    out["sharpen"] = max(out["sharpen"], 0.15)
    return out


def identity(look: dict) -> str:
    """What a channel's style frames were drawn from. When it changes (a
    new preset, new notes, a new palette) the frames no longer show this
    look and are drawn again."""
    basis = json.dumps([look["key"], look["image"], look.get("notes", ""),
                        look.get("palette", [])], sort_keys=True)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def style_text(look: dict) -> str:
    """The style, as every picture prompt states it."""
    parts = [f"Art style: {look['image']}.", f"Light: {look['light']}."]
    if look.get("palette"):
        parts.append("Colour palette built from " + ", ".join(look["palette"]) + ".")
    if look.get("notes"):
        parts.append(f"Channel style notes: {look['notes']}.")
    parts.append(f"Never: {look['avoid']}.")
    return " ".join(parts)


def energy_text(energy: int) -> str:
    if energy < 34:
        return ("Calm and restrained: small, deliberate movements and a slow, smooth camera.")
    if energy < 67:
        return "Natural, purposeful movement and a steady, motivated camera move."
    return ("Lively and expressive: strong poses, clear anticipation and follow-through, "
            "a dynamic camera.")


def motion_text(look: dict) -> str:
    """The style of motion, as every video prompt states it."""
    return f"{look['motion']}. {energy_text(look['energy'])} {MOTION_RULES}"


def cadence_fps(look: dict) -> int:
    return CADENCE_FPS.get(look.get("cadence"), 12)
