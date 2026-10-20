"""
A channel's own card designs (decision 123). The owner, on 20 Oct: the
new channels' cards were "basically identical", still "Title, 'X' vs
'Y'", when "the whole point is that these are supposed to be entirely
distinct channels". A palette and a font weren't enough: every channel
had the same smoked-glass panels in the same places.

So a design is its own shapes for every kind of card, not a recolour:
- "glass": the smoked-glass panels every channel had (pipeline.documentary
  .cards), the default, unchanged;
- "time_card": paper on a keeper's or a mill clerk's desk. A clock card
  with punch holes and a red rubber stamp, a two-column ledger, a typed
  order pinned with a brass split pin, a duty rota, a ticked duty list,
  a paper tag on the map;
- "scandal": a gossip page. A starburst under a black headline ribbon,
  two taped cards with a heart between them, a newspaper clipping swiped
  with highlighter, notes pinned on a string, a "juicy bits" list, a
  lipstick ring round the place on the map.

Each builder takes (card, duration) and returns (css, body), like the
glass ones, in the channel's own colours (--a1 to --a5, --ink, --bg).
An entrance sets an element's transform, so anything tilted or placed
by a transform sits inside a wrapper that makes the entrance (`_w`).
"""

from __future__ import annotations

import html

DESIGNS = ("glass", "time_card", "scandal")
LABELS = {"glass": "Smoked glass", "time_card": "Time card", "scandal": "Scandal sheet"}
esc = html.escape


def of(style: dict) -> str:
    design = (style or {}).get("card_design")
    return design if design in DESIGNS else "glass"


def _in(t: float, anim: str = "rise", dur: float = 0.6) -> str:
    return f"data-in='{t:.3f}' data-anim='{anim}' data-dur='{dur}'"


def _w(inner: str, t: float, anim: str = "rise", dur: float = 0.6, cls: str = "") -> str:
    return f"<div class='w {cls}' {_in(t, anim, dur)}>{inner}</div>"


def _sized(text: str, widest: int, largest: int, smallest: int = 60) -> int:
    """A display size that fits `text` across `widest` pixels: a heavy face
    is about 0.6em a letter. Measured, a tall face's glyphs overflow a
    line-height of 1, and the page's own fitting shrinks them to nothing."""
    return max(smallest, min(largest, int(widest / (0.6 * max(1, len(text))))))


def _split(item: str) -> tuple:
    if "|" in item:
        a, b = item.split("|", 1)
        return a.strip(), b.strip()
    return "", item.strip()


# --- the time card --------------------------------------------------------------------------

PAPER = "#EFE3C2"
PAPER_INK = "#2B2620"

TIME_SHARED = f"""
  .stage {{ align-items: center; }}
  .w {{ position: relative; }}
  .paper {{ position: relative; background: {PAPER}; color: {PAPER_INK};
            background-image: repeating-linear-gradient(0deg, transparent 0 63px, rgba(80,60,30,.16) 63px 65px);
            border-radius: 6px; box-shadow: 0 26px 70px rgba(0,0,0,.5), 0 3px 0 rgba(0,0,0,.25);
            padding: 70px 80px 60px; }}
  .paper::after {{ content: ''; position: absolute; inset: 0; border-radius: 6px; pointer-events: none;
                   background: radial-gradient(ellipse at 30% 20%, rgba(255,255,255,.18), transparent 60%),
                               radial-gradient(ellipse at 80% 90%, rgba(120,90,40,.16), transparent 55%); }}
  .holes {{ position: absolute; left: 40px; right: 40px; top: 18px; height: 26px;
            background: radial-gradient(circle at 13px 13px, #1a140e 0 10px, transparent 11px) 0 0 / 64px 26px repeat-x;
            opacity: .55; }}
  .head {{ font-family: var(--text); font-weight: 700; font-size: 40px; letter-spacing: .22em;
           text-transform: uppercase; color: {PAPER_INK}; border-bottom: 5px double {PAPER_INK};
           padding-bottom: 14px; margin-bottom: 26px; }}
  .typed {{ font-family: var(--display); color: {PAPER_INK}; }}
  .stamp {{ display: inline-block; font-family: var(--display); font-weight: 700; color: var(--a1);
            border: 9px solid var(--a1); border-radius: 18px; padding: 10px 40px; text-transform: uppercase;
            mix-blend-mode: multiply; opacity: .9; white-space: nowrap; }}
  .tilt-l {{ transform: rotate(-2.2deg); }}
  .tilt-r {{ transform: rotate(1.6deg); }}
  .pinhead {{ position: absolute; width: 46px; height: 46px; border-radius: 50%;
              background: radial-gradient(circle at 35% 30%, #fff3c4, #d6a640 45%, #7a5414 100%);
              box-shadow: 0 6px 10px rgba(0,0,0,.45); }}
"""

