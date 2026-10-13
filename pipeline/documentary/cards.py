"""
Animated cards for documentaries: a number, a comparison, a quote, a
timeline, a list, or a map of where the story is (decision 086).

A widescreen film that is one kind of picture for ten minutes reads as a
slideshow. These are the other kinds: drawn here as pages in the
channel's own theme (pipeline.templates.theme: its palette, its display
face, its background), filmed by the page renderer, then given the same
grade and grain as the stills, so they look like part of the film. They
cost nothing to make.

The map uses Natural Earth's country shapes (already cached for the quiz
outlines): a slow zoom onto the place, its country picked out in the
accent colour, a pin and its name.

Over a picture (decision 087): the first film's cards were bright
parchment slides between dark paintings, a jump of nearly five times in
brightness, and read as a different film. Given a `backdrop` (the scene
before), a card is drawn over that picture, blurred and darkened, in
light type on a smoked-glass panel, so it's a moment in the film.
"""

from __future__ import annotations

import html
import math
import re
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger(__name__)

SIZE = (1920, 1080)
KINDS = ("number", "versus", "quote", "timeline", "list", "map")
esc = html.escape


def _in(t: float, anim: str = "rise", dur: float = 0.6) -> str:
    return f"data-in='{t:.3f}' data-anim='{anim}' data-dur='{dur}'"


def _split(item: str) -> tuple:
    if "|" in item:
        a, b = item.split("|", 1)
        return a.strip(), b.strip()
    return "", item.strip()


NUMBER = re.compile(r"^([^\d-]*)(-?[\d,]*\.?\d+)(.*)$")


def _number(card: dict, duration: float) -> tuple:
    value = card.get("value", "")
    match = NUMBER.match(value.strip())
    counted = ""
    if match and match.group(2).replace(",", "").replace(".", "").isdigit():
        number = float(match.group(2).replace(",", ""))
        decimals = len(match.group(2).split(".")[1]) if "." in match.group(2) else 0
        counted = (f" data-count-to='{number}' data-count-from='0' data-decimals='{decimals}' "
                   f"data-prefix='{esc(match.group(1))}' data-suffix='{esc(match.group(3))}'")
    body = (f"<div class='kicker' {_in(0.2)}>{esc(card.get('heading', ''))}</div>"
            f"<div class='hero big a1 accent-text' data-fit='120' {_in(0.45, 'pop', 0.7)}{counted}>"
            # The final value from the start, so the fit is measured on it, not
            # on "0" (decision 093: "100,000,000 years" ran off the card).
            f"{esc(value)}</div>"
            + (f"<div class='card filled a2 cap' {_in(1.1)}><div class='body'>{esc(card.get('caption', ''))}</div></div>"
               if card.get("caption") else ""))
    css = """
      .big { font-size: 260px; white-space: nowrap; }
      .cap { padding: 26px 48px; border-radius: 22px; max-width: 1300px; margin: 0 auto; }
      .cap .body { font-size: 52px; text-align: center; }
    """
    return css, body


def _versus(card: dict, duration: float) -> tuple:
    sides = [_split(i) for i in card.get("items", [])[:2]]
    cells = []
    for n, (label, value) in enumerate(sides):
        # Sized to its length here (a display face is about 0.58em a
        # letter), and allowed a second line rather than running off the card.
        size = max(46, min(130, int(540 / (0.58 * max(1, len(value))))))
        label_size = max(34, min(54, int(1000 / max(1, len(label)))))
        cells.append(f"<div class='card side filled a{1 + n * 2}' {_in(0.3 + n * 0.5, 'slide-' + ('left' if n == 0 else 'right'))}>"
                     f"<div class='label' style='font-size:{label_size}px'>{esc(label)}</div>"
                     f"<div class='hero val' style='font-size:{size}px'>{esc(value)}</div></div>")
    body = ((f"<div class='kicker' {_in(0.1)}>{esc(card['heading'])}</div>" if card.get("heading") else "")
            + f"<div class='row'>{cells[0]}<div class='chip vs filled a2' {_in(0.9, 'pop')}>vs</div>{cells[1]}</div>")
    css = """
      .row { display: flex; align-items: center; justify-content: center; gap: 40px; }
      .side { width: 620px; height: 420px; border-radius: 28px; display: flex; flex-direction: column;
              align-items: center; justify-content: center; gap: 20px; padding: 30px; }
      .side .label { letter-spacing: .03em; text-align: center; line-height: 1.1; }
      .side .val { width: 560px; text-align: center; line-height: 1.05; overflow-wrap: break-word; }
      .vs { width: 150px; height: 150px; font-size: 60px; }
    """
    return css, body


