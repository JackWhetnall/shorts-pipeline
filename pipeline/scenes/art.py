"""
A channel's art direction: which preset it starts from, and what it
changes.

A channel stores only `{"preset": "chalkboard", ...overrides}`; the full
art direction is the preset with the overrides laid over it. So a preset
improved later improves every channel built on it, while a channel's own
choices (its colours, its fonts, how its props are drawn) stay its own.

Everything a person or the channel draft can set is checked here: colours
must be colours, fonts must be installed ones, numbers stay in range. A
wrong value falls back to the preset's rather than breaking a render.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger(__name__)

STYLES_DIR = Path(__file__).parent / "styles"
DEFAULT_PRESET = "clean_flat"

# Installed on Windows, so a scene renders the same on any Windows PC
# without shipping font files. The descriptions are what the channel
# draft chooses from. Every one must stay readable as a small label, a
# number and an equation, because the heading font sets all three:
# decorative scripts (Segoe Script, Gabriola) were left out for that.
FONTS = {
    "Bahnschrift": "clean geometric sans, modern and technical",
    "Segoe UI": "neutral humanist sans, very readable",
    "Segoe UI Black": "heavy rounded sans, loud and friendly",
    "Candara": "soft humanist sans, gentle and warm",
    "Corbel": "light clean sans, calm",
    "Georgia": "classic newspaper serif, trustworthy",
    "Constantia": "warm book serif",
    "Palatino Linotype": "old-style book serif, literary and historic",
    "Cambria": "sturdy modern serif, academic",
    "Segoe Print": "neat handwriting, like a teacher's",
    "Ink Free": "casual marker handwriting",
    "Arial Black": "heavy poster sans",
    "Impact": "condensed poster headline",
    "Comic Sans MS": "playful, childlike",
    "Consolas": "monospace, code and data",
}
PATTERNS = ("none", "dots", "grid", "lines")
COLOR_KEYS = ("ink", "ink_soft", "label_fill", "accent1", "accent2", "accent3", "accent4", "accent5")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
PROP_STYLE_MAX = 500


def presets() -> dict:
    """{key: art direction} for every preset, in a stable order."""
    out = {}
    for path in sorted(STYLES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[data["key"]] = data
    return dict(sorted(out.items(), key=lambda kv: kv[0] != DEFAULT_PRESET))


def resolve(settings: dict) -> dict:
    """The full art direction for a channel's stored settings."""
    settings = clean(settings or {})
    style = copy.deepcopy(presets()[settings["preset"]])
    for key in COLOR_KEYS:
        if key in settings:
            style["colors"][key] = settings[key]
    if "ink" in settings:
        style["ink"] = settings["ink"]
    if "background" in settings:
        style["background"]["color"] = settings["background"]
    if "pattern" in settings:
        style["background"]["pattern"] = settings["pattern"]
    if "pattern_color" in settings:
        style["background"]["pattern_color"] = settings["pattern_color"]
    for key in ("font_display", "font_text", "stroke_width", "prop_style"):
        if key in settings:
            style[key] = settings[key]
    return style


def clean(raw: dict) -> dict:
    """Keep only valid settings. Always carries a real preset."""
    raw = raw or {}
    out = {"preset": raw.get("preset") if raw.get("preset") in presets() else DEFAULT_PRESET}
    for key in (*COLOR_KEYS, "background", "pattern_color"):
        value = str(raw.get(key) or "").strip()
        if HEX_RE.match(value):
            out[key] = value.upper()
    if raw.get("pattern") in PATTERNS:
        out["pattern"] = raw["pattern"]
    for key in ("font_display", "font_text"):
        if raw.get(key) in FONTS:
            out[key] = raw[key]
    try:
        if raw.get("stroke_width") not in (None, ""):
            out["stroke_width"] = int(min(20, max(3, float(raw["stroke_width"]))))
    except (TypeError, ValueError):
        pass
    prop_style = " ".join(str(raw.get("prop_style") or "").split())[:PROP_STYLE_MAX]
    if prop_style:
        out["prop_style"] = prop_style
    return out