TIME_OVER = """
  .bg { background: #120d08 !important; }
  .bg-photo { position: absolute; inset: -40px; background-size: cover; background-position: center;
              filter: blur(14px) brightness(.55) saturate(.9) sepia(.25);
              transform: scale(calc(1.02 + 0.02 * var(--t, 0) / var(--T, 1))); }
  .bg-pattern { display: none; }
  .bg-vignette { background: radial-gradient(ellipse at 50% 50%, transparent 30%, rgba(0,0,0,.6) 100%) !important; }
"""


def _tc_number(card: dict, duration: float) -> tuple:
    value = card.get("value", "")
    stamp = _w(f"<div class='stamp big' style='font-size:{_sized(value, 980, 210)}px'>{esc(value)}</div>",
               0.55, "stamp", 0.45)
    note = (f"<div class='typed note' data-fit='34' {_in(1.1, 'wipe', 1.0)}>{esc(card.get('caption', ''))}</div>"
            if card.get("caption") else "")
    body = _w(f"<div class='paper clock tilt-l'><div class='holes'></div>"
              f"<div class='head'>{esc(card.get('heading', '') or 'Clock card')}</div>"
              f"<div class='slot'>{stamp}</div>{note}</div>", 0.1)
    css = """
      .clock { width: 1240px; }
      .slot { height: 300px; display: flex; align-items: center; justify-content: center; }
      .big { line-height: 1.15; max-width: 1080px; overflow: hidden; transform: rotate(-5deg); }
      .note { font-size: 50px; line-height: 1.25; margin-top: 18px; height: 130px; overflow: hidden;
              border-top: 3px dashed rgba(43,38,32,.4); padding-top: 18px; }
    """
    return css, body


def _tc_versus(card: dict, duration: float) -> tuple:
    sides = [_split(i) for i in card.get("items", [])[:2]]
    cols = "".join(
        f"<div class='col'><div class='colhead'>{esc(label)}</div>"
        f"<div class='typed amount' data-fit='54' {_in(0.5 + n * 0.6, 'wipe', 0.7)}>{esc(value)}</div></div>"
        for n, (label, value) in enumerate(sides))
    body = _w(f"<div class='paper ledger tilt-r'>"
              f"<div class='head'>{esc(card.get('heading', '') or 'Ledger')}</div>"
              f"<div class='cols'>{cols}</div></div>", 0.1)
    css = """
      .ledger { width: 1420px; }
      .cols { display: grid; grid-template-columns: 1fr 1fr; position: relative; }
      .cols::before { content: ''; position: absolute; left: 50%; top: -10px; bottom: -10px; width: 4px;
                      background: var(--a1); opacity: .75; }
      .col { padding: 0 50px; }
      .colhead { font-family: var(--text); font-weight: 700; font-size: 44px; text-transform: uppercase;
                 letter-spacing: .14em; color: var(--a2); margin-bottom: 26px; }
      .amount { font-size: 120px; line-height: 1.05; height: 270px; overflow: hidden; overflow-wrap: break-word; }
    """
    return css, body


def _tc_quote(card: dict, duration: float) -> tuple:
    body = _w(f"<div class='paper slip tilt-l'>"
              f"<div class='pinhead' style='left:34px;top:30px'></div>"
              f"<div class='head'>{esc(card.get('heading', '') or 'Orders')}</div>"
              f"<div class='typed said' data-fit='40' {_in(0.5, 'wipe', 1.8)}>{esc(card.get('caption', ''))}</div>"
              "</div>", 0.1)
    css = """
      .slip { width: 1360px; }
      .said { font-size: 72px; line-height: 1.25; height: 460px; overflow: hidden; }
    """
    return css, body