def _quote(card: dict, duration: float) -> tuple:
    body = (f"<div class='mark accent-text a1' {_in(0.1, 'pop')}>&ldquo;</div>"
            f"<div class='hero qt' data-fit='44' {_in(0.4, 'wipe', 1.6)}>{esc(card.get('caption', ''))}</div>"
            + (f"<div class='kicker who' {_in(2.0)}>{esc(card['heading'])}</div>" if card.get("heading") else ""))
    css = """
      .mark { font-family: var(--display); font-size: 300px; line-height: .55; height: 150px; text-align: center; }
      .qt { font-size: 88px; line-height: 1.15; max-width: 1500px; height: 520px; margin: 0 auto;
            display: flex; align-items: center; justify-content: center; text-align: center; }
      .who { font-size: 44px; }
    """
    return css, body


def _timeline(card: dict, duration: float) -> tuple:
    items = [_split(i) for i in card.get("items", [])[:5]]
    n = len(items)
    step = min(0.9, max(0.35, (duration * 0.5) / max(1, n)))
    stops = []
    for i, (when, what) in enumerate(items):
        left = 100 * (i + 0.5) / n
        at = 0.6 + i * step
        size = max(36, min(64, int(620 / max(1, len(when)))))
        stops.append(f"<div class='stop' style='left:{left:.2f}%'>"
                     f"<div class='when hero accent-text a{1 + i % 5}' style='font-size:{size}px' {_in(at, 'rise')}>"
                     f"{esc(when)}</div>"
                     f"<div class='dot filled a{1 + i % 5}' {_in(at, 'pop', 0.4)}></div>"
                     f"<div class='what' data-fit='26' {_in(at + 0.15)}>{esc(what)}</div></div>")
    body = ((f"<div class='kicker' {_in(0.1)}>{esc(card['heading'])}</div>" if card.get("heading") else "")
            + f"<div class='line-wrap'><svg class='rail' viewBox='0 0 1600 20'><path d='M 0 10 L 1600 10' "
              f"stroke='var(--ink)' stroke-width='8' stroke-linecap='round' fill='none' {_in(0.3, 'draw', 1.2)}/>"
              f"</svg>{''.join(stops)}</div>")
    css = """
      .line-wrap { position: relative; width: 1600px; height: 520px; margin: 0 auto; }
      .rail { position: absolute; left: 0; top: 250px; width: 1600px; height: 20px; }
      .stop { position: absolute; top: 0; width: 300px; transform: translateX(-50%); height: 520px; }
      .stop .when { position: absolute; bottom: 300px; width: 300px; text-align: center; line-height: 1.05; }
      .stop .dot { position: absolute; top: 236px; left: 126px; width: 48px; height: 48px; border-radius: 50%;
                   border: 6px solid var(--ink); }
      .stop .what { position: absolute; top: 310px; width: 300px; height: 190px; font-size: 40px;
                    line-height: 1.15; text-align: center; overflow: hidden; }
    """
    return css, body


def _list(card: dict, duration: float) -> tuple:
    items = card.get("items", [])[:4]
    step = min(0.8, max(0.35, duration * 0.45 / max(1, len(items))))
    rows = "".join(f"<div class='li card' {_in(0.6 + i * step, 'slide-left')}><span class='n filled a{1 + i}'>"
                   f"{i + 1}</span><span class='t' data-fit='30'>{esc(text)}</span></div>"
                   for i, text in enumerate(items))
    body = f"<div class='title' {_in(0.15)}>{esc(card.get('heading', ''))}</div><div class='rows'>{rows}</div>"
    css = """
      .title { font-size: 84px; }
      .rows { display: grid; gap: 22px; width: 1300px; margin: 0 auto; }
      .li { display: flex; align-items: center; gap: 32px; padding: 18px 28px; border-radius: 20px; }
      .li .n { width: 84px; height: 84px; border-radius: 50%; display: flex; align-items: center;
               justify-content: center; font-family: var(--display); font-weight: var(--dw); font-size: 48px; flex: none; }
      .li .t { font-size: 52px; line-height: 1.1; height: 66px; flex: 1; overflow: hidden; white-space: nowrap; }
    """
    return css, body