def sparse(settings: dict) -> dict:
    """Only what differs from the preset. A form sends every field; kept
    whole, a channel would stop inheriting improvements to its preset."""
    settings = clean(settings)
    base = editable({"preset": settings["preset"]})
    return {k: v for k, v in settings.items()
            if k == "preset" or str(v).upper() != str(base.get(k)).upper()}


def editable(settings: dict) -> dict:
    """Every editable value, filled in from the preset: what a settings
    form shows."""
    style = resolve(settings)
    return {
        "preset": clean(settings)["preset"],
        "background": style["background"]["color"],
        "pattern": style["background"].get("pattern") or "none",
        "pattern_color": style["background"].get("pattern_color") or "#000000",
        **{key: style["colors"][key] for key in COLOR_KEYS},
        "font_display": style["font_display"],
        "font_text": style["font_text"],
        "stroke_width": style["stroke_width"],
        "prop_style": style["prop_style"],
    }


# --- preview ---------------------------------------------------------------

# A scene that shows everything a style touches (title type, a shape
# being drawn, labels with each accent, a number, a chart) with no
# illustrated props, so a preview never costs an image.
PREVIEW_SCENE = {
    "duration": 3.0,
    "elements": [
        {"id": "title", "type": "label", "text": "How it adds up", "style": "title",
         "pill": False, "size": 86, "x": 540, "y": 170},
        {"id": "tri", "type": "shape", "kind": "poly", "vertices": [[430, 800], [800, 800], [430, 520]],
         "stroke": "ink", "fill": "accent2", "fill_opacity": 0.35},
        {"id": "sq", "type": "shape", "kind": "square", "on": {"of": "tri", "edge": 2},
         "stroke": "accent1", "fill": "accent1", "fill_opacity": 0.25},
        {"id": "mark", "type": "shape", "kind": "angle", "at": {"of": "tri", "vertex": 0}, "width": 6},
        {"id": "a", "type": "label", "text": "a", "dot": "accent1", "size": 56,
         "anchor": {"of": "sq", "offset": 0}},
        {"id": "b", "type": "label", "text": "b", "dot": "accent3", "size": 56,
         "anchor": {"of": "tri", "edge": 0, "offset": 70}},
        {"id": "eq", "type": "label", "style": "title", "pill": False, "size": 84, "x": 540, "y": 340,
         "parts": [{"text": "a² ", "color": "accent1"}, {"text": "+ "},
                   {"text": "b²", "color": "accent3"}]},
        {"id": "count", "type": "counter", "from": 0, "suffix": "%", "size": 96, "x": 300, "y": 1120},
        {"id": "bars", "type": "chart", "kind": "bar", "x": 720, "y": 1110, "w": 380, "h": 190,
         "values": [2, 4, 7, 11], "fill": "accent4"},
    ],
    "actions": [
        {"target": "title", "do": "write", "at": 0.0, "dur": 0.3},
        {"target": "tri", "do": "draw", "at": 0.0, "dur": 0.6},
        {"target": "sq", "do": "draw", "at": 0.2, "dur": 0.6},
        {"target": "count", "do": "count", "to": 75, "at": 0.0, "dur": 0.5},
        {"target": "bars", "do": "draw", "at": 0.0, "dur": 0.6},
    ],
}


def preview(settings: dict, cache_dir: Path) -> Path:
    """A still of the preview scene in this art direction, cached by
    content so an unchanged style is never re-rendered."""
    from pipeline.scenes import render

    style = resolve(settings)
    digest = hashlib.sha1(json.dumps([style, PREVIEW_SCENE, render.RUNTIME.stat().st_mtime],
                                     sort_keys=True).encode()).hexdigest()[:16]
    out = Path(cache_dir) / f"{digest}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        render.render_frame(PREVIEW_SCENE, style, {}, PREVIEW_SCENE["duration"], out)
    return out
