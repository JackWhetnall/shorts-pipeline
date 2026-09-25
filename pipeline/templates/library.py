"""
The motion-graphics templates: designed once, filled by the model.

Each template is a fixed, balanced composition for one kind of point (a
big number, this-versus-that, a list, a process...). The model only
chooses a template and fills its slots with words, numbers and icon
names, each timed to the spoken word it enters on; it never lays
anything out. That is what keeps every frame full, legible and on-brand:
the first generation of scenes, where the model placed shapes itself,
came out sparse, with invisible labels and pictures unrelated to the
words. See decision 040.

A template here is: a description and slot guide for the model, its
beats (the moments things enter), which beats deserve a sound, and a
builder that returns the stage's HTML for a filled template.
"""

from __future__ import annotations

import html
import math

from pipeline.templates import tex

ACCENTS = ("a1", "a2", "a3", "a4", "a5")


def esc(text) -> str:
    return html.escape(str(text or ""))


def _icon(icons, name, size: int, extra: str = "") -> str:
    uri = icons(name) if name else ""
    if uri:
        return f"<img class='icon' src='{uri}' style='width:{size}px;height:{size}px' alt='' {extra}>"
    letter = esc((str(name or "?").strip() or "?")[0].upper())
    return (f"<div class='chip filled a3' style='width:{size}px;height:{size}px;"
            f"font-size:{size // 2}px' {extra}>{letter}</div>")


def _in(t, anim="rise", dur=0.5) -> str:
    return f"data-in='{t:.3f}' data-anim='{anim}' data-dur='{dur}'"


# --- the templates -------------------------------------------------------------

def big_number(s, t, icons):
    value = float(s["value"])
    decimals = int(s.get("decimals") or (0 if value == int(value) else 1))
    icon = _icon(icons, s.get("icon"), 150) if s.get("icon") else ""
    return f"""
    <style>
      .bn-num {{ font-size: 250px; width: 1000px; height: 290px; white-space: nowrap; overflow: hidden; }}
      .bn-line {{ width: 1000px; height: 60px; }}
      .bn-cap {{ display: flex; gap: 36px; align-items: center; padding: 40px 48px; min-height: 260px; }}
      .bn-cap .body {{ flex: 1; height: 200px; display: flex; align-items: center; color: var(--on-card); font-size: 58px; }}
    </style>
    <div class="kicker" style="height:60px" data-fit="28" {_in(t['kicker'])}>{esc(s.get('kicker'))}</div>
    <div class="hero bn-num a1 accent-text glow" data-fit="120" {_in(t['value'], 'pop', 0.6)}
         data-count-to="{value}" data-count-from="{float(s.get('count_from') or 0)}" data-decimals="{decimals}"
         data-prefix="{esc(s.get('prefix'))}" data-suffix="{esc(s.get('suffix'))}"></div>
    <svg class="bn-line" viewBox="0 0 1000 60"><path d="M 220 38 Q 500 8 780 38" fill="none"
         stroke="var(--a2)" stroke-width="14" stroke-linecap="round" {_in(t['value'] + 0.4, 'draw', 0.6)}/></svg>
    <div class="card bn-cap" {_in(t['caption'])}>{icon}<div class="body" data-fit="30">{esc(s.get('caption'))}</div></div>
    """


def versus(s, t, icons):
    def side(key, accent, at, anim):
        d = s[key]
        return f"""
        <div class="card vs-side" {_in(at, anim)}>
          <div class="chip filled {accent} vs-label" data-fit="28">{esc(d.get('label'))}</div>
          <div class="vs-icon">{_icon(icons, d.get('icon'), 230)}</div>
          <div class="hero vs-value {accent} accent-text" data-fit="30">{esc(d.get('value'))}</div>
        </div>"""
    verdict = s.get("verdict")
    return f"""
    <style>
      .vs-row {{ display: flex; gap: 40px; position: relative; }}
      .vs-side {{ flex: 1; height: 700px; display: flex; flex-direction: column; align-items: center;
                 justify-content: space-between; padding: 40px 24px; }}
      .vs-label {{ font-size: 50px; padding: 14px 34px; max-width: 420px; height: 90px; white-space: nowrap; overflow: hidden; }}
      .vs-icon {{ height: 260px; display: flex; align-items: center; }}
      .vs-value {{ font-size: 78px; width: 420px; height: 200px; display: flex; align-items: center; justify-content: center; }}
      .vs-badge {{ position: absolute; left: 50%; top: 50%; width: 150px; height: 150px; margin: -75px 0 0 -75px;
                  font-size: 64px; z-index: 2; }}
      .vs-verdict {{ padding: 34px 44px; min-height: 200px; display: flex; align-items: center; justify-content: center; }}
      .vs-verdict .body {{ height: 150px; width: 100%; display: flex; align-items: center; justify-content: center;
                          text-align: center; font-size: 56px; font-family: var(--display); font-weight: var(--dw); }}
    </style>
    <div class="title" style="height:170px" data-fit="40" {_in(t['title'])}>{esc(s.get('title'))}</div>
    <div class="vs-row">
      {side('left', 'a1', t['left'], 'slide-left')}
      {side('right', 'a2', t['right'], 'slide-right')}
      <div class="chip filled a3 vs-badge" {_in(t['right'] + 0.25, 'pop')}>VS</div>
    </div>
    {f'<div class="card filled a4 vs-verdict" {_in(t["verdict"], "pop")}><div class="body" data-fit="30">{esc(verdict)}</div></div>' if verdict else ''}
    """


