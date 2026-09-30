"""
Designed arrangements for a beat: where each object goes, how big, and
where its label, arrows and symbols sit.

The storyboard only ever names a layout and fills it (which objects, how
many, what each label says). Placement is always this code's: decision
040 found that a model placing things on an empty canvas can't make a
composed frame, and every layout here is composed by rule, fits the
vertical frame, keeps clear of the captions' third, and can't overlap
its own labels.

Coordinates are within one 1080x1920 area whose top-left is `origin`.
"""

from __future__ import annotations

import math

LAYOUTS = ("hero", "pair", "row", "grid", "steps", "cycle", "group", "travel", "scale",
           "statement", "presenter")

# How many objects each layout takes.
ITEM_LIMITS = {"hero": (1, 1), "pair": (2, 2), "row": (2, 3), "grid": (4, 6), "steps": (2, 4),
               "cycle": (3, 5), "group": (1, 1), "travel": (1, 3), "scale": (2, 4),
               "statement": (0, 1), "presenter": (0, 1)}
RELATIONS = ("", "vs", "plus", "equals", "arrow")
MAX_COUNT = 30

TITLE_Y = 230
CENTRE_Y = 800          # the middle of the space between the title and the captions
BOTTOM = 1230           # nothing placed lower: the captions' third starts about 1280


def fit(aspect: float, max_w: float, max_h: float) -> tuple:
    """(w, h) of something with this aspect (w/h) inside max_w x max_h."""
    if aspect <= 0:
        aspect = 1.0
    w = min(max_w, max_h * aspect)
    return round(w), round(w / aspect)


def _tilt(key: str, i: int, amount: float) -> float:
    seed = sum(ord(c) for c in key) * 13 + i * 7
    return round(math.sin(seed * 12.9898) * amount, 2)


def _place(key, i, x, y, box, aspects, tilt, origin, label=None, chars=12, label_gap=62):
    w, h = fit(aspects.get(key, 1.0), *box)
    ox, oy = origin
    p = {"key": key, "copy": i, "x": ox + x, "y": oy + y, "w": w, "h": h, "rot": _tilt(key, i, tilt)}
    marks = []
    if label:
        marks.append({"kind": "label", "role": "label", "anchor": (key, i), "text": label,
                      "x": ox + x, "y": oy + y + h / 2 + label_gap, "chars": chars})
    return p, marks


def _cluster(key, count, cx, cy, box, aspects, tilt, origin, highlight=None):
    """`count` copies of one object packed into a box, as a loose grid."""
    count = max(1, min(MAX_COUNT, int(count)))
    cols = max(1, math.ceil(math.sqrt(count * box[0] / box[1])))
    rows = math.ceil(count / cols)
    cw, ch = box[0] / cols, box[1] / rows
    placed, marks = [], []
    for i in range(count):
        r, c = divmod(i, cols)
        in_row = min(cols, count - r * cols)
        x = cx - (in_row * cw) / 2 + cw * (c + 0.5)
        y = cy - (rows * ch) / 2 + ch * (r + 0.5)
        jig = 0.08 * min(cw, ch)
        x += math.sin(i * 3.7 + len(key)) * jig
        y += math.cos(i * 5.3 + len(key)) * jig
        p, _ = _place(key, i, x, y, (cw * 0.86, ch * 0.86), aspects, tilt * 1.5, origin)
        placed.append(p)
        if highlight is not None and i == highlight:
            marks.append({"kind": "ring", "role": "highlight", "anchor": (key, i),
                          "x": p["x"], "y": p["y"], "rx": p["w"] * 0.72, "ry": p["h"] * 0.72})
    return placed, marks


