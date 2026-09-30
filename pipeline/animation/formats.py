"""
Formats: what kind of animated video a channel makes, separate from how
it looks (decision 052).

A look is a medium: felt, gouache, engraving. A format is a grammar: what
persists through the video, what is drawn once for the channel, how the
storyboard thinks, and what renders it.

- **story** and **theatre** are generated: shots drawn and animated by a
  video model (pipeline.animation.stage), theatre with a stage grammar and
  captions of its own.
- **tabletop** and **canvas** are composited: a kit of objects (and a
  narrator) drawn once in the look, arranged by designed layouts, moved
  with real motion design and labelled exactly (pipeline.animation.compose).

Any look can be used with any format; each format names the looks that
suit it best, and the settings page offers those first.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

FORMATS_DIR = Path(__file__).resolve().parent / "formats"
DEFAULT_FORMAT = "story"
STEPS = {"ones": 0.0, "twos": 1 / 12, "threes": 1 / 8}


@lru_cache(maxsize=1)
def formats() -> dict:
    out = {}
    for path in FORMATS_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[data["key"]] = data
    return dict(sorted(out.items(), key=lambda kv: kv[1].get("order", 9)))


def resolve(key: str) -> dict:
    return formats().get(key) or formats()[DEFAULT_FORMAT]


def composited(fmt: dict) -> bool:
    return fmt.get("engine") == "compositor"


def _luma(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _saturation(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hi, lo = max(r, g, b), min(r, g, b)
    return 0.0 if hi == 0 else (hi - lo) / hi


def _rgb(hex_colour: str) -> str:
    return ",".join(str(int(hex_colour[i:i + 2], 16)) for i in (1, 3, 5))


def inks(look: dict) -> dict:
    """The look's palette as roles: ink (the darkest), paper (the
    lightest), accent (the most vivid of the middle tones)."""
    palette = [c for c in look.get("palette") or [] if isinstance(c, str) and len(c) == 7]
    if not palette:
        palette = ["#2B2A33", "#E4572E", "#F6F1E7"]
    by_luma = sorted(palette, key=_luma)
    middle = [c for c in palette if 0.18 < _luma(c) < 0.85] or palette
    accent = max(middle, key=lambda c: (_saturation(c), -abs(_luma(c) - 0.5)))
    ink = by_luma[0] if _luma(by_luma[0]) < 0.3 else "#2B2A33"
    return {"ink": ink, "paper": by_luma[-1], "accent": accent}


def style_for(fmt: dict, look: dict) -> dict:
    """What the compositor needs from a format and a look: labels, shadow,
    surface, and the look's drawing rate and handmade boil."""
    colours = inks(look)
    step = STEPS.get(look.get("cadence"), 1 / 12)
    labels = dict(fmt.get("labels") or {})
    labels.update({"color": colours["ink"], "accent": colours["accent"],
                   "stepped": step > 0, "badge_text": "#FFFFFF"})
    shadow = dict(fmt.get("shadow") or {"mode": "none"})
    shadow.setdefault("rgb", _rgb(colours["ink"]) if shadow.get("mode") != "contact" else "60,45,30")
    handmade = step > 0
    surface = {"color": look.get("canvas") or colours["paper"]}
    return {"labels": labels, "shadow": shadow, "surface": surface, "step": step,
            "jitter": 1.3 if handmade and fmt.get("continuity") == "move" else 0.0,
            "idle": "none"}
