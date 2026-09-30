"""
Diagrams the compositor draws itself (decision 054): typeset formulas and
bullet points, matrices, bar charts, number lines, plots of curves, and
graphs of nodes and arrows. They cost nothing to make (no picture model),
are exact where a drawn picture can't be (a number line's ticks, a curve,
a formula), and take the style's ink: crisp on a plain background, a
marker's wobble on a whiteboard, chalk on a chalkboard.

The storyboard describes a diagram in plain terms (`schema`); `settle`
makes that safe (bounded sizes, real numbers, curves that parse); `build`
turns it into primitives placed in the beat's diagram box:

    stroke  a line or curve drawn on, optionally with arrowheads
    bar     a bar that grows from its baseline
    dot     a point that pops in
    area    a filled shape that fades in
    math    typeset maths (compositor.mathtext), written left to right
    text    plain words or numbers in the label face

Every primitive has a `pid` saying what it is ("the bar labelled X_1").
When the next beat continues the same diagram (the same `id`), the script
keeps whatever is unchanged on screen and moves what changed (a bar to its
new height, a point along the line) instead of drawing it again: the way
a maths animation builds an idea up rather than cutting between slides.
"""

from __future__ import annotations

import math

from pipeline.animation import frame as frames
from pipeline.animation.compositor import expr, mathtext

KINDS = ("formula", "bullets", "matrix", "chart", "number_line", "plot", "graph")
ARRANGEMENTS = ("circle", "row", "column", "tree")
# Type sizes (the height of a capital, in pixels), by role and whether the
# frame is vertical: sized to read on a phone.
SIZES = {"formula": {True: 64, False: 62}, "bullet": {True: 50, False: 50},
         "label": {True: 42, False: 40}, "tick": {True: 34, False: 34},
         "node": {True: 42, False: 42}}
MAX_LINES = 5
MAX_BULLETS = 6
MAX_MATRIX = 10
MAX_BARS = 8
MAX_POINTS = 8
MAX_JUMPS = 6
MAX_CURVES = 3
MAX_NODES = 10
MAX_EDGES = 16
MAX_EDGE_LABELS = 5
TEXT = 90                      # characters in a line or a label

ROLES = ("line", "bar", "point", "jump", "curve", "node", "edge")

GUIDE = {
    "formula": "formula: one to five lines of maths, centred and written in one after another: each "
               "an element with role line, its text the line (maths between $...$ in LaTeX, words "
               "outside it, e.g. \"Corr$(X,Y) = \frac{3}{5}$\"). Continue it next beat with the same id "
               "and more lines to build a derivation up line by line.",
    "bullets": "bullets: two to six short points, left-aligned: elements with role line, each written "
               "as it's said (maths allowed between $...$).",
    "matrix": "matrix: rows of entries (up to 10 by 10), in brackets.",
    "chart": "chart: a bar chart on arrowed axes: elements with role bar, text its label and a its "
             "value (may be negative). Continue it next beat with the same id and new values and "
             "the bars move to them.",
    "number_line": "number_line: range [min, max]; elements with role point (a where, text its "
                   "label) and role jump (an arc from a to b, text its label: adding, stepping, a "
                   "random walk); shade an interval [from, to], or [0, 0]. Same id next beat and "
                   "points move to their new places.",
    "plot": "plot: axes over range [min, max] of x, y_range [min, max] ([0, 0] to fit the curves); "
            "elements with role curve (ref the expression in x using + - * / ^, sqrt, exp, log, "
            "sin, cos, abs, pi, e, normal(x, mean, sd); text its label) and role point (a its x, b "
            "its y, text its label); shade the area under the first curve between [from, to], or "
            "[0, 0].",
    "graph": "graph: elements with role node (ref its id, text its label, up to 10) and role edge "
             "(ref the node it leaves, to the node it reaches, text its label); arrangement circle, "
             "row, column or tree (from the first node); directed for arrows. Flows, networks, "
             "trees, states, cause and effect.",
}


def schema() -> dict:
    """One diagram in a beat; kind "" means none. Every part of every kind
    is one shape of element (its role says what it is), which keeps the
    storyboard's schema small enough to compile."""
    num = {"type": "number"}
    pair = {"type": "array", "items": num}
    element = {"type": "object", "properties": {
        "role": {"type": "string", "enum": list(ROLES)},
        "text": {"type": "string"}, "ref": {"type": "string"}, "to": {"type": "string"},
        "a": num, "b": num, "on_word": {"type": "integer"}},
        "required": ["role", "text", "ref", "to", "a", "b", "on_word"],
        "additionalProperties": False}
    return {"type": "object", "properties": {
        "kind": {"type": "string", "enum": [""] + list(KINDS)},
        "id": {"type": "string"},
        "elements": {"type": "array", "items": element},
        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
        "range": pair, "y_range": pair, "shade": pair,
        "arrangement": {"type": "string", "enum": list(ARRANGEMENTS)},
        "directed": {"type": "boolean"}},
        "required": ["kind", "id", "elements", "rows", "range", "y_range", "shade", "arrangement",
                     "directed"],
        "additionalProperties": False}