def _tc_timeline(card: dict, duration: float) -> tuple:
    items = [_split(i) for i in card.get("items", [])[:5]]
    step = min(0.9, max(0.35, duration * 0.5 / max(1, len(items))))
    rows = "".join(
        f"<div class='rrow' {_in(0.5 + i * step, 'slide-left')}>"
        f"<div class='stamp when' data-fit='30'>{esc(when)}</div>"
        f"<div class='typed what' data-fit='30'>{esc(what)}</div></div>"
        for i, (when, what) in enumerate(items))
    body = _w(f"<div class='paper rota tilt-r'><div class='holes'></div>"
              f"<div class='head'>{esc(card.get('heading', '') or 'Duty rota')}</div>{rows}</div>", 0.1)
    css = """
      .rota { width: 1300px; padding-bottom: 40px; }
      .rrow { display: grid; grid-template-columns: 360px 1fr; align-items: center; gap: 40px;
              height: 118px; border-bottom: 3px solid rgba(43,38,32,.18); }
      .when { font-size: 48px; padding: 4px 22px; border-width: 6px; transform: rotate(-3deg);
              max-width: 340px; overflow: hidden; justify-self: start; }
      .what { font-size: 50px; line-height: 1.1; height: 112px; display: flex; align-items: center; overflow: hidden; }
    """
    return css, body


def _tc_list(card: dict, duration: float) -> tuple:
    items = card.get("items", [])[:4]
    step = min(0.8, max(0.35, duration * 0.45 / max(1, len(items))))
    rows = "".join(
        "<div class='lrow'><div class='box'>" + _w("<div class='tick'></div>", 0.8 + i * step, "stamp", 0.35, "tickw")
        + f"</div><div class='typed t' data-fit='30' {_in(0.6 + i * step, 'wipe', 0.6)}>{esc(text)}</div></div>"
        for i, text in enumerate(items))
    body = _w(f"<div class='paper duty tilt-l'><div class='holes'></div>"
              f"<div class='head'>{esc(card.get('heading', '') or 'Duties')}</div>{rows}</div>", 0.1)
    css = f"""
      .duty {{ width: 1300px; }}
      .lrow {{ display: flex; align-items: center; gap: 40px; height: 120px; }}
      .box {{ width: 76px; height: 76px; border: 6px solid {PAPER_INK}; flex: none; position: relative; }}
      .tickw {{ position: absolute; inset: 0; }}
      .tick {{ position: absolute; left: 18px; top: -14px; width: 34px; height: 70px;
               border: solid var(--a1); border-width: 0 13px 13px 0; transform: rotate(40deg); }}
      .t {{ font-size: 54px; line-height: 1.1; height: 66px; flex: 1; overflow: hidden; white-space: nowrap; }}
    """
    return css, body


def _tc_map(card: dict, duration: float) -> tuple:
    from pipeline.documentary import cards
    css, body = cards._map(card, duration)
    css += f"""
      .bg {{ background: #9fb7c4 !important; }}
      .mapwrap {{ background: #9fb7c4 !important; }}
      .map path {{ stroke: {PAPER_INK} !important; stroke-width: 2.2 !important; }}
      .map .land {{ fill: {PAPER} !important; }}
      .map .home {{ fill: var(--a3) !important; }}
      .pin {{ background: radial-gradient(circle at 35% 30%, #fff3c4, #d6a640 45%, #7a5414 100%) !important;
              border: none !important; box-shadow: 0 8px 14px rgba(0,0,0,.45) !important; }}
      .tag {{ background: {PAPER} !important; color: {PAPER_INK} !important; border-radius: 4px 18px 18px 4px !important;
              box-shadow: 0 14px 30px rgba(0,0,0,.35) !important; border: none !important; }}
      .tag .place {{ font-family: var(--display) !important; color: {PAPER_INK}; }}
    """
    return css, body


# --- the scandal sheet ----------------------------------------------------------------------

SCRIPT_FONT = "'Ink Free', 'Segoe Print', cursive"

