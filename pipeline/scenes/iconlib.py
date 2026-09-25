"""
Free, openly licensed illustrations for scene props, tried before any
image is generated.

Openly licensed sets through the Iconify API, tried in the order an art
direction lists them. Microsoft's Fluent Emoji (MIT: about 1,500
everyday objects and people, in a colour set and a line set) come first;
Google's Noto emoji (Apache 2.0) back up the colour looks, and Tabler,
Phosphor (MIT) and Lucide (ISC) back up the line looks with diagram
icons: gears, bulbs, scales, hourglasses. Line sets are recoloured in the
channel's ink, so a chalk or ink channel's props look drawn in the same
hand as everything else. A prop is fetched once
per channel and look, and kept in its prop library like a generated one,
with a note of where it came from and its licence. Nothing is sent but
the object's name.

When nothing in the set matches the object closely (by its name, or by
its last word: "wooden ladder" finds "ladder"), the caller generates one
instead. See decision 036.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from core.logging_setup import get_logger

log = get_logger(__name__)

API = "https://api.iconify.design"
TIMEOUT = 20
SIZE = 640

# What the library says about each set, recorded beside every prop.
LICENCES = {
    "fluent-emoji-flat": ("MIT", "https://github.com/microsoft/fluentui-emoji/blob/main/LICENSE"),
    "fluent-emoji-high-contrast": ("MIT",
                                   "https://github.com/microsoft/fluentui-emoji/blob/main/LICENSE"),
    "noto": ("Apache-2.0", "https://github.com/googlefonts/noto-emoji/blob/main/svg/LICENSE"),
    "tabler": ("MIT", "https://github.com/tabler/tabler-icons/blob/master/LICENSE"),
    "ph": ("MIT", "https://github.com/phosphor-icons/core/blob/main/LICENSE"),
    "lucide": ("ISC", "https://github.com/lucide-icons/lucide/blob/main/LICENSE"),
}
# Thin-line sets whose bold weight reads better at video size.
BOLD_VARIANT = {"ph": "-bold"}


def sets_of(icons: dict) -> list:
    """The sets an art direction's prop library lists, in order."""
    icons = icons or {}
    found = list(icons.get("sets") or []) or ([icons["set"]] if icons.get("set") else [])
    return [s for s in found if s in LICENCES]


def candidates(name: str) -> list:
    """Icon names to try, most specific first: "wooden ladder" ->
    ["wooden-ladder", "ladder", "wooden"]."""
    words = [w for w in re.findall(r"[a-z]+", (name or "").lower()) if len(w) > 2]
    out = ["-".join(words)] if len(words) > 1 else []
    out += list(reversed(words))
    return list(dict.fromkeys(out))


def find(name: str, icon_set: str) -> str:
    """The icon in `icon_set` that is this object, or "" if none is."""
    for query in candidates(name):
        try:
            response = requests.get(f"{API}/search", timeout=TIMEOUT,
                                    params={"query": query, "prefix": icon_set, "limit": 64})
            icons = response.json().get("icons", []) if response.status_code == 200 else []
        except (requests.RequestException, ValueError) as exc:
            log.info(f"  [scene] icon library unreachable ({exc}); generating instead")
            return ""
        # Exact names only: "wall" must not become "wall-clock".
        names = {icon.split(":", 1)[1]: icon for icon in icons}
        for wanted in (query + BOLD_VARIANT.get(icon_set, ""), query):
            if wanted in names:
                return names[wanted]
    return ""


def fetch_svg(icon: str, tint: str = "") -> str:
    prefix, slug = icon.split(":", 1)
    response = requests.get(f"{API}/{prefix}/{slug}.svg", timeout=TIMEOUT)
    response.raise_for_status()
    svg = response.text
    # Line sets draw in currentColor; this is where the channel's ink goes.
    return svg.replace("currentColor", tint) if tint else svg


def rasterize(svg: str) -> bytes:
    """A transparent PNG of the SVG, SIZE px on its long side, drawn by
    the same Chrome that renders the scenes."""
    from playwright.sync_api import sync_playwright

    page_html = ("<html><body style='margin:0;background:transparent'>"
                 f"<div id='i' style='width:{SIZE}px;height:{SIZE}px'>{svg}</div>"
                 "<style>svg{width:100%;height:100%}</style></body></html>")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": SIZE, "height": SIZE})
            page.set_content(page_html)
            return page.locator("#i").screenshot(omit_background=True)
        finally:
            browser.close()


def get(library: Path, name: str, path: Path, icon_sets, tint: str = "") -> bool:
    """Save the first listed set's illustration of `name` to `path` (with a
    note of its source and licence beside it). False when no set has a
    good match or the library can't be reached; the caller generates one
    instead."""
    if isinstance(icon_sets, str):
        icon_sets = [icon_sets]
    icon, icon_set = "", ""
    for icon_set in icon_sets:
        icon = find(name, icon_set)
        if icon:
            break
    if not icon:
        return False
    try:
        png = rasterize(fetch_svg(icon, tint))
    except Exception as exc:  # noqa: BLE001 - falls back to generating, which says why
        log.info(f"  [scene] couldn't fetch {icon} ({exc}); generating instead")
        return False
    from pipeline.scenes.props import clean

    library.mkdir(parents=True, exist_ok=True)
    path.write_bytes(clean(png))
    licence, url = LICENCES.get(icon_set, ("see source", API))
    path.with_suffix(".json").write_text(json.dumps(
        {"name": name, "source": f"iconify:{icon}", "licence": licence, "licence_url": url,
         "tint": tint}, indent=1), encoding="utf-8")
    log.info(f"  [scene] prop from the free library: {name} -> {icon}")
    return True