def expand(raw: dict) -> dict:
    """The storyboard's elements as each kind's own parts (lines, bars,
    points, jumps, curves, nodes, edges)."""
    if not isinstance(raw, dict) or "elements" not in raw:
        return raw
    out = {k: v for k, v in raw.items() if k != "elements"}
    parts = {k: [] for k in ("lines", "bars", "points", "jumps", "curves", "nodes", "edges")}
    for e in raw.get("elements") or []:
        if not isinstance(e, dict):
            continue
        role, text, word = e.get("role"), e.get("text"), e.get("on_word")
        if role == "line":
            parts["lines"].append({"text": text, "on_word": word})
        elif role == "bar":
            parts["bars"].append({"label": text, "value": e.get("a"), "on_word": word})
        elif role == "point":
            parts["points"].append({"at": e.get("a"), "y": e.get("b"), "label": text,
                                    "on_word": word})
        elif role == "jump":
            parts["jumps"].append({"from": e.get("a"), "to": e.get("b"), "label": text,
                                   "on_word": word})
        elif role == "curve":
            parts["curves"].append({"expr": e.get("ref"), "label": text, "on_word": word})
        elif role == "node":
            parts["nodes"].append({"id": e.get("ref") or text, "label": text})
        elif role == "edge":
            parts["edges"].append({"from": e.get("ref"), "to": e.get("to"), "label": text,
                                   "on_word": word})
    out.update(parts)
    return out


# --- settle: the storyboard's diagram made safe -------------------------------------

def _text(v, limit: int = TEXT) -> str:
    return " ".join(str(v or "").split())[:limit]


def _num(v, default=0.0) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) and abs(v) < 1e7 else default


