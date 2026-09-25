"""
A filled template as one self-contained page, ready to film.

Theme (the channel's look) + background + the template's composition +
the timing engine. Icons come from the free libraries only
(pipeline.scenes.iconlib), tinted for line looks and kept in the
channel's prop folder; a template never pays to draw an icon, and a name
the libraries don't have becomes a lettered badge instead.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from core.logging_setup import get_logger
from pipeline.templates import library, theme

log = get_logger(__name__)

RUNTIME = Path(__file__).parent / "runtime.js"
GRAIN = ("data:image/svg+xml;base64," + base64.b64encode(
    b"<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'>"
    b"<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' seed='7'/>"
    b"</filter><rect width='300' height='300' filter='url(#n)'/></svg>").decode("ascii"))
FILTERS = """<svg width="0" height="0" style="position:absolute"><filter id="sketch" x="-5%" y="-5%"
  width="110%" height="110%"><feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2"
  seed="3" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale="5" xChannelSelector="R"
  yChannelSelector="G"/></filter></svg>"""


def icon_resolver(style: dict, folder: Path):
    """name -> data URI of that icon in this look, or "" if no free library
    has it. Cached in the channel's prop folder like any prop."""
    from pipeline.scenes import iconlib, props
    from pipeline.scenes.stage import _icons

    icons = _icons(style)
    sets = iconlib.sets_of(icons)
    memo = {}

    def resolve(name: str) -> str:
        name = (name or "").strip()
        if not name:
            return ""
        if name not in memo:
            path = Path(folder) / f"{props.slug(name)}.png"
            if not path.exists() and sets:
                iconlib.get(Path(folder), name, path, sets, icons.get("tint", ""))
            memo[name] = ("data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
                          if path.exists() else "")
        return memo[name]

    return resolve


def build(name: str, slots: dict, times: dict, style: dict, duration: float, icons) -> str:
    spec = library.TEMPLATES[name]
    stage = spec["build"](slots, times, icons)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"{theme.css(style)}"
        f".bg-grain {{ background-image: url({GRAIN}); }}"
        "</style></head><body>"
        f"{FILTERS}"
        "<div class='bg'><div class='bg-pattern'></div><div class='bg-grain'></div>"
        "<div class='bg-vignette'></div></div>"
        f"<div class='stage'>{stage}</div>"
        f"<script>window.TEMPLATE_DURATION = {json.dumps(duration)};</script>"
        f"<script>{RUNTIME.read_text(encoding='utf-8')}</script>"
        "</body></html>"
    )