def arrange(layout: str, items: list, aspects: dict, origin=(0, 0), relation: str = "",
            title: str = "", tilt: float = 3.0) -> tuple:
    """(placements, marks) for one beat.

    `items`: [{"key", "label", "count", "highlight"}] in the storyboard's
    order. `aspects`: {key: width / height} of each object's picture.
    Placements are {"key", "copy", "x", "y", "w", "h", "rot"} (centres, in
    world coordinates); marks are the runtime's marks without timing,
    each with a "role" and, where it belongs to an object, an "anchor"."""
    ox, oy = origin
    placed, marks = [], []
    lo, hi = ITEM_LIMITS.get(layout, (0, 6))
    items = items[:hi]
    if title and layout != "statement":
        marks.append({"kind": "title", "role": "title", "text": title, "x": ox + 540,
                      "y": oy + TITLE_Y})

    def add(result):
        p, m = result
        placed.append(p)
        marks.extend(m)

    if layout == "hero" and items:
        it = items[0]
        if int(it.get("count") or 1) > 1:
            ps, ms = _cluster(it["key"], it["count"], 540, CENTRE_Y, (700, 640), aspects, tilt,
                              origin, _highlight(it))
            placed += ps
            marks += ms
            if it.get("label"):
                marks.append(_label_under(it, ox + 540, oy + CENTRE_Y + 380, 18))
        else:
            add(_place(it["key"], 0, 540, CENTRE_Y, (780, 720), aspects, tilt, origin,
                       it.get("label"), 18, 90))

    elif layout == "pair" and len(items) >= 2:
        # Joined by a symbol or an arrow, the two stand further apart and a
        # little smaller, so what joins them has room to be read.
        joined = relation in ("arrow", "plus", "vs", "equals")
        sides = (250, 830) if joined else (285, 795)
        box = (370, 500) if joined else (460, 540)
        for side, it in zip(sides, items[:2]):
            count = int(it.get("count") or 1)
            if count > 1:
                ps, ms = _cluster(it["key"], count, side, CENTRE_Y, (box[0] + 20, 460), aspects,
                                  tilt, origin, _highlight(it))
                placed += ps
                marks += ms
                if it.get("label"):
                    marks.append(_label_under(it, ox + side, oy + CENTRE_Y + 300, 11))
            else:
                add(_place(it["key"], 0, side, CENTRE_Y, box, aspects, tilt, origin,
                           it.get("label"), 11, 72))
        marks += _relation(relation, placed[:1] + placed[-1:], origin)

    elif layout == "row" and items:
        n = len(items)
        xs = (300, 780) if n == 2 else (190, 540, 890)
        joined = relation in ("arrow", "plus", "vs", "equals")
        # Room between them for what joins them.
        box = ((400 if joined else 460), 500) if n == 2 else ((250 if joined else 300), 400)
        for x, it in zip(xs, items):
            add(_place(it["key"], 0, x, CENTRE_Y, box, aspects, tilt, origin, it.get("label"),
                       10 if n == 3 else 12, 60))
        marks += _relation(relation or "", [p for p in placed], origin)

    elif layout == "grid" and items:
        n = len(items)
        rows = (580, 1000) if n <= 4 else (480, 810, 1140)
        box = (400, 340) if n <= 4 else (360, 250)
        for i, it in enumerate(items):
            r, c = divmod(i, 2)
            add(_place(it["key"], 0, (300, 780)[c], rows[r], box, aspects, tilt, origin,
                       it.get("label"), 12, 52 if n > 4 else 58))

    elif layout == "steps" and items:
        n = len(items)
        top, bottom = 430, 1170
        gap = (bottom - top) / max(1, n - 1) if n > 1 else 0
        size = min(300, gap - 30) if n > 1 else 360
        for i, it in enumerate(items):
            y = top + gap * i if n > 1 else CENTRE_Y
            p, _ = _place(it["key"], 0, 330, y, (size, size), aspects, tilt, origin)
            placed.append(p)
            marks.append({"kind": "badge", "role": "badge", "anchor": (it["key"], 0),
                          "text": str(i + 1), "x": ox + 120, "y": oy + y, "r": 40})
            if it.get("label"):
                marks.append({"kind": "label", "role": "label", "anchor": (it["key"], 0),
                              "text": it["label"], "x": ox + 530, "y": oy + y, "align": "start",
                              "chars": 14})
        for a, b in zip(placed, placed[1:]):
            marks.append({"kind": "arrow", "role": "relation", "anchor": (b["key"], b["copy"]),
                          "x1": a["x"], "y1": a["y"] + a["h"] / 2 + 12,
                          "x2": b["x"], "y2": b["y"] - b["h"] / 2 - 12, "bend": 0.0})

    elif layout == "cycle" and items:
        n = len(items)
        cx, cy, r = 540, 820, 330 if n <= 4 else 350
        box = (290, 290) if n <= 4 else (240, 240)
        angles = [-math.pi / 2 + 2 * math.pi * i / n for i in range(n)]
        for a, it in zip(angles, items):
            add(_place(it["key"], 0, cx + r * math.cos(a), cy + r * math.sin(a), box, aspects,
                       tilt, origin, it.get("label"), 10, 44))
        for i in range(n):
            a0, a1 = angles[i], angles[(i + 1) % n]
            if a1 < a0:
                a1 += 2 * math.pi
            s, e = a0 + 0.42, a1 - 0.42
            rr = r * 1.0
            marks.append({"kind": "arrow", "role": "relation",
                          "anchor": (items[(i + 1) % n]["key"], 0),
                          "x1": ox + cx + rr * math.cos(s), "y1": oy + cy + rr * math.sin(s),
                          "x2": ox + cx + rr * math.cos(e), "y2": oy + cy + rr * math.sin(e),
                          "bend": -0.22})

    elif layout == "group" and items:
        it = items[0]
        ps, ms = _cluster(it["key"], it.get("count") or 10, 540, CENTRE_Y - 20, (900, 760),
                          aspects, tilt, origin, _highlight(it))
        placed += ps
        marks += ms
        if it.get("label"):
            marks.append(_label_under(it, ox + 540, oy + CENTRE_Y + 400, 18))

    elif layout == "travel" and items:
        # The traveller, then where it starts and where it arrives. An end
        # given alone (`place: "end"`) means it sets off from nowhere in
        # particular and arrives there.
        mover = items[0]
        start, end = (270, 1080), (810, 500)
        ends = {}
        for it in items[1:3]:
            where = it.get("place") or ("start" if "start" not in ends else "end")
            ends.setdefault(where, it)
        for where, (x, y) in (("start", start), ("end", end)):
            if where in ends:
                it = ends[where]
                add(_place(it["key"], 0, x, y, (380, 380), aspects, tilt, origin,
                           it.get("label"), 11, 60))
        # The mover is placed at its destination; the script moves it there
        # from the start along the dotted path.
        size = (270, 270) if ends else (420, 420)
        # Beside its start and its end, never on top of them.
        sx, sy = (start[0] + 270, start[1] - 220) if "start" in ends else (200, 1020)
        ex, ey = (end[0] - 270, end[1] + 220) if "end" in ends else (860, 520)
        p, _ = _place(mover["key"], 0, ex, ey, size, aspects, tilt, origin)
        p["from"] = (ox + sx, oy + sy)
        placed.insert(0, p)
        marks.append({"kind": "path", "role": "relation", "anchor": (mover["key"], 0),
                      "x1": p["from"][0], "y1": p["from"][1], "x2": p["x"], "y2": p["y"],
                      "bend": 0.28})
        if mover.get("label"):
            # Beside the middle of its path, clear of both ends.
            mx, my = (p["from"][0] + p["x"]) / 2, (p["from"][1] + p["y"]) / 2
            marks.append({"kind": "label", "role": "label", "anchor": (mover["key"], 0),
                          "text": mover["label"], "x": mx + 150, "y": my + 110, "chars": 12})

    elif layout == "scale" and items:
        n = len(items)
        factors = [0.42, 0.62, 0.82, 1.0][-n:] if n < 4 else [0.4, 0.58, 0.78, 1.0]
        base_y = 1080
        xs = [140 + (800 / max(1, n - 1)) * i for i in range(n)] if n > 1 else [540]
        width = 820 / n
        for x, f, it in zip(xs, factors, items):
            w, h = fit(aspects.get(it["key"], 1.0), width * 0.92 * f / max(factors) * 1.05,
                       560 * f)
            placed.append({"key": it["key"], "copy": 0, "x": ox + x, "y": oy + base_y - h / 2,
                           "w": w, "h": h, "rot": _tilt(it["key"], 0, tilt * 0.5)})
            if it.get("label"):
                marks.append({"kind": "label", "role": "label", "anchor": (it["key"], 0),
                              "text": it["label"], "x": ox + x, "y": oy + base_y + 70,
                              "chars": 9})

    elif layout == "statement":
        if items:
            add(_place(items[0]["key"], 0, 540, 560, (520, 460), aspects, tilt, origin))
        if title:
            marks.append({"kind": "title", "role": "statement", "text": title,
                          "x": ox + 540, "y": oy + (1010 if items else CENTRE_Y), "big": True})

    elif layout == "presenter":
        if items:
            it = items[0]
            add(_place(it["key"], 0, 770, 660, (480, 480), aspects, tilt, origin,
                       it.get("label"), 12, 64))
    return placed, marks


def _highlight(item: dict):
    return 0 if item.get("highlight") else None


def _label_under(item: dict, x: float, y: float, chars: int) -> dict:
    return {"kind": "label", "role": "label", "anchor": (item["key"], 0), "text": item["label"],
            "x": x, "y": y, "chars": chars}


def _relation(relation: str, placed: list, origin) -> list:
    """The mark(s) between neighbouring objects: vs, +, =, or arrows."""
    out = []
    for a, b in zip(placed, placed[1:]):
        if a is b:
            continue
        mx, my = (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
        anchor = (b["key"], b["copy"])
        if relation == "arrow":
            gap = 16
            out.append({"kind": "arrow", "role": "relation", "anchor": anchor,
                        "x1": a["x"] + a["w"] / 2 + gap, "y1": a["y"],
                        "x2": b["x"] - b["w"] / 2 - gap, "y2": b["y"], "bend": -0.18})
        elif relation in ("vs", "plus", "equals"):
            out.append({"kind": "symbol", "role": "relation", "anchor": anchor,
                        "text": {"vs": "vs", "plus": "+", "equals": "="}[relation],
                        "x": mx, "y": my})
    return out