def _word(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else -1


def _pair(v, default=(0.0, 0.0)) -> tuple:
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return _num(v[0], default[0]), _num(v[1], default[1])
    return default


def settle(raw: dict, allowed=KINDS) -> dict:
    """The diagram, safe to draw, or None if there isn't one (or it can't
    be drawn: a chart without bars, a plot whose curves don't parse)."""
    raw = expand(raw)
    if not isinstance(raw, dict) or raw.get("kind") not in allowed:
        return None
    kind = raw["kind"]
    d = {"kind": kind, "id": _text(raw.get("id"), 40) or kind}
    if kind in ("formula", "bullets"):
        limit = MAX_LINES if kind == "formula" else MAX_BULLETS
        d["lines"] = [{"text": _text(l.get("text")), "on_word": _word(l.get("on_word"))}
                      for l in (raw.get("lines") or []) if isinstance(l, dict)
                      and _text(l.get("text"))][:limit]
        return d if d["lines"] else None
    if kind == "matrix":
        rows = [[_text(c, 12) for c in r[:MAX_MATRIX]] for r in (raw.get("rows") or [])
                if isinstance(r, list) and r][:MAX_MATRIX]
        if not rows:
            return None
        cols = max(len(r) for r in rows)
        d["rows"] = [r + [""] * (cols - len(r)) for r in rows]
        return d
    if kind == "chart":
        d["bars"] = [{"label": _text(b.get("label"), 24), "value": _num(b.get("value")),
                      "on_word": _word(b.get("on_word"))}
                     for b in (raw.get("bars") or []) if isinstance(b, dict)][:MAX_BARS]
        return d if d["bars"] else None
    if kind == "number_line":
        lo, hi = _pair(raw.get("range"), (0.0, 10.0))
        points = [{"at": _num(p.get("at")), "label": _text(p.get("label"), 24),
                   "on_word": _word(p.get("on_word"))}
                  for p in (raw.get("points") or []) if isinstance(p, dict)][:MAX_POINTS]
        jumps = [{"from": _num(j.get("from")), "to": _num(j.get("to")),
                  "label": _text(j.get("label"), 24), "on_word": _word(j.get("on_word"))}
                 for j in (raw.get("jumps") or []) if isinstance(j, dict)][:MAX_JUMPS]
        values = [p["at"] for p in points] + [v for j in jumps for v in (j["from"], j["to"])]
        if hi <= lo:
            lo, hi = (min(values), max(values)) if values else (0.0, 10.0)
            if hi <= lo:
                lo, hi = lo - 5, lo + 5
        # Everything named must be on the line.
        lo, hi = min([lo] + values), max([hi] + values)
        shade = _pair(raw.get("shade"))
        d.update(range=(lo, hi), points=points, jumps=jumps,
                 shade=tuple(sorted(shade)) if shade[0] != shade[1] else None)
        return d
    if kind == "plot":
        lo, hi = _pair(raw.get("range"), (-5.0, 5.0))
        if hi <= lo:
            lo, hi = -5.0, 5.0
        curves = []
        for c in (raw.get("curves") or [])[:MAX_CURVES]:
            if not isinstance(c, dict):
                continue
            try:
                expr.parse(c.get("expr"))
            except expr.BadExpression:
                continue
            curves.append({"expr": _text(c.get("expr"), expr.MAX_LENGTH),
                           "label": _text(c.get("label"), 24), "on_word": _word(c.get("on_word"))})
        points = [{"at": _num(p.get("at")), "y": _num(p.get("y")), "label": _text(p.get("label"), 24),
                   "on_word": _word(p.get("on_word"))}
                  for p in (raw.get("points") or []) if isinstance(p, dict)][:MAX_POINTS]
        if not curves and not points:
            return None
        ylo, yhi = _pair(raw.get("y_range"))
        shade = _pair(raw.get("shade"))
        d.update(range=(lo, hi), y_range=(ylo, yhi) if yhi > ylo else None, curves=curves,
                 points=points, shade=tuple(sorted(shade)) if shade[0] != shade[1] and curves else None)
        return d
    if kind == "graph":
        nodes, seen = [], set()
        for n in raw.get("nodes") or []:
            nid = _text((n or {}).get("id"), 24) if isinstance(n, dict) else ""
            if nid and nid not in seen and len(nodes) < MAX_NODES:
                seen.add(nid)
                nodes.append({"id": nid, "label": _text(n.get("label"), 24)})
        edges = [{"from": _text(e.get("from"), 24), "to": _text(e.get("to"), 24),
                  "label": _text(e.get("label"), 24), "on_word": _word(e.get("on_word"))}
                 for e in (raw.get("edges") or []) if isinstance(e, dict)]
        edges = [e for e in edges if e["from"] in seen and e["to"] in seen
                 and e["from"] != e["to"]][:MAX_EDGES]
        if len(nodes) < 2:
            return None
        d.update(nodes=nodes, edges=edges, directed=bool(raw.get("directed")),
                 arrangement=raw.get("arrangement") if raw.get("arrangement") in ARRANGEMENTS
                 else "circle")
        return d
    return None


# --- build: the diagram as primitives in its box ---------------------------------------

class _Out:
    """Primitives being made, and the typeset pictures they need."""

    def __init__(self, ink: dict, frame):
        self.prims, self.assets, self.ink, self.frame = [], {}, ink, frames.get(frame)
        self.math_face = ink.get("math_face", True)
        self.face = ink.get("hand") or ""          # a handwritten style writes its maths by hand

    def typeset(self, text, color, size):
        return mathtext.render(text, color, size, self.face)

    def add(self, pid, kind, order=0, word=-1, **data):
        self.prims.append({"pid": pid, "kind": kind, "order": order, "on_word": word, **data})
        return self.prims[-1]

    def words(self, pid, text, x, y, size, order=0, word=-1, align="middle", color=None,
              maths=False):
        """Text as typeset maths (when it has any, or the style sets words
        in Computer Modern) or as words in the style's label face."""
        color = color or self.ink["ink"]
        text = str(text)
        if maths:
            text = mathtext.as_math(text)
        if mathtext.is_math(text) or (self.math_face and text):
            path, w, h = self.typeset(text, color, size)
            name = mathtext.asset_name(path)
            self.assets[name] = path
            anchor = {"start": x + w / 2, "end": x - w / 2}.get(align, x)
            return self.add(pid, "math", order, word, src=name, x=anchor, y=y, w=w, h=h)
        return self.add(pid, "text", order, word, text=text, x=x, y=y, size=size * 1.45,
                        align=align, color=color)


def _series(ink: dict, i: int) -> str:
    colours = ink.get("series") or [ink["accent"]]
    return colours[i % len(colours)]


def build(diagram: dict, box, ink: dict, frame=None) -> tuple:
    """(primitives, assets) for a settled diagram in `box` (left, top,
    right, bottom). `ink`: the theme's diagram colours ({"ink", "accent",
    "series", "line", "math_face"})."""
    out = _Out(ink, frame)
    x0, y0, x1, y1 = box
    {"formula": _formula, "bullets": _bullets, "matrix": _matrix, "chart": _chart,
     "number_line": _number_line, "plot": _plot, "graph": _graph}[diagram["kind"]](
        diagram, (x0, y0, x1, y1), out)
    return out.prims, out.assets


def _scale_size(out, texts, size, width, maths=False):
    """The largest size up to `size` at which the widest line fits `width`."""
    widest = 0
    for t in texts:
        if mathtext.is_math(t) or out.math_face or maths:
            _, w, _ = out.typeset(mathtext.as_math(t) if maths else t, out.ink["ink"], size)
        else:
            w = len(t) * size * 0.72
        widest = max(widest, w)
    return size if widest <= width else max(18, size * width / widest)


def _display(text: str) -> str:
    """A formula set on its own line reads at display size: \\frac as
    \\dfrac, so fractions aren't squeezed to half height."""
    return text.replace("\\frac", "\\dfrac") if "\\dfrac" not in text else text


def _formula(d, box, out):
    x0, y0, x1, y1 = box
    base = SIZES["formula"][out.frame.vertical]
    d = dict(d, lines=[dict(l, text=_display(l["text"])) for l in d["lines"]])
    texts = [l["text"] for l in d["lines"]]
    size = _scale_size(out, texts, base, (x1 - x0) * 0.94)
    if size < base * 0.75:
        # A long line of words wraps (maths stays whole) rather than
        # shrinking out of reading.
        lines = []
        for l in d["lines"]:
            parts = _halves(l["text"]) if len(l["text"]) > 24 else [l["text"]]
            lines += [dict(l, text=part, on_word=l["on_word"] if k == 0 else -1, _part=k)
                      for k, part in enumerate(parts)]
        d = dict(d, lines=lines)
        texts = [l["text"] for l in lines]
        size = _scale_size(out, texts, base, (x1 - x0) * 0.94)

    def measure(size):
        heights = [out.typeset(t, out.ink["ink"], size)[2] if mathtext.is_math(t) or out.math_face
                   else size * 1.6 for t in texts]
        return heights, sum(heights) + size * 0.9 * (len(heights) - 1)

    heights, total = measure(size)
    if total > (y1 - y0):                  # a long derivation: smaller, never over its box
        size = max(18, size * (y1 - y0) / total * 0.97)
        heights, total = measure(size)
    gap = size * 0.9
    y = (y0 + y1) / 2 - total / 2
    for i, (l, h) in enumerate(zip(d["lines"], heights)):
        out.words(f"{d['id']}:line:{l['text']}", l["text"], (x0 + x1) / 2, y + h / 2, size,
                  order=i, word=l["on_word"])
        y += h + gap


def _halves(text: str) -> list:
    """A line split in two at the space nearest its middle (never inside
    $...$ maths), or the line alone if it can't be."""
    spaces = [i for i, c in enumerate(text) if c == " " and text[:i].count("$") % 2 == 0]
    if not spaces:
        return [text]
    cut = min(spaces, key=lambda i: abs(i - len(text) / 2))
    return [text[:cut], text[cut + 1:]]


def _bullets(d, box, out):
    x0, y0, x1, y1 = box
    base = SIZES["bullet"][out.frame.vertical]
    indent = base * 1.6
    width = (x1 - x0) - indent - 20
    rows = [[l["text"]] for l in d["lines"]]
    size = _scale_size(out, [r[0] for r in rows], base, width)
    if size < base * 0.8:                  # a long point wraps rather than shrinking to nothing
        rows = [_halves(r[0]) for r in rows]
        size = _scale_size(out, [t for r in rows for t in r], base, width)
    row_h = size * 1.75
    gap = size * 1.3
    total = sum(len(r) for r in rows) * row_h + gap * (len(rows) - 1)
    if total > y1 - y0:
        scale = (y1 - y0) / total
        size, row_h, gap = size * scale, row_h * scale, gap * scale
    y = (y0 + y1) / 2 - (sum(len(r) for r in rows) * row_h + gap * (len(rows) - 1)) / 2
    left = x0 + 20
    for i, (l, parts) in enumerate(zip(d["lines"], rows)):
        first = y + row_h / 2
        out.add(f"{d['id']}:dot:{i}", "dot", i, l["on_word"], x=left + size * 0.4, y=first,
                r=max(5, size * 0.16), color=out.ink["ink"])
        for k, part in enumerate(parts):
            p = out.words(f"{d['id']}:bullet:{l['text']}:{k}", part, left + indent,
                          first + k * row_h, size, order=i, word=l["on_word"], align="start")
            p["stagger"] = round(0.35 * k, 3)
        y += len(parts) * row_h + gap


def _matrix(d, box, out):
    x0, y0, x1, y1 = box
    rows = d["rows"]
    nr, nc = len(rows), len(rows[0])
    cell_w = min((x1 - x0) * 0.86 / nc, 130)
    cell_h = min((y1 - y0) * 0.8 / nr, cell_w * 0.78, 96)
    size = min(cell_h * 0.42, cell_w * 0.36)
    w, h = cell_w * nc, cell_h * nr
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left, top = cx - w / 2, cy - h / 2
    lip, pad = max(14, size * 0.5), size * 0.5
    lw = out.ink.get("line", 4)
    for side, sx, dx in (("l", left - pad, 1), ("r", left + w + pad, -1)):
        out.add(f"{d['id']}:bracket:{side}:{nr}x{nc}", "stroke", 0,
                points=[[sx + dx * lip, top - pad], [sx, top - pad], [sx, top + h + pad],
                        [sx + dx * lip, top + h + pad]], width=lw * 0.8, color=out.ink["ink"])
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            if not v:
                continue
            p = out.words(f"{d['id']}:cell:{r}:{c}:{v}", v, left + (c + 0.5) * cell_w,
                          top + (r + 0.5) * cell_h, size, order=1, maths=True)
            p["stagger"] = round(0.03 * (r * nc + c) / max(1, nr * nc / 20), 3)


def _arrow_axes(out, pid, x_from, x_to, y_axis_x, y_from, y_to, zero_y, order=0,
                y_both=False, x_both=False):
    lw = out.ink.get("line", 4)
    out.add(f"{pid}:x", "stroke", order, points=[[x_from, zero_y], [x_to, zero_y]], width=lw,
            color=out.ink["ink"], arrow="both" if x_both else "end", solid_head=True)
    out.add(f"{pid}:y", "stroke", order, points=[[y_axis_x, y_from], [y_axis_x, y_to]], width=lw,
            color=out.ink["ink"], arrow="both" if y_both else "end", solid_head=True)


def _chart(d, box, out):
    x0, y0, x1, y1 = box
    bars = d["bars"]
    values = [b["value"] for b in bars]
    top_v, bottom_v = max(0.0, max(values)), min(0.0, min(values))
    if d.get("scale"):                   # continued over beats: one scale for all of them
        bottom_v, top_v = min(bottom_v, d["scale"][0]), max(top_v, d["scale"][1])
    span = (top_v - bottom_v) or 1.0
    label_room = 70
    inner_top, inner_bottom = y0 + label_room, y1 - label_room
    zero_y = inner_top + (inner_bottom - inner_top) * top_v / span
    unit = (inner_bottom - inner_top) / span
    axis_x = x0 + 30
    width = (x1 - axis_x - 90)
    slot = width / len(bars)
    bar_w = min(slot * 0.55, 150)
    _arrow_axes(out, f"{d['id']}:axes:{round(zero_y)}", axis_x - 10, x1 - 10, axis_x,
                y1 - 10 if bottom_v < 0 else zero_y + 30, y0 + 10, zero_y)
    size = SIZES["label"][out.frame.vertical]
    for i, b in enumerate(bars):
        x = axis_x + 40 + slot * (i + 0.5)
        h = b["value"] * unit
        out.add(f"{d['id']}:bar:{b['label'] or i}", "bar", 1 + i, b["on_word"], x=x, base=zero_y,
                w=bar_w, h=h, color=_series(out.ink, i))
        if b["label"]:
            ly = zero_y - h - size if b["value"] >= 0 else zero_y - h + size
            # Beside the end of the bar, so it rides with it when it moves.
            p = out.words(f"{d['id']}:barlabel:{b['label']}", b["label"], x, ly, size,
                          order=1 + i, word=b["on_word"], maths=True)
            p["rides"] = f"{d['id']}:bar:{b['label'] or i}"


def _nice_step(span: float, most: int = 12) -> float:
    raw = span / most
    power = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 5, 10):
        if raw <= m * power:
            return m * power
    return 10 * power