# --- the map --------------------------------------------------------------------------

VIEW_DEGREES = 34.0             # longitude across the frame at the start
ZOOM = 2.2                      # how far it closes in on the place over the scene


def _contains(ring: list, lon: float, lat: float) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def map_svg(lat: float, lon: float, width: int = SIZE[0], height: int = SIZE[1]) -> tuple:
    """(svg paths for the countries around the place, the place's country
    name or "", (x, y) of the place) on a frame `width` by `height`
    centred on it, VIEW_DEGREES of longitude across."""
    from pipeline import pictures
    squash = max(math.cos(math.radians(lat)), 0.2)
    scale = width / VIEW_DEGREES                      # pixels per degree of longitude
    half_w = VIEW_DEGREES / 2 * 1.6                   # degrees either side worth drawing
    half_h = height * squash / scale / 2 * 1.6

    # Equirectangular, true to shape at the place's latitude: VIEW_DEGREES
    # of longitude across the frame, a degree of latitude 1/squash taller.
    def project(x, y):
        return (width / 2 + (x - lon) * scale, height / 2 - (y - lat) * scale / squash)

    home, paths = "", []
    for name, geometry in pictures._shapes().items():
        rings = pictures._rings(geometry) if geometry["type"] == "Polygon" else \
            [poly[0] for poly in geometry["coordinates"]]
        near = [r for r in rings if any(abs(px - lon) < half_w and abs(py - lat) < half_h for px, py in r[::3] or r)]
        if not near:
            continue
        is_home = any(_contains(r, lon, lat) for r in rings)
        if is_home:
            home = name
        d = " ".join("M" + " L".join(f"{a:.1f},{b:.1f}" for a, b in (project(px, py) for px, py in r)) + " Z"
                     for r in near)
        paths.append((is_home, d))
    return paths, home, project(lon, lat)


def _map(card: dict, duration: float) -> tuple:
    paths, home, (px, py) = map_svg(card["lat"], card["lon"])
    land = "".join(f"<path class='{'home' if is_home else 'land'}' d='{d}'/>" for is_home, d in paths)
    zoom_end = 1 + (ZOOM - 1)
    body = (f"<div class='mapwrap'><svg class='map' viewBox='0 0 {SIZE[0]} {SIZE[1]}' "
            f"style='transform-origin:{px:.1f}px {py:.1f}px'>{land}</svg>"
            f"<div class='pin filled a1' style='left:{px - 24:.1f}px;top:{py - 24:.1f}px' {_in(0.9, 'pop', 0.5)}></div>"
            f"<div class='tag card filled a2' style='left:{px + 44:.1f}px;top:{py - 70:.1f}px' {_in(1.2, 'slide-left')}>"
            f"<div class='place'>{esc(card['heading'])}</div>"
            + (f"<div class='sub'>{esc(card['caption'])}</div>" if card.get("caption") else "")
            + "</div></div>")
    css = f"""
      .stage {{ display: none; }}
      .mapwrap {{ position: absolute; inset: 0; overflow: hidden; }}
      .map {{ position: absolute; inset: 0; width: {SIZE[0]}px; height: {SIZE[1]}px;
              transform: scale(calc(1 + {zoom_end - 1:.3f} * min(1, var(--t, 0) / max(1, var(--T, 1) * 0.8)))); }}
      .map path {{ stroke: var(--ink); stroke-width: 1.4; stroke-linejoin: round; }}
      .map .land {{ fill: var(--bg); }}
      .map .home {{ fill: var(--a1); }}
      .bg {{ background: color-mix(in srgb, var(--a5) 42%, var(--bg)) !important; }}
      .bg-pattern {{ display: none; }}
      .pin {{ position: absolute; width: 48px; height: 48px; border-radius: 50%; border: 8px solid var(--ink);
              box-shadow: 0 0 0 14px rgba(255,255,255,.35); }}
      .tag {{ position: absolute; padding: 18px 34px; border-radius: 20px; max-width: 760px; }}
      .tag .place {{ font-family: var(--display); font-weight: var(--dw); font-size: 66px; line-height: 1; }}
      .tag .sub {{ font-size: 38px; margin-top: 8px; }}
    """
    # The pin and its label stay put while the map zooms: they're placed
    # where the place ends up, at the zoom's centre, which doesn't move.
    return css, body