SCANDAL_SHARED = f"""
  .stage {{ align-items: center; }}
  .w {{ position: relative; }}
  .ribbon {{ display: inline-block; background: #111; color: #fff; font-family: var(--display);
             font-weight: var(--dw); text-transform: uppercase; letter-spacing: .06em; font-size: 58px;
             padding: 10px 40px; transform: rotate(-3deg); box-shadow: 10px 10px 0 var(--a1); }}
  .scrawl {{ font-family: {SCRIPT_FONT}; font-weight: 700; color: var(--ink); }}
  .sticky {{ position: relative; background: #FFF6EC; color: #1d1418; border-radius: 4px; padding: 46px 50px;
             box-shadow: 0 24px 60px rgba(0,0,0,.45); }}
  .sticky.pink {{ background: var(--a1); color: var(--on-a1); }}
  .tape {{ position: absolute; top: -26px; left: 50%; width: 190px; height: 54px; margin-left: -95px;
           background: rgba(255,255,255,.55); transform: rotate(-4deg); box-shadow: 0 2px 6px rgba(0,0,0,.15); }}
  .heart {{ width: 150px; height: 140px; background: var(--a2); flex: none;
            clip-path: path('M75 135 C 20 95 0 70 0 42 C 0 18 18 0 42 0 C 58 0 70 9 75 22 C 80 9 92 0 108 0 C 132 0 150 18 150 42 C 150 70 130 95 75 135 Z');
            display: flex; align-items: center; justify-content: center; }}
"""

SCANDAL_OVER = """
  .bg { background: #14060f !important; }
  .bg-photo { position: absolute; inset: -40px; background-size: cover; background-position: center;
              filter: blur(16px) brightness(.45) saturate(1.35);
              transform: scale(calc(1.02 + 0.02 * var(--t, 0) / var(--T, 1))); }
  .bg-pattern { display: none; }
  .bg-vignette { background: radial-gradient(ellipse at 50% 50%, transparent 30%, rgba(40,0,25,.65) 100%) !important; }
"""


def _ribbon(text: str) -> str:
    return _w(f"<div class='ribbon'>{esc(text)}</div>", 0.1, "slide-left") if text else ""


def _sc_number(card: dict, duration: float) -> tuple:
    value = card.get("value", "")
    burst = _w(f"<div class='burst'><div class='num' style='font-size:{_sized(value, 560, 190)}px'>{esc(value)}</div>"
               "</div>", 0.4, "spring", 0.7)
    cap = (f"<div class='scrawl cap' data-fit='34' {_in(1.1, 'wipe', 1.0)}>{esc(card.get('caption', ''))}</div>"
           if card.get("caption") else "")
    body = _ribbon(card.get("heading", "")) + burst + cap
    css = """
      .burst { width: 900px; height: 520px; background: var(--a1); color: var(--on-a1); transform: rotate(-4deg);
               clip-path: polygon(50% 0%, 58% 14%, 72% 4%, 74% 20%, 92% 14%, 86% 32%, 100% 40%, 88% 52%, 98% 68%,
                                  80% 70%, 82% 88%, 66% 80%, 58% 100%, 48% 84%, 34% 98%, 30% 80%, 12% 88%, 16% 70%,
                                  0% 62%, 12% 48%, 2% 32%, 20% 30%, 16% 12%, 34% 18%, 40% 2%);
               display: flex; align-items: center; justify-content: center; }
      .num { font-family: var(--display); font-weight: var(--dw); line-height: 1.15; width: 600px;
             text-align: center; white-space: nowrap; overflow: hidden; }
      .cap { font-size: 56px; line-height: 1.2; text-align: center; max-width: 1300px; height: 140px; overflow: hidden;
             border-bottom: 8px solid var(--a2); padding-bottom: 6px; }
    """
    return css, body