def _fmt(v: float) -> str:
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:g}"


def _number_line(d, box, out):
    x0, y0, x1, y1 = box
    lo, hi = d["range"]
    lw = out.ink.get("line", 4)
    left, right = x0 + 40, x1 - 40
    y = (y0 + y1) / 2 + (60 if d["jumps"] else 0)
    to_x = lambda v: left + 30 + (right - left - 60) * (v - lo) / (hi - lo)  # noqa: E731
    base = f"{d['id']}:nl:{_fmt(lo)}:{_fmt(hi)}"
    out.add(f"{base}:line", "stroke", 0, points=[[left, y], [right, y]], width=lw,
            color=out.ink["ink"], arrow="both", solid_head=True)
    step = _nice_step(hi - lo, 10 if out.frame.vertical else 16)
    size = SIZES["tick"][out.frame.vertical]
    label_size = SIZES["label"][out.frame.vertical]
    v = math.ceil(lo / step) * step
    while v <= hi + 1e-9:
        x = to_x(v)
        out.add(f"{base}:tick:{_fmt(v)}", "stroke", 0, points=[[x, y - 18], [x, y + 18]],
                width=lw * 0.8, color=out.ink["ink"])
        out.words(f"{base}:ticklabel:{_fmt(v)}", _fmt(v), x, y + size + 34, size, order=0)
        v += step
    size = label_size
    if d["shade"]:
        a, b = d["shade"]
        out.add(f"{d['id']}:shade:{_fmt(a)}:{_fmt(b)}", "stroke", 1,
                points=[[to_x(a), y], [to_x(b), y]], width=lw * 3.5, color=_series(out.ink, 1),
                opacity=0.85)
    for i, j in enumerate(d["jumps"]):
        xa, xb = to_x(j["from"]), to_x(j["to"])
        rise = min(160, 40 + abs(xb - xa) * 0.35)
        pts = [[xa + (xb - xa) * t, y - 22 - math.sin(math.pi * t) * rise] for t in
               (k / 24 for k in range(25))]
        colour = _series(out.ink, 2 + i)
        out.add(f"{d['id']}:jump:{_fmt(j['from'])}:{_fmt(j['to'])}:{i}", "stroke", 2 + i,
                j["on_word"], points=pts, width=lw, color=colour, arrow="end")
        if j["label"]:
            out.words(f"{d['id']}:jumplabel:{i}:{j['label']}", j["label"], (xa + xb) / 2,
                      y - 22 - rise - size, size, order=2 + i, word=j["on_word"], maths=True)
    # Points are labelled above the line, or below its numbers when jumps
    # arc over it.
    label_y = y + SIZES["tick"][out.frame.vertical] * 2 + 70 if d["jumps"] else y - 62
    for i, p in enumerate(d["points"]):
        x = to_x(p["at"])
        pid = f"{d['id']}:point:{p['label'] or i}"
        out.add(pid, "dot", 1 + i, p["on_word"], x=x, y=y, r=15, color=_series(out.ink, i))
        if p["label"]:
            lp = out.words(f"{d['id']}:pointlabel:{p['label']}", p["label"], x, label_y, size,
                           order=1 + i, word=p["on_word"], maths=True, color=_series(out.ink, i))
            lp["rides"] = pid


