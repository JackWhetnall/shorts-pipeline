"""
A compiled style (pipeline.animation.style) as the compositor's theme:
label face and colours, shadows, the drawing rate and its handmade boil,
and the canvas.

Colours come from the style's palette by role: the ink is its darkest
colour, the paper its lightest, the accent its most vivid middle tone. On
a dark surface (a chalkboard, a blueprint, neon) ink and paper swap, so
labels are always legible.
"""

from __future__ import annotations

STEPS = {"ones": 0.0, "twos": 1 / 12, "threes": 1 / 8}


def _luma(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _saturation(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hi, lo = max(r, g, b), min(r, g, b)
    return 0.0 if hi == 0 else (hi - lo) / hi


def rgb(hex_colour: str) -> str:
    return ",".join(str(int(hex_colour[i:i + 2], 16)) for i in (1, 3, 5))


def inks(look: dict) -> dict:
    """The palette as roles: ink (the darkest), paper (the lightest),
    accent (the most vivid of the middle tones)."""
    palette = [c for c in look.get("palette") or [] if isinstance(c, str) and len(c) == 7]
    if not palette:
        palette = ["#2B2A33", "#E4572E", "#F6F1E7"]
    by_luma = sorted(palette, key=_luma)
    middle = [c for c in palette if 0.18 < _luma(c) < 0.85] or palette
    accent = max(middle, key=lambda c: (_saturation(c), -abs(_luma(c) - 0.5)))
    ink = by_luma[0] if _luma(by_luma[0]) < 0.3 else "#2B2A33"
    paper = by_luma[-1] if _luma(by_luma[-1]) > 0.7 else "#F6F1E7"
    return {"ink": ink, "paper": paper, "accent": accent}


def dark(fmt: dict, look: dict) -> bool:
    canvas = look.get("canvas")
    return bool(fmt.get("dark_surface")) or bool(canvas and _luma(canvas) < 0.3)


def series(look: dict, background: str, text: str) -> list:
    """The palette's colours that read against the background, in the
    palette's own order (a style puts its lead colour first), for a
    diagram's bars, curves and points (not the text colour)."""
    bg = _luma(background) if isinstance(background, str) and len(background) == 7 else 0.9
    out = []
    for c in look.get("palette") or []:
        if not (isinstance(c, str) and len(c) == 7) or c.lower() == text.lower():
            continue
        if abs(_luma(c) - bg) < 0.28 or _saturation(c) < 0.25:
            continue
        out.append(c)
    return out[:6]


def theme(fmt: dict, look: dict) -> dict:
    colours = inks(look)
    on_dark = dark(fmt, look)
    step = STEPS.get(look.get("cadence"), 1 / 12)
    labels = {"font": "Segoe UI Black", "weight": 900, "size": 58, "title_size": 72,
              "line": 7, **(fmt.get("labels") or {})}
    text = colours["paper"] if on_dark and not labels.get("tag") else colours["ink"]
    labels.update({"color": text, "accent": colours["accent"], "stepped": step > 0,
                   "badge_text": colours["paper"] if not on_dark else colours["ink"],
                   "tag_text": labels.get("tag_text") or colours["ink"]})
    shadow = dict(fmt.get("shadow") or {"mode": "none"})
    shadow.setdefault("rgb", "60,45,30" if not on_dark else "0,0,0")
    jitter = look.get("jitter")
    if jitter is None:
        jitter = 1.3 if step > 0 and fmt.get("continuity") in ("move", "scene") else 0.0
    background = look.get("canvas") or colours["paper"]
    # Diagrams: lines and words in the label ink, data in the palette's
    # colours that read on this background; typeset words keep maths and
    # words in one face.
    typeset = labels.get("font") == TYPESET_FACE
    colours_on = series(look, background, text) or [colours["accent"]]
    diagram = {"ink": text, "accent": colours_on[0], "series": colours_on,
               "line": max(3.0, labels["line"] * 0.7), "math_face": typeset,
               "hand": labels["font"] if labels.get("rough") else ""}
    return {"labels": labels, "shadow": shadow, "surface": {"color": background},
            "step": step, "jitter": float(jitter), "idle": "none",
            "depth_sort": fmt.get("view") == "angle", "diagram": diagram}


TYPESET_FACE = "Computer Modern"