BUILDERS = {"number": _number, "versus": _versus, "quote": _quote, "timeline": _timeline,
            "list": _list, "map": _map}


OVER_PICTURE = """
  :root { --ink: #F6F0E6; --soft: rgba(246,240,230,.78); --card: rgba(16,13,10,.58); --on-card: #F6F0E6; }
  .bg { background: #0d0b09 !important; }
  .bg-photo { position: absolute; inset: -40px; background-size: cover; background-position: center;
              filter: blur(18px) brightness(.42) saturate(1.1);
              transform: scale(calc(1.02 + 0.02 * var(--t, 0) / var(--T, 1))); }
  .bg-pattern { display: none; }
  .bg-vignette { background: radial-gradient(ellipse at 50% 50%, transparent 35%, rgba(0,0,0,.55) 100%) !important; }
  .card { background: var(--card) !important; border: 1px solid rgba(246,240,230,.22) !important;
          backdrop-filter: blur(6px); box-shadow: 0 18px 50px rgba(0,0,0,.35) !important; }
  .card.filled { background: color-mix(in srgb, var(--fill) 78%, #000) !important; }
  .chip { box-shadow: 0 10px 30px rgba(0,0,0,.35); }
  .kicker, .title, .hero:not(.accent-text) { text-shadow: 0 4px 24px rgba(0,0,0,.5); }
  .rail path, .map path { stroke: rgba(246,240,230,.55) !important; }
  .map .land { fill: color-mix(in srgb, var(--bg) 40%, #1b1611) !important; }
  .map .home { fill: color-mix(in srgb, var(--a1) 85%, #000) !important; }
  .mapwrap { background: color-mix(in srgb, var(--a5) 30%, #0b0a09); }
"""


def build(card: dict, style: dict, duration: float, backdrop: Path = None) -> str:
    """The card as one self-contained seekable page; over `backdrop` (a
    picture, blurred and darkened) when given."""
    from pipeline.templates import page, theme
    kind = card.get("kind")
    if kind not in BUILDERS:
        raise ValueError(f"no card kind {kind!r}")
    css, body = BUILDERS[kind](card, max(1.0, duration))
    photo = ""
    if backdrop is not None and Path(backdrop).exists():
        import base64
        data = base64.b64encode(Path(backdrop).read_bytes()).decode("ascii")
        photo = f"<div class='bg-photo' style=\"background-image:url(data:image/jpeg;base64,{data})\"></div>"
        css += OVER_PICTURE
    return ("<!doctype html><html><head><meta charset='utf-8'><style>"
            f"{theme.css(style)}"
            f"html, body {{ width: {SIZE[0]}px; height: {SIZE[1]}px; }}"
            f".bg-grain {{ background-image: url({page.GRAIN}); }}"
            ".stage { left: 160px; top: 110px; width: 1600px; height: 860px; gap: 40px; }"
            f"{css}</style></head><body>{page.FILTERS}"
            f"<div class='bg'>{photo}<div class='bg-pattern'></div><div class='bg-grain'></div>"
            f"<div class='bg-vignette'></div></div>"
            + (body if kind == "map" else f"<div class='stage'>{body}</div>")
            + f"<script>window.TEMPLATE_DURATION = {max(1.0, duration):.3f};</script>"
            f"<script>{page.RUNTIME.read_text(encoding='utf-8')}</script></body></html>")


def style_for(channel) -> dict:
    from pipeline.scenes import art
    return art.resolve(channel.scenes.art)


def preview(card: dict, style: dict, out: Path, at: float = 3.0, backdrop: Path = None) -> Path:
    """A still of the card once it's built, for the storyboard."""
    from pipeline.scenes import render
    render.page_frame(build(card, style, max(at + 1, 5.0), backdrop), at, out, size=SIZE)
    return Path(out)


def clip(card: dict, style: dict, seconds: float, out: Path, backdrop: Path = None) -> Path:
    """The card filmed for `seconds`."""
    from pipeline.scenes import render
    return render.render_page(build(card, style, seconds, backdrop), seconds, Path(out), size=SIZE)