def _plot(d, box, out):
    x0, y0, x1, y1 = box
    lo, hi = d["range"]
    samples = []
    for c in d["curves"]:
        samples.append(expr.sample(c["expr"], lo, hi))
    ys = [pt[1] for s in samples for pt in s if pt] + [p["y"] for p in d["points"]]
    if d["y_range"]:
        ylo, yhi = d["y_range"]
    else:
        ylo, yhi = (min(ys), max(ys)) if ys else (-1.0, 1.0)
        if yhi - ylo < 1e-9:
            ylo, yhi = ylo - 1, yhi + 1
        pad = (yhi - ylo) * 0.12
        ylo, yhi = (ylo - pad if ylo < 0 or ylo - pad < 0 < ylo else ylo), yhi + pad
        if 0 < ylo < (yhi - ylo) * 0.3:
            ylo = 0.0
    left, right, top, bottom = x0 + 40, x1 - 40, y0 + 30, y1 - 60
    to_x = lambda v: left + (right - left) * (v - lo) / (hi - lo)  # noqa: E731
    to_y = lambda v: bottom - (bottom - top) * (v - ylo) / (yhi - ylo)  # noqa: E731
    zero_y = to_y(0) if ylo <= 0 <= yhi else bottom
    axis_x = to_x(0) if lo <= 0 <= hi else left
    _arrow_axes(out, f"{d['id']}:axes:{_fmt(lo)}:{_fmt(hi)}:{ylo:.3g}:{yhi:.3g}",
                left - 20, right + 20, axis_x, bottom + 20, top - 20, zero_y,
                x_both=False, y_both=False)
    size = SIZES["label"][out.frame.vertical]
    lw = out.ink.get("line", 4)
    for v in (lo, hi):
        if abs(v) > 1e-9:
            out.words(f"{d['id']}:xtick:{_fmt(v)}", _fmt(v), to_x(v), zero_y + 46,
                      SIZES["tick"][out.frame.vertical])
    taken = []                             # label lines already used at the curves' ends
    for i, (c, pts) in enumerate(zip(d["curves"], samples)):
        colour = _series(out.ink, i)
        segment, part = [], 0
        clipped = [(to_x(x), max(top - 30, min(bottom + 30, to_y(y)))) if pt else None
                   for pt in pts for x, y in ([pt] if pt else [(0, 0)])]
        for pt in clipped + [None]:
            if pt is None:
                if len(segment) > 1:
                    out.add(f"{d['id']}:curve:{c['expr']}:{part}", "stroke", 1 + i, c["on_word"],
                            points=[[round(x, 1), round(y, 1)] for x, y in segment],
                            width=lw * 1.15, color=colour)
                    part += 1
                segment = []
            else:
                segment.append(pt)
        if c["label"]:
            last = next((pt for pt in reversed(clipped) if pt), None)
            if last:
                # Right-aligned just inside the end of its curve, in its colour,
                # and moved off any label already there (curves that end together).
                y = max(top + 20, last[1] - 44)
                while any(abs(y - t) < size * 1.5 for t in taken):
                    y += size * 1.5
                taken.append(y)
                out.words(f"{d['id']}:curvelabel:{c['label']}", c["label"],
                          min(last[0], right) - 8, y, size, order=1 + i, word=c["on_word"],
                          maths=True, align="end", color=colour)
    if d["shade"] and samples:
        a, b = d["shade"]
        area = [(x, y) for pt in expr.sample(d["curves"][0]["expr"], a, b, 80) if pt
                for x, y in [pt]]
        if len(area) > 1:
            poly = [[to_x(area[0][0]), zero_y]] + \
                   [[to_x(x), max(top, min(bottom, to_y(y)))] for x, y in area] + \
                   [[to_x(area[-1][0]), zero_y]]
            out.add(f"{d['id']}:area:{_fmt(a)}:{_fmt(b)}", "area", len(d["curves"]) + 1,
                    points=[[round(x, 1), round(y, 1)] for x, y in poly],
                    color=_series(out.ink, 0), opacity=0.42)
    for i, p in enumerate(d["points"]):
        x, y = to_x(p["at"]), to_y(p["y"])
        if not (left - 5 <= x <= right + 5 and top - 5 <= y <= bottom + 5):
            continue
        pid = f"{d['id']}:ppoint:{p['label'] or i}"
        out.add(pid, "dot", len(d["curves"]) + 1 + i, p["on_word"], x=x, y=y, r=12,
                color=out.ink["accent"])
        if p["label"]:
            # To the right of its point, or to the left in the right half,
            # so it never runs off the edge.
            right_side = x < (left + right) / 2
            ly = y - 40
            while any(abs(ly - t) < size * 1.5 for t in taken):      # clear of the curve labels
                ly -= size * 1.5
            taken.append(ly)
            lp = out.words(f"{d['id']}:ppointlabel:{p['label']}", p["label"],
                           x + 16 if right_side else x - 16, ly, size,
                           order=len(d["curves"]) + 1 + i, word=p["on_word"],
                           align="start" if right_side else "end", maths=True)
            lp["rides"] = pid