def _sc_versus(card: dict, duration: float) -> tuple:
    sides = [_split(i) for i in card.get("items", [])[:2]]
    cells = [_w(f"<div class='sticky {'pink' if n else ''} side' style='transform:rotate({-3 if n == 0 else 3}deg)'>"
                f"<div class='tape'></div><div class='slabel'>{esc(label)}</div>"
                f"<div class='sval' data-fit='44'>{esc(value)}</div></div>", 0.3 + n * 0.5, "spring", 0.6)
             for n, (label, value) in enumerate(sides)]
    heart = _w("<div class='heart'><span class='scrawl vs'>or</span></div>", 0.9, "pop")
    body = (_ribbon(card.get("heading", ""))
            + f"<div class='vrow'>{cells[0] if cells else ''}{heart}{cells[1] if len(cells) > 1 else ''}</div>")
    css = """
      .vrow { display: flex; align-items: center; justify-content: center; gap: 30px; margin-top: 30px; }
      .side { width: 620px; height: 440px; display: flex; flex-direction: column; justify-content: center; }
      .slabel { font-family: var(--text); font-weight: 800; font-size: 40px; text-transform: uppercase;
                letter-spacing: .1em; opacity: .75; margin-bottom: 18px; }
      .sval { font-family: var(--display); font-weight: var(--dw); font-size: 110px; line-height: 1.02;
              height: 290px; overflow: hidden; overflow-wrap: break-word; }
      .vs { font-size: 56px; color: #fff; margin-top: -8px; }
    """
    return css, body


def _sc_quote(card: dict, duration: float) -> tuple:
    clipping = (f"<div class='clip'>" + _w("<div class='hl'></div>", 0.8, "grow", 1.2, "hlw")
                + f"<div class='qtext' data-fit='40'>&ldquo;{esc(card.get('caption', ''))}&rdquo;</div></div>")
    who = (f"<div class='scrawl who' {_in(1.8, 'wipe', 0.8)}>&mdash; {esc(card['heading'])}</div>"
           if card.get("heading") else "")
    body = _w(clipping, 0.1, "spring", 0.6) + who
    css = """
      .clip { position: relative; width: 1400px; background: #F4EEE0; color: #1b1712; padding: 70px 80px;
              transform: rotate(-1.5deg); box-shadow: 0 24px 60px rgba(0,0,0,.5);
              clip-path: polygon(0 3%, 6% 0, 14% 2%, 26% 0, 38% 3%, 52% 0, 66% 2%, 80% 0, 92% 3%, 100% 1%,
                                 99% 50%, 100% 97%, 90% 100%, 76% 97%, 60% 100%, 44% 97%, 30% 100%, 16% 98%, 4% 100%, 1% 60%); }
      .hlw { position: absolute; inset: 0; }
      .hl { position: absolute; left: 60px; right: 60px; top: 42%; height: 120px; background: var(--a1); opacity: .45;
            transform: rotate(-1deg); }
      .qtext { position: relative; font-family: Georgia, serif; font-style: italic; font-size: 76px; line-height: 1.22;
               height: 440px; display: flex; align-items: center; overflow: hidden; }
      .who { font-size: 54px; margin-top: 36px; align-self: flex-end; margin-right: 140px; }
    """
    return css, body


def _sc_timeline(card: dict, duration: float) -> tuple:
    items = [_split(i) for i in card.get("items", [])[:5]]
    n = max(1, len(items))
    step = min(0.9, max(0.35, duration * 0.5 / n))
    notes = []
    for i, (when, what) in enumerate(items):
        left = 100 * (i + 0.5) / n
        angle = (-5, 4, -3, 5, -4)[i % 5]
        notes.append(f"<div class='pinned' style='left:{left:.2f}%'>" + _w(
            f"<div class='sticky {'pink' if i % 2 else ''} pn' style='transform:rotate({angle}deg)'>"
            f"<div class='pinball'></div><div class='pwhen' data-fit='34'>{esc(when)}</div>"
            f"<div class='pwhat' data-fit='24'>{esc(what)}</div></div>", 0.6 + i * step, "spring", 0.6) + "</div>")
    body = (_ribbon(card.get("heading", ""))
            + f"<div class='string-wrap'><svg class='string' viewBox='0 0 1600 120'><path d='M 0 30 Q 800 120 1600 30' "
              f"stroke='var(--ink)' stroke-width='5' fill='none' {_in(0.3, 'draw', 1.0)}/></svg>{''.join(notes)}</div>")
    css = """
      .string-wrap { position: relative; width: 1600px; height: 600px; margin: 10px auto 0; }
      .string { position: absolute; left: 0; top: 0; width: 1600px; height: 120px; }
      .pinned { position: absolute; top: 60px; width: 290px; transform: translateX(-50%); }
      .pn { padding: 50px 26px 30px; height: 380px; }
      .pinball { position: absolute; top: 12px; left: 50%; width: 30px; height: 30px; margin-left: -15px;
                 border-radius: 50%; background: var(--a2); box-shadow: 0 4px 6px rgba(0,0,0,.4); }
      .pwhen { font-family: var(--display); font-weight: var(--dw); font-size: 58px; line-height: 1; height: 70px;
               overflow: hidden; white-space: nowrap; text-align: center; }
      .pwhat { font-size: 36px; line-height: 1.15; height: 220px; overflow: hidden; margin-top: 18px; text-align: center; }
    """
    return css, body