def items_list(s, t, icons):
    items = s["items"][:5]
    hi = s.get("highlight")
    rows = []
    for i, item in enumerate(items):
        filled = "filled a1" if hi is not None and int(hi) == i else ""
        rows.append(f"""
        <div class="card li-row {filled}" {_in(t[f'item{i}'], 'slide-left')}>
          <div class="li-icon">{_icon(icons, item.get('icon'), 120)}</div>
          <div class="body li-text" data-fit="30">{esc(item.get('text'))}</div>
        </div>""")
    n = len(items)
    row_h = min(200, (900 - 30 * (n - 1)) // n)
    return f"""
    <style>
      .li-row {{ display: flex; align-items: center; gap: 34px; padding: 0 40px; height: {row_h}px; }}
      .li-icon {{ width: 130px; flex: none; display: flex; justify-content: center; }}
      .li-text {{ flex: 1; height: {row_h - 30}px; display: flex; align-items: center; font-size: 56px; color: inherit; }}
      .li-row:not(.filled) .li-text {{ color: var(--on-card); }}
    </style>
    <div class="title" style="height:170px" data-fit="40" {_in(t['title'])}>{esc(s.get('title'))}</div>
    {''.join(rows)}
    """


def steps(s, t, icons):
    items = s["steps"][:5]
    n = len(items)
    step_h = min(190, (900 - 36 * (n - 1)) // n)
    rows = "".join(f"""
      <div class="st-row" {_in(t[f'step{i}'], 'rise')}>
        <div class="chip filled {ACCENTS[i % 5]} st-num">{i + 1}</div>
        <div class="card st-card">
          {_icon(icons, item.get('icon'), 96) if item.get('icon') else ''}
          <div class="body st-text" data-fit="30">{esc(item.get('text'))}</div>
        </div>
      </div>""" for i, item in enumerate(items))
    return f"""
    <style>
      .st-wrap {{ position: relative; display: flex; flex-direction: column; gap: 36px; }}
      .st-row {{ display: flex; align-items: center; gap: 30px; height: {step_h}px; position: relative; z-index: 1; }}
      .st-num {{ width: 120px; height: 120px; font-size: 64px; flex: none; }}
      .st-card {{ flex: 1; height: 100%; display: flex; align-items: center; gap: 26px; padding: 0 36px; }}
      .st-text {{ flex: 1; height: {step_h - 30}px; display: flex; align-items: center; color: var(--on-card); font-size: 54px; }}
      .st-line {{ position: absolute; left: 60px; top: 60px; width: 10px; height: calc(100% - 120px); }}
    </style>
    <div class="title" style="height:170px" data-fit="40" {_in(t['title'])}>{esc(s.get('title'))}</div>
    <div class="st-wrap">
      <svg class="st-line" viewBox="0 0 10 100" preserveAspectRatio="none"><path d="M 5 0 V 100"
           stroke="var(--soft)" stroke-width="10" vector-effect="non-scaling-stroke"
           {_in(t['step0'], 'draw', max(0.6, t[f'step{n - 1}'] - t['step0']))}/></svg>
      {rows}
    </div>
    """


def timeline(s, t, icons):
    events = s["events"][:5]
    n = len(events)
    row_h = min(190, (900 - 30 * (n - 1)) // n)
    rows = "".join(f"""
      <div class="tl-row" {_in(t[f'event{i}'], 'slide-right')}>
        <div class="chip filled {ACCENTS[i % 5]} tl-when" data-fit="26">{esc(e.get('when'))}</div>
        <div class="tl-dot" style="background: var(--{ACCENTS[i % 5]})"></div>
        <div class="card tl-card"><div class="body tl-text" data-fit="28">{esc(e.get('text'))}</div></div>
      </div>""" for i, e in enumerate(events))
    return f"""
    <style>
      .tl-wrap {{ position: relative; display: flex; flex-direction: column; gap: 30px; }}
      .tl-row {{ display: grid; grid-template-columns: 270px 60px 1fr; align-items: center; height: {row_h}px; }}
      .tl-when {{ height: 96px; font-size: 44px; padding: 0 20px; white-space: nowrap; overflow: hidden; }}
      .tl-dot {{ width: 44px; height: 44px; border-radius: 50%; border: 6px solid var(--ink); justify-self: center; z-index: 1; }}
      .tl-card {{ height: 100%; padding: 0 30px; display: flex; align-items: center; }}
      .tl-text {{ height: {row_h - 30}px; display: flex; align-items: center; color: var(--on-card); font-size: 50px; }}
      .tl-line {{ position: absolute; left: 294px; top: 20px; width: 12px; height: calc(100% - 40px); }}
    </style>
    <div class="title" style="height:170px" data-fit="40" {_in(t['title'])}>{esc(s.get('title'))}</div>
    <div class="tl-wrap">
      <svg class="tl-line" viewBox="0 0 10 100" preserveAspectRatio="none"><path d="M 5 0 V 100"
           stroke="var(--soft)" stroke-width="12" vector-effect="non-scaling-stroke"
           {_in(t['event0'], 'draw', max(0.6, t[f'event{n - 1}'] - t['event0']))}/></svg>
      {rows}
    </div>
    """


def bars(s, t, icons):
    items = s["bars"][:6]
    top = max(float(b.get("value") or 0) for b in items) or 1
    hi = s.get("highlight")
    unit = s.get("unit") or ""
    n = len(items)
    bar_h = min(150, (820 - 28 * (n - 1)) // n)
    rows = []
    for i, b in enumerate(items):
        value = float(b.get("value") or 0)
        accent = "a1" if hi is not None and int(hi) == i else ACCENTS[(i + 1) % 5]
        at = t["bars"] + i * 0.25
        dec = 0 if value == int(value) else 1
        rows.append(f"""
        <div class="bar-row">
          <div class="bar-label" data-fit="26" {_in(at, 'fade')}>{esc(b.get('label'))}</div>
          <div class="bar-track">
            <div class="bar-fill filled {accent}" style="width:{max(4, 100 * value / top):.1f}%" {_in(at, 'grow', 0.9)}></div>
          </div>
          <div class="bar-value" {_in(at + 0.4, 'fade')} data-count-to="{value}" data-decimals="{dec}"
               data-suffix="{esc(unit)}" data-count-dur="0.9"></div>
        </div>""")
    return f"""
    <style>
      .bar-row {{ display: grid; grid-template-columns: 250px 1fr 190px; gap: 22px; align-items: center; height: {bar_h}px; }}
      .bar-label {{ font-size: 44px; text-align: right; height: {bar_h}px; display: flex; align-items: center;
                   justify-content: flex-end; line-height: 1.05; }}
      .bar-track {{ height: {int(bar_h * 0.72)}px; }}
      .bar-fill {{ height: 100%; border-radius: 18px; border: 5px solid var(--ink); }}
      .bar-value {{ font-family: var(--display); font-weight: var(--dw); font-size: 54px; white-space: nowrap; }}
    </style>
    <div class="title" style="height:170px" data-fit="40" {_in(t['title'])}>{esc(s.get('title'))}</div>
    <div class="card" style="padding: 50px 40px; display: flex; flex-direction: column; gap: 28px;" {_in(t['bars'], 'rise')}>
      {''.join(rows)}
    </div>
    """


def myth_fact(s, t, icons):
    return f"""
    <style>
      .mf-card {{ padding: 44px 50px 50px; display: flex; flex-direction: column; gap: 26px; }}
      .mf-tag {{ align-self: flex-start; font-size: 46px; padding: 12px 36px; letter-spacing: .08em; }}
      .mf-text {{ height: 260px; display: flex; align-items: center; font-size: 60px; color: var(--on-card); }}
      .mf-strike {{ position: absolute; left: 30px; right: 30px; top: 58%; height: 14px; background: var(--a1);
                   border-radius: 7px; }}
      .mf-myth .mf-text {{ opacity: .85; }}
    </style>
    <div class="card mf-card mf-myth" {_in(t['myth'], 'rise')}>
      <div class="chip filled a1 mf-tag">{esc(s.get('myth_label') or 'MYTH')}</div>
      <div class="body mf-text" data-fit="30">{esc(s.get('myth'))}</div>
      <div class="mf-strike" {_in(t['strike'], 'strike', 0.5)}></div>
    </div>
    <div class="card mf-card" {_in(t['fact'], 'pop')}>
      <div class="chip filled a4 mf-tag">{esc(s.get('fact_label') or 'FACT')}</div>
      <div class="body mf-text" data-fit="30" style="font-family: var(--display); font-weight: var(--dw)">{esc(s.get('fact'))}</div>
    </div>
    """


def definition(s, t, icons):
    example = s.get("example")
    return f"""
    <style>
      .df-term {{ font-size: 150px; width: 1000px; height: 200px; white-space: nowrap; overflow: hidden; }}
      .df-kind {{ align-self: center; font-size: 42px; padding: 12px 36px; }}
      .df-def {{ padding: 44px 50px; }}
      .df-def .body {{ height: 330px; display: flex; align-items: center; font-size: 58px; color: var(--on-card); }}
      .df-ex {{ padding: 34px 50px; }}
      .df-ex .body {{ height: 170px; display: flex; align-items: center; font-style: italic; font-size: 48px; }}
    </style>
    <div class="hero df-term glow" data-fit="70" {_in(t['term'], 'pop')}>{esc(s.get('term'))}</div>
    {f'<div class="chip filled a2 df-kind" {_in(t["term"] + 0.3, "fade")}>{esc(s.get("kind"))}</div>' if s.get('kind') else ''}
    <div class="card df-def" {_in(t['definition'], 'rise')}><div class="body" data-fit="30">{esc(s.get('definition'))}</div></div>
    {f'<div class="card filled a3 df-ex" {_in(t["example"], "rise")}><div class="body" data-fit="28">{esc(example)}</div></div>' if example else ''}
    """


def quote(s, t, icons):
    return f"""
    <style>
      .qt-mark {{ font-family: var(--display); font-size: 300px; line-height: .6; height: 180px; color: var(--a1); text-align: center; }}
      .qt-card {{ padding: 50px 50px 60px; }}
      .qt-text {{ height: 640px; display: flex; align-items: center; justify-content: center; text-align: center;
                 font-family: var(--display); font-weight: var(--dw); font-size: 92px; line-height: 1.12;
                 color: var(--on-card); }}
      .qt-who {{ font-size: 48px; text-align: center; color: var(--soft); height: 70px; }}
    </style>
    <div class="card qt-card" {_in(t['text'], 'rise')}>
      <div class="qt-mark">“</div>
      <div class="qt-text" data-fit="36" {_in(t['text'] + 0.2, 'wipe', 1.4)}>{esc(s.get('text'))}</div>
    </div>
    <div class="qt-who" data-fit="28" {_in(t['who'], 'rise')}>{esc(s.get('who'))}</div>
    """


def equation(s, t, icons):
    lines = s["lines"][:4]
    note = s.get("note")
    rows = "".join(f"""
      <div class="tex eq-line glow" data-fit="50" {_in(t[f'line{i}'], 'wipe', 0.9)}>{tex.to_html(l.get('tex'))}</div>"""
                   for i, l in enumerate(lines))
    return f"""
    <style>{tex.CSS}
      .eq-card {{ padding: 60px 40px; display: flex; flex-direction: column; gap: 50px; align-items: center; }}
      .eq-line {{ font-size: 120px; width: 920px; height: 190px; display: flex; align-items: center;
                 justify-content: center; color: var(--on-card); overflow: hidden; }}
      .eq-note {{ padding: 34px 44px; }}
      .eq-note .body {{ height: 160px; display: flex; align-items: center; justify-content: center; text-align: center; font-size: 52px; }}
    </style>
    <div class="title" style="height:150px" data-fit="40" {_in(t['title'])}>{esc(s.get('title'))}</div>
    <div class="card eq-card" {_in(t['line0'], 'rise')}>{rows}</div>
    {f'<div class="card filled a2 eq-note" {_in(t["note"], "pop")}><div class="body" data-fit="28">{esc(note)}</div></div>' if note else ''}
    """


def one_in_n(s, t, icons):
    n = max(2, min(50, int(s.get("n") or 10)))
    k = max(1, min(n, int(s.get("k") or 1)))
    cols = 5 if n <= 10 else (8 if n <= 40 else 10)
    size = min(150, int(900 / cols) - 18)
    cells = []
    for i in range(n):
        at = t["grid"] + (i / n) * 0.8
        marked = i < k
        ring = f"<div class='oin-ring' {_in(t['highlight'] + i * 0.08, 'pop')}></div>" if marked else ""
        cells.append(f"<div class='oin-cell {'oin-on' if marked else ''}' {_in(at, 'pop', 0.35)}>"
                     f"{_icon(icons, s.get('icon'), size)}{ring}</div>")
    return f"""
    <style>
      .oin-big {{ font-size: 170px; height: 210px; white-space: nowrap; }}
      .oin-grid {{ display: grid; grid-template-columns: repeat({cols}, {size}px); gap: 18px; justify-content: center; }}
      .oin-cell {{ position: relative; width: {size}px; height: {size}px; display: flex; align-items: center;
                  justify-content: center; filter: grayscale(1); opacity: .45; }}
      .oin-cell.oin-on {{ filter: none; }}
      .oin-cell.oin-on.is-on {{ opacity: 1; }}
      .oin-ring {{ position: absolute; inset: -8px; border: 8px solid var(--a1); border-radius: 50%; }}
      .oin-cap {{ padding: 34px 44px; }}
      .oin-cap .body {{ height: 170px; display: flex; align-items: center; justify-content: center;
                       text-align: center; font-size: 54px; color: var(--on-card); }}
    </style>
    <div class="hero oin-big a1 accent-text glow" data-fit="80" {_in(t['highlight'], 'pop')}>{k} in {n}</div>
    <div class="oin-grid">{''.join(cells)}</div>
    <div class="card oin-cap" {_in(t['caption'], 'rise')}><div class="body" data-fit="28">{esc(s.get('caption'))}</div></div>
    """


def scale(s, t, icons):
    items = s["items"][:4]
    top = max(float(i.get("value") or 0) for i in items) or 1
    biggest = 420 if len(items) <= 2 else 300
    cells = []
    for i, it in enumerate(items):
        d = max(70, int(biggest * math.sqrt(float(it.get("value") or 0) / top)))
        cells.append(f"""
        <div class="sc-cell" {_in(t[f'item{i}'], 'pop', 0.6)}>
          <div class="sc-circle filled {ACCENTS[i % 5]}" style="width:{d}px;height:{d}px">
            {_icon(icons, it.get('icon'), int(d * 0.55)) if it.get('icon') else ''}</div>
          <div class="sc-label" data-fit="26">{esc(it.get('label'))}</div>
        </div>""")
    return f"""
    <style>
      .sc-row {{ display: flex; align-items: flex-end; justify-content: center; gap: 40px; height: 640px; }}
      .sc-cell {{ display: flex; flex-direction: column; align-items: center; gap: 22px; }}
      .sc-circle {{ border-radius: 50%; border: 6px solid var(--ink); display: flex; align-items: center; justify-content: center; }}
      .sc-label {{ font-family: var(--display); font-weight: var(--dw); font-size: 46px; width: 260px;
                  height: 120px; text-align: center; }}
      .sc-cap {{ padding: 30px 44px; }}
      .sc-cap .body {{ height: 150px; display: flex; align-items: center; justify-content: center; text-align: center;
                      font-size: 52px; color: var(--on-card); }}
    </style>
    <div class="title" style="height:170px" data-fit="40" {_in(t['title'])}>{esc(s.get('title'))}</div>
    <div class="sc-row">{''.join(cells)}</div>
    {f'<div class="card sc-cap" {_in(t["caption"], "rise")}><div class="body" data-fit="28">{esc(s["caption"])}</div></div>' if s.get('caption') else ''}
    """


# --- the catalogue -----------------------------------------------------------------

def _list_beats(key, prefix):
    return lambda s: [prefix + str(i) for i in range(len(s.get(key) or []))]


TEMPLATES = {
    "big_number": {
        "use": "One striking number or statistic the words say.",
        "slots": "kicker (2-5 words above it), value (the number), prefix/suffix (like '£', '%', ' years'), "
                 "decimals, count_from (default 0), caption (one line, <=10 words), icon (optional)",
        "required": ["value", "caption"], "beats": lambda s: ["kicker", "value", "caption"],
        "sounds": {"value": "pop"}, "build": big_number},
    "versus": {
        "use": "Two things compared: then vs now, this vs that, who does vs who doesn't.",
        "slots": "title (<=6 words), left {label <=3 words, value <=4 words, icon}, right {same}, "
                 "verdict (optional, <=8 words)",
        "required": ["left", "right"], "beats": lambda s: ["title", "left", "right"] + (["verdict"] if s.get("verdict") else []),
        "sounds": {"verdict": "chime", "right": "pop"}, "build": versus},
    "list": {
        "use": "Two to five parallel points, reasons, signs or examples.",
        "slots": "title (<=6 words), items [{text <=7 words, icon}] 2-5, highlight (optional index of the one that matters most)",
        "required": ["items"], "beats": lambda s: ["title"] + _list_beats("items", "item")(s),
        "sounds": {}, "build": items_list},
    "steps": {
        "use": "A process in order: how something happens or how to do it.",
        "slots": "title (<=6 words), steps [{text <=7 words, icon (optional)}] 2-5",
        "required": ["steps"], "beats": lambda s: ["title"] + _list_beats("steps", "step")(s),
        "sounds": {}, "build": steps},
    "timeline": {
        "use": "Events in time: history, a life, stages over years.",
        "slots": "title (<=6 words), events [{when (e.g. '1609', 'Age 4'), text <=7 words}] 2-5",
        "required": ["events"], "beats": lambda s: ["title"] + _list_beats("events", "event")(s),
        "sounds": {}, "build": timeline},
    "bars": {
        "use": "Several quantities compared as numbers the words give.",
        "slots": "title (<=6 words), unit (e.g. '%'), bars [{label <=3 words, value}] 2-6, highlight (optional index)",
        "required": ["bars"], "beats": lambda s: ["title", "bars"],
        "sounds": {"bars": "whoosh"}, "build": bars},
    "myth_fact": {
        "use": "A common belief that is wrong, and what's true.",
        "slots": "myth (<=12 words), fact (<=12 words), myth_label/fact_label (optional, default MYTH/FACT)",
        "required": ["myth", "fact"], "beats": lambda s: ["myth", "strike", "fact"],
        "sounds": {"strike": "whoosh", "fact": "chime"}, "build": myth_fact},
    "definition": {
        "use": "A term the viewer needs, defined plainly.",
        "slots": "term (1-3 words), kind (optional: 'psychology', 'noun'...), definition (<=16 words), example (optional, <=12 words)",
        "required": ["term", "definition"], "beats": lambda s: ["term", "definition"] + (["example"] if s.get("example") else []),
        "sounds": {"term": "pop"}, "build": definition},
    "quote": {
        "use": "Someone's actual words, quoted exactly.",
        "slots": "text (the quote, <=30 words), who (attribution)",
        "required": ["text", "who"], "beats": lambda s: ["text", "who"],
        "sounds": {}, "build": quote},
    "equation": {
        "use": "An equation or calculation built up line by line.",
        "slots": "title (optional), lines [{tex}] 1-4 in the TeX subset (\\frac{a}{b}, \\sqrt{x}, x^{2}, "
                 "\\color{accent1}{a^2}, \\times, \\pi...), note (optional, <=10 words)",
        "required": ["lines"], "beats": lambda s: ["title"] + _list_beats("lines", "line")(s) + (["note"] if s.get("note") else []),
        "sounds": {"note": "chime"}, "build": equation},
    "one_in_n": {
        "use": "A proportion shown as people or things: '1 in 4', '3 out of 10'.",
        "slots": "n (total, 2-50), k (how many), icon (e.g. 'person', 'dog'), caption (<=12 words)",
        "required": ["n", "k", "icon", "caption"], "beats": lambda s: ["grid", "highlight", "caption"],
        "sounds": {"highlight": "chime"}, "build": one_in_n},
    "scale": {
        "use": "Sizes compared: how big one thing is next to another.",
        "slots": "title (<=6 words), items [{label <=3 words, value (relative size), icon}] 2-4, caption (optional)",
        "required": ["items"], "beats": lambda s: ["title"] + _list_beats("items", "item")(s) + (["caption"] if s.get("caption") else []),
        "sounds": {}, "build": scale},
}


def catalogue() -> str:
    """The templates as the model sees them."""
    return "\n".join(f"- {name}: {spec['use']} Slots: {spec['slots']}."
                     for name, spec in TEMPLATES.items())