def _graph(d, box, out):
    x0, y0, x1, y1 = box
    nodes, edges = d["nodes"], d["edges"]
    n = len(nodes)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    labelled = any(nd["label"] for nd in nodes)
    long_labels = any(len(nd["label"]) > 4 for nd in nodes)
    r = (44 if labelled else 20) if not long_labels else 0
    pos = {}
    arrangement = d["arrangement"]
    if arrangement == "tree":
        depth = {nodes[0]["id"]: 0}
        frontier = [nodes[0]["id"]]
        while frontier:
            nxt = []
            for a in frontier:
                for e in edges:
                    for s, t in ((e["from"], e["to"]),) + (() if d["directed"] else ((e["to"], e["from"]),)):
                        if s == a and t not in depth:
                            depth[t] = depth[a] + 1
                            nxt.append(t)
            frontier = nxt
        for nd in nodes:
            depth.setdefault(nd["id"], max(depth.values()) + 1)
        levels = {}
        for nd in nodes:
            levels.setdefault(depth[nd["id"]], []).append(nd["id"])
        deepest = max(levels)
        for lv, ids in levels.items():
            yy = y0 + 80 + (y1 - y0 - 160) * (lv / max(1, deepest))
            for k, nid in enumerate(ids):
                pos[nid] = (x0 + (x1 - x0) * (k + 0.5) / len(ids), yy)
    elif arrangement in ("row", "column"):
        # A flow runs down a vertical frame (a short one, whichever way it
        # was asked for) and across a wide one: that's the way there's room.
        down = out.frame.vertical and (arrangement == "column" or n <= 6)
        for k, nd in enumerate(nodes):
            pos[nd["id"]] = ((cx, y0 + (y1 - y0) * (k + 0.5) / n) if down
                             else (x0 + (x1 - x0) * (k + 0.5) / n, cy))
    else:
        rx = min((x1 - x0) / 2 - 90, (y1 - y0) / 2 * (1.5 if not out.frame.vertical else 1) - 90)
        ry = min((y1 - y0) / 2 - 80, rx if out.frame.vertical else (y1 - y0) / 2 - 80)
        for k, nd in enumerate(nodes):
            a = -math.pi / 2 + 2 * math.pi * k / n
            pos[nd["id"]] = (cx + rx * math.cos(a), cy + ry * math.sin(a))
    size = SIZES["node"][out.frame.vertical]
    lw = out.ink.get("line", 4)
    if not r:
        size = _fit_boxes(out, nodes, pos, size * 0.8, (x1 - x0)) / 0.8
    half = {}                              # node -> (half width, half height) of its shape
    for k, nd in enumerate(nodes):
        x, y = pos[nd["id"]]
        pid = f"{d['id']}:node:{nd['id']}"
        if r:                              # a dot, or a ring with a short label inside
            out.add(pid, "dot", 0, x=x, y=y, r=r, color=out.ink["ink"],
                    hollow=bool(nd["label"]), width=lw)
            out.prims[-1]["stagger"] = round(0.08 * k, 3)
            if nd["label"]:
                p = out.words(f"{pid}:label:{nd['label']}", nd["label"], x, y, size * 0.8,
                              order=0, maths=True)
                p["stagger"] = round(0.08 * k + 0.1, 3)
            half[nd["id"]] = (r, r)
        else:                              # words in a box
            p = out.words(f"{pid}:label:{nd['label']}", nd["label"] or nd["id"], x, y, size * 0.8,
                          order=0)
            w = p["w"] if p["kind"] == "math" else len(p["text"]) * p["size"] * 0.5
            h = p["h"] if p["kind"] == "math" else p["size"] * 1.1
            bw, bh = w / 2 + 26, h / 2 + 18
            out.add(f"{pid}:box:{round(bw)}", "stroke", 0,
                    points=[[x - bw, y - bh], [x + bw, y - bh], [x + bw, y + bh], [x - bw, y + bh],
                            [x - bw, y - bh]], width=lw, color=out.ink["ink"])
            out.prims[-1]["stagger"] = p["stagger"] = round(0.1 * k, 3)
            half[nd["id"]] = (bw, bh)

    def edge_of(node, ux, uy):
        hw, hh = half[node]
        return min(hw / abs(ux) if abs(ux) > 1e-6 else 1e9, hh / abs(uy) if abs(uy) > 1e-6 else 1e9) + 12

    for i, e in enumerate(edges):
        (ax, ay), (bx, by) = pos[e["from"]], pos[e["to"]]
        length = math.hypot(bx - ax, by - ay) or 1
        ux, uy = (bx - ax) / length, (by - ay) / length
        ga, gb = edge_of(e["from"], ux, uy), edge_of(e["to"], ux, uy)
        colour = _series(out.ink, i) if not d["directed"] and not labelled else out.ink["ink"]
        out.add(f"{d['id']}:edge:{e['from']}:{e['to']}", "stroke", 1 + i * 0.25, e["on_word"],
                points=[[ax + ux * ga, ay + uy * ga], [bx - ux * gb, by - uy * gb]], width=lw,
                color=colour, arrow="end" if d["directed"] else "", solid_head=True)
        # Edge labels only while there are few enough to read; a busy graph
        # keeps its structure clear instead.
        if e["label"] and sum(1 for x in edges if x["label"]) <= MAX_EDGE_LABELS:
            # Beside the arrow's middle, clear of it by the label's own size.
            small = size * 0.55
            w, h = _label_size(out, mathtext.as_math(e["label"]), small)
            px, py = -uy, ux
            off = abs(px) * (w / 2 + 16) + abs(py) * (h / 2 + 10)
            out.words(f"{d['id']}:edgelabel:{e['from']}:{e['to']}:{e['label']}", e["label"],
                      (ax + bx) / 2 + px * off, (ay + by) / 2 + py * off, small,
                      order=1 + i * 0.25, word=e["on_word"], maths=True)


def _label_size(out, text: str, size: float) -> tuple:
    """(w, h) a node's label will take at `size`."""
    if mathtext.is_math(text) or out.math_face:
        _, w, h = out.typeset(text, out.ink["ink"], size)
        return w, h
    return len(text) * size * 1.45 * 0.5, size * 1.6


def _fit_boxes(out, nodes, pos, size, width) -> float:
    """The largest label size up to `size` at which no two boxed nodes
    overlap and none is wider than the diagram."""
    while size > 18:
        boxes = []
        for nd in nodes:
            w, h = _label_size(out, nd["label"] or nd["id"], size)
            x, y = pos[nd["id"]]
            boxes.append((x - w / 2 - 34, y - h / 2 - 24, x + w / 2 + 34, y + h / 2 + 24))
        clash = any(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                    for i, a in enumerate(boxes) for b in boxes[i + 1:])
        if not clash and all(b[2] - b[0] <= width for b in boxes):
            return size
        size *= 0.88
    return size