def _sc_list(card: dict, duration: float) -> tuple:
    items = card.get("items", [])[:4]
    step = min(0.8, max(0.35, duration * 0.45 / max(1, len(items))))
    rows = "".join(_w(
        f"<div class='srow' style='transform:rotate({(-1.5, 1.2, -1, 1.5)[i % 4]}deg)'>"
        f"<div class='heart small'><span>{i + 1}</span></div><div class='st' data-fit='30'>{esc(text)}</div></div>",
        0.6 + i * step, "slide-" + ("left" if i % 2 == 0 else "right")) for i, text in enumerate(items))
    body = _ribbon(card.get("heading", "") or "The juicy bits") + f"<div class='srows'>{rows}</div>"
    css = """
      .srows { display: grid; gap: 26px; width: 1360px; margin: 34px auto 0; }
      .srow { display: flex; align-items: center; gap: 30px; background: #FFF6EC; color: #1d1418;
              padding: 14px 34px 14px 20px; box-shadow: 0 14px 30px rgba(0,0,0,.35); border-radius: 4px; }
      .heart.small { width: 96px; height: 90px;
                     clip-path: path('M48 87 C 13 61 0 45 0 27 C 0 12 12 0 27 0 C 37 0 45 6 48 14 C 51 6 59 0 69 0 C 84 0 96 12 96 27 C 96 45 83 61 48 87 Z'); }
      .heart.small span { font-family: var(--display); font-weight: var(--dw); color: #fff; font-size: 44px; margin-top: -6px; }
      .st { font-size: 54px; line-height: 1.1; height: 66px; flex: 1; overflow: hidden; white-space: nowrap; }
    """
    return css, body


def _sc_map(card: dict, duration: float) -> tuple:
    from pipeline.documentary import cards
    css, body = cards._map(card, duration)
    _, _, (px, py) = cards.map_svg(card["lat"], card["lon"])
    ring = (f"<svg class='lips' viewBox='0 0 1920 1080'><ellipse cx='{px:.1f}' cy='{py:.1f}' rx='190' ry='120' "
            f"transform='rotate(-8 {px:.1f} {py:.1f})' stroke='var(--a1)' stroke-width='16' fill='none' "
            f"stroke-linecap='round' {_in(1.0, 'draw', 1.0)}/></svg>")
    body = body.replace("<div class='pin", ring + "<div class='pin", 1)
    css += """
      .bg { background: #2a0f2a !important; }
      .mapwrap { background: #2a0f2a !important; }
      .map path { stroke: rgba(255,230,240,.55) !important; stroke-width: 1.6 !important; }
      .map .land { fill: #4a1d45 !important; }
      .map .home { fill: var(--a2) !important; }
      .lips { position: absolute; inset: 0; width: 1920px; height: 1080px; }
      .pin { background: var(--a1) !important; border-color: #fff !important; }
      .tag { background: #FFF6EC !important; color: #1d1418 !important; border: none !important;
             box-shadow: 8px 8px 0 var(--a1) !important; }
      .tag .place { font-family: 'Ink Free', 'Segoe Print', cursive !important; }
    """
    return css, body


BUILDERS = {
    "time_card": {"number": _tc_number, "versus": _tc_versus, "quote": _tc_quote, "timeline": _tc_timeline,
                  "list": _tc_list, "map": _tc_map},
    "scandal": {"number": _sc_number, "versus": _sc_versus, "quote": _sc_quote, "timeline": _sc_timeline,
                "list": _sc_list, "map": _sc_map},
}
SHARED = {"time_card": TIME_SHARED, "scandal": SCANDAL_SHARED}
OVER = {"time_card": TIME_OVER, "scandal": SCANDAL_OVER}
