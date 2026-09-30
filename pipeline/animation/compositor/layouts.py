"""
Designed arrangements for a beat: where each object goes, how big, and
where its label, arrows and symbols sit.

The storyboard only ever names a layout and fills it (which objects, how
many, what each label says). Placement is always this code's: decision
040 found that a model placing things on an empty canvas can't make a
composed frame, and every layout here is composed by rule, fits the
frame, keeps clear of the captions, and can't overlap its own labels.

Layouts are arranged in the frame's content box (pipeline.animation.frame,
decision 054): a vertical short stacks things down the middle, a
widescreen video spreads them across (steps run left to right, a grid
reflows, a statement sits beside its picture). Coordinates are world
coordinates within one frame-sized area whose top-left is `origin`.
"""

from __future__ import annotations

import math

from pipeline.animation import frame as frames

LAYOUTS = ("hero", "pair", "row", "grid", "steps", "cycle", "group", "travel", "scale",
           "lineup", "table", "statement", "presenter", "scene", "diagram")

# How many objects each layout takes.
ITEM_LIMITS = {"hero": (1, 1), "pair": (2, 2), "row": (2, 3), "grid": (4, 6), "steps": (2, 4),
               "cycle": (3, 5), "group": (1, 1), "travel": (1, 3), "scale": (2, 4),
               "statement": (0, 1), "presenter": (0, 1), "lineup": (2, 8), "table": (0, 2),
               "scene": (0, 5), "diagram": (0, 2)}
ROLES = ("", "left", "centre", "right", "prop")
RELATIONS = ("", "vs", "plus", "equals", "arrow")
MAX_COUNT = 30
STAGE_FLOOR = frames.VERTICAL.floor      # where a puppet's feet are, in a vertical frame


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


def diagram_box(frame, items: int = 0, title: bool = False) -> tuple:
    """(left, top, right, bottom) of the space a beat's diagram fills: all
    of the content box, less a band for up to two pictures (above it in a
    vertical frame, beside it in a wide one)."""
    f = frames.get(frame)
    left, top, right, bottom = f.content
    if not title:
        top -= 60 if f.vertical else 40
    if items:
        if f.vertical:
            top += 330
        else:
            left += 470
    return left + 10, top, right - 10, bottom


def arrange(layout: str, items: list, aspects: dict, origin=(0, 0), relation: str = "",
            title: str = "", tilt: float = 3.0, table: list = None, backdrop: str = "",
            caption: str = "", frame=None) -> tuple:
    """(placements, marks) for one beat.

    `items`: [{"key", "label", "count", "highlight"}] in the storyboard's
    order. `aspects`: {key: width / height} of each object's picture.
    Placements are {"key", "copy", "x", "y", "w", "h", "rot"} (centres, in
    world coordinates); marks are the runtime's marks without timing,
    each with a "role" and, where it belongs to an object, an "anchor".
    A diagram layout adds a mark of kind "diagram" whose "box" is the
    diagram's space (drawn by compositor.diagrams, not the runtime)."""
    f = frames.get(frame)
    wide = not f.vertical
    ox, oy = origin
    cx, cy = f.cx, f.cy
    left, top, right, bottom = f.content
    placed, marks = [], []
    lo, hi = ITEM_LIMITS.get(layout, (0, 6))
    items = items[:hi]
    if title and layout != "statement":
        marks.append({"kind": "title", "role": "title", "text": title, "x": ox + f.w / 2,
                      "y": oy + f.title_y})

    def add(result):
        p, m = result
        placed.append(p)
        marks.extend(m)

    if layout == "hero" and items:
        it = items[0]
        if int(it.get("count") or 1) > 1:
            box = (1100, 500) if wide else (700, 640)
            ps, ms = _cluster(it["key"], it["count"], cx, cy - (20 if wide else 0), box, aspects,
                              tilt, origin, _highlight(it))
            placed += ps
            marks += ms
            if it.get("label"):
                marks.append(_label_under(it, ox + cx, oy + cy + box[1] / 2 + 60, 18))
        else:
            box = (900, 500) if wide else (780, 720)
            add(_place(it["key"], 0, cx, cy - (25 if wide else 0), box, aspects, tilt, origin,
                       it.get("label"), 24 if wide else 18, 64 if wide else 90))

    elif layout == "pair" and len(items) >= 2:
        # Joined by a symbol or an arrow, the two stand further apart and a
        # little smaller, so what joins them has room to be read.
        joined = relation in ("arrow", "plus", "vs", "equals")
        if wide:
            spread, box = (470, (560, 480)) if joined else (430, (640, 500))
        else:
            spread, box = (290, (370, 500)) if joined else (255, (460, 540))
        sides = (cx - spread, cx + spread)
        for side, it in zip(sides, items[:2]):
            count = int(it.get("count") or 1)
            if count > 1:
                ps, ms = _cluster(it["key"], count, side, cy, (box[0] + 20, 460), aspects,
                                  tilt, origin, _highlight(it))
                placed += ps
                marks += ms
                if it.get("label"):
                    marks.append(_label_under(it, ox + side, oy + cy + 300, 11))
            else:
                add(_place(it["key"], 0, side, cy - (20 if wide else 0), box, aspects, tilt,
                           origin, it.get("label"), 16 if wide else 11, 58 if wide else 72))
        marks += _relation(relation, placed[:1] + placed[-1:], origin)

    elif layout == "row" and items:
        n = len(items)
        joined = relation in ("arrow", "plus", "vs", "equals")
        if wide:
            xs = (cx - 420, cx + 420) if n == 2 else (cx - 560, cx, cx + 560)
            box = ((560 if joined else 620), 480) if n == 2 else ((380 if joined else 440), 460)
        else:
            xs = (cx - 240, cx + 240) if n == 2 else (cx - 350, cx, cx + 350)
            # Room between them for what joins them.
            box = ((400 if joined else 460), 500) if n == 2 else ((250 if joined else 300), 400)
        for x, it in zip(xs, items):
            add(_place(it["key"], 0, x, cy - (20 if wide else 0), box, aspects, tilt, origin,
                       it.get("label"), (14 if wide else 10) if n == 3 else (16 if wide else 12),
                       56 if wide else 60))
        marks += _relation(relation or "", [p for p in placed], origin)

    elif layout == "grid" and items:
        n = len(items)
        if wide:
            if n <= 4:
                slot = f.cw / n
                spots = [(left + slot * (i + 0.5), cy - 30) for i in range(n)]
                box = (min(400, slot * 0.8), 420)
            else:
                spots = [(cx + dx, y) for y in (cy - 175, cy + 175) for dx in (-560, 0, 560)]
                box = (420, 230)
            gap = 50
        else:
            rows = (580, 1000) if n <= 4 else (480, 810, 1140)
            spots = [((cx - 240, cx + 240)[i % 2], rows[i // 2]) for i in range(n)]
            box = (400, 340) if n <= 4 else (360, 250)
            gap = 52 if n > 4 else 58
        for (x, y), it in zip(spots, items):
            add(_place(it["key"], 0, x, y, box, aspects, tilt, origin, it.get("label"),
                       14 if wide else 12, gap))

    elif layout == "steps" and items:
        n = len(items)
        if wide:
            # Left to right, numbered above, labelled below, arrows between.
            slot = f.cw / n
            size = min(330, slot - 110)
            y = cy - 20
            for i, it in enumerate(items):
                x = left + slot * (i + 0.5)
                p, _ = _place(it["key"], 0, x, y, (size, size), aspects, tilt, origin)
                placed.append(p)
                marks.append({"kind": "badge", "role": "badge", "anchor": (it["key"], 0),
                              "text": str(i + 1), "x": ox + x, "y": oy + y - size / 2 - 70,
                              "r": 38})
                if it.get("label"):
                    marks.append({"kind": "label", "role": "label", "anchor": (it["key"], 0),
                                  "text": it["label"], "x": ox + x, "y": oy + y + size / 2 + 62,
                                  "chars": max(8, int(slot / 30))})
            for a, b in zip(placed, placed[1:]):
                marks.append({"kind": "arrow", "role": "relation", "anchor": (b["key"], b["copy"]),
                              "x1": a["x"] + a["w"] / 2 + 14, "y1": a["y"],
                              "x2": b["x"] - b["w"] / 2 - 14, "y2": b["y"], "bend": 0.0})
        else:
            first, last = 430, 1170
            gap = (last - first) / max(1, n - 1) if n > 1 else 0
            size = min(300, gap - 30) if n > 1 else 360
            for i, it in enumerate(items):
                y = first + gap * i if n > 1 else cy
                p, _ = _place(it["key"], 0, 330, y, (size, size), aspects, tilt, origin)
                placed.append(p)
                marks.append({"kind": "badge", "role": "badge", "anchor": (it["key"], 0),
                              "text": str(i + 1), "x": ox + 120, "y": oy + y, "r": 40})
                if it.get("label"):
                    marks.append({"kind": "label", "role": "label", "anchor": (it["key"], 0),
                                  "text": it["label"], "x": ox + 530, "y": oy + y,
                                  "align": "start", "chars": 14})
            for a, b in zip(placed, placed[1:]):
                marks.append({"kind": "arrow", "role": "relation", "anchor": (b["key"], b["copy"]),
                              "x1": a["x"], "y1": a["y"] + a["h"] / 2 + 12,
                              "x2": b["x"], "y2": b["y"] - b["h"] / 2 - 12, "bend": 0.0})

    elif layout == "cycle" and items:
        n = len(items)
        if wide:
            ccx, ccy, rx, ry = cx, cy - 10, 470, 235
            box = (250, 210) if n <= 4 else (220, 190)
        else:
            r = 330 if n <= 4 else 350
            ccx, ccy, rx, ry = cx, 820, r, r
            box = (290, 290) if n <= 4 else (240, 240)
        angles = [-math.pi / 2 + 2 * math.pi * i / n for i in range(n)]
        for a, it in zip(angles, items):
            add(_place(it["key"], 0, ccx + rx * math.cos(a), ccy + ry * math.sin(a), box,
                       aspects, tilt, origin, it.get("label"), 10 if not wide else 14,
                       44 if not wide else 36))
        for i in range(n):
            a0, a1 = angles[i], angles[(i + 1) % n]
            if a1 < a0:
                a1 += 2 * math.pi
            s, e = a0 + 0.42, a1 - 0.42
            marks.append({"kind": "arrow", "role": "relation",
                          "anchor": (items[(i + 1) % n]["key"], 0),
                          "x1": ox + ccx + rx * math.cos(s), "y1": oy + ccy + ry * math.sin(s),
                          "x2": ox + ccx + rx * math.cos(e), "y2": oy + ccy + ry * math.sin(e),
                          "bend": -0.22})

    elif layout == "group" and items:
        it = items[0]
        box = (1500, 560) if wide else (900, 760)
        ps, ms = _cluster(it["key"], it.get("count") or 10, cx, cy - 20, box, aspects, tilt,
                          origin, _highlight(it))
        placed += ps
        marks += ms
        if it.get("label"):
            marks.append(_label_under(it, ox + cx, oy + cy + box[1] / 2 + 20, 18))

    elif layout == "travel" and items:
        # The traveller, then where it starts and where it arrives. An end
        # given alone (`place: "end"`) means it sets off from nowhere in
        # particular and arrives there.
        mover = items[0]
        if wide:
            start, end, end_box, off = (left + 250, cy + 140), (right - 250, cy - 120), 340, (300, 150)
            lone = ((left + 160, cy + 200), (right - 200, cy - 150))
        else:
            start, end, end_box, off = (270, 1080), (810, 500), 380, (270, 220)
            lone = ((200, 1020), (860, 520))
        ends = {}
        for it in items[1:3]:
            where = it.get("place") or ("start" if "start" not in ends else "end")
            ends.setdefault(where, it)
        for where, (x, y) in (("start", start), ("end", end)):
            if where in ends:
                it = ends[where]
                add(_place(it["key"], 0, x, y, (end_box, end_box), aspects, tilt, origin,
                           it.get("label"), 11, 60))
        # The mover is placed at its destination; the script moves it there
        # from the start along the dotted path.
        size = (270, 270) if ends else (420, 420)
        # Beside its start and its end, never on top of them.
        sx, sy = (start[0] + off[0], start[1] - off[1]) if "start" in ends else lone[0]
        ex, ey = (end[0] - off[0], end[1] + off[1]) if "end" in ends else lone[1]
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
        if wide:
            base_y, span, tallest = cy + 230, 1360, 520
        else:
            base_y, span, tallest = 1080, 800, 560
        x0 = cx - span / 2
        xs = [x0 + (span / max(1, n - 1)) * i for i in range(n)] if n > 1 else [cx]
        width = (span + 20) / n
        for x, fct, it in zip(xs, factors, items):
            w, h = fit(aspects.get(it["key"], 1.0), width * 0.92 * fct / max(factors) * 1.05,
                       tallest * fct)
            placed.append({"key": it["key"], "copy": 0, "x": ox + x, "y": oy + base_y - h / 2,
                           "w": w, "h": h, "rot": _tilt(it["key"], 0, tilt * 0.5)})
            if it.get("label"):
                marks.append({"kind": "label", "role": "label", "anchor": (it["key"], 0),
                              "text": it["label"], "x": ox + x, "y": oy + base_y + 64,
                              "chars": 9 if not wide else 14})

    elif layout == "statement":
        if wide:
            if items:
                add(_place(items[0]["key"], 0, cx - 450, cy, (620, 560), aspects, tilt, origin))
            if title:
                marks.append({"kind": "title", "role": "statement", "text": title,
                              "x": ox + (cx + 330 if items else cx), "y": oy + cy, "big": True})
        else:
            if items:
                add(_place(items[0]["key"], 0, cx, 560, (520, 460), aspects, tilt, origin))
            if title:
                marks.append({"kind": "title", "role": "statement", "text": title,
                              "x": ox + cx, "y": oy + (1010 if items else cy), "big": True})

    elif layout == "presenter":
        if items:
            it = items[0]
            if wide:
                add(_place(it["key"], 0, cx + 330, cy - 20, (640, 540), aspects, tilt, origin,
                           it.get("label"), 18, 60))
            else:
                add(_place(it["key"], 0, 770, 660, (480, 480), aspects, tilt, origin,
                           it.get("label"), 12, 64))

    elif layout == "lineup" and items:
        # A row of figures or things standing side by side (the hats puzzle's
        # prisoners, a queue, the players of a game), feet on one line.
        n = len(items)
        if wide:
            span, x0, base, tallest, rate = 1600, cx - 800, cy + 200, 470, 1.4
        else:
            span, x0, base, tallest, rate = 940, 70, 1060, 560, 2.1
        slot = span / n
        height = min(tallest, slot * rate)
        copies = {}
        for i, it in enumerate(items):
            x = x0 + slot * (i + 0.5)
            copy = copies.get(it["key"], 0)
            copies[it["key"]] = copy + 1
            it["_copy"] = copy
            w, h = fit(aspects.get(it["key"], 0.6), slot * 0.86, height)
            placed.append({"key": it["key"], "copy": copy, "x": ox + x, "y": oy + base - h / 2,
                           "w": w, "h": h, "rot": _tilt(it["key"], i, tilt * 0.4)})
            if it.get("label"):
                marks.append({"kind": "label", "role": "label", "anchor": (it["key"], copy),
                              "text": it["label"], "x": ox + x, "y": oy + base + 58,
                              "chars": max(6, int(slot / 30)), "size": 52 if n > 4 else None})

    elif layout == "table":
        # Words in a grid: a payoff matrix, a before-and-after, a tally, on a
        # card of its own so it reads on any surface. What it's about sits
        # above it (beside it, in a wide frame), each thing labelled under.
        rows = [list(r) for r in (table or []) if r][:4]
        if rows:
            cols = max(len(r) for r in rows)
            rows = [r + [""] * (cols - len(r)) for r in rows]
            if wide:
                w, h = min(1040, 260 * cols), min(560, 135 * len(rows))
                tx, ty = (cx + 250 if items else cx), cy
                spots = [(left + 250, cy - 150), (left + 250, cy + 170)][:len(items[:2])]
                if len(items) == 1:
                    spots = [(left + 250, cy)]
                ibox = (300, 220)
            else:
                w, h = min(940, 240 * cols), min(600, 150 * len(rows))
                tx, ty = cx, (870 if items else cy)
                spots = [(cx - 230, 470), (cx + 230, 470)] if len(items) > 1 else [(cx, 470)]
                ibox = (260, 190)
            marks.append({"kind": "table", "role": "table", "rows": rows,
                          "x": ox + tx, "y": oy + ty, "w": w, "h": h})
            for (x, y), it in zip(spots, items[:2]):
                add(_place(it["key"], 0, x, y, ibox, aspects, tilt, origin, it.get("label"), 12,
                           44))

    elif layout == "scene":
        # A puppet play: the backdrop fills the stage, up to three players
        # stand on its floor facing the middle, and props sit between them.
        if backdrop:
            placed.append({"key": backdrop, "copy": 0, "x": ox + f.w / 2, "y": oy + f.h / 2,
                           "w": f.w, "h": f.h, "rot": 0, "layer": "back"})
        if wide:
            spots = {"left": cx - 520, "centre": cx, "right": cx + 520}
            person, prop = (420, 660), (300, 280)
        else:
            spots = {"left": 250, "centre": 540, "right": 830}
            person, prop = (380, 820), (260, 300)
        taken = set()
        people = [it for it in items if it.get("role") != "prop"][:3]
        props = [it for it in items if it.get("role") == "prop"][:2]
        free = [r for r in ("left", "right", "centre") if r not in
                {it.get("role") for it in people}]
        for it in people:
            role = it.get("role") if it.get("role") in spots and it.get("role") not in taken \
                else (free.pop(0) if free else "centre")
            taken.add(role)
            x = spots[role]
            w, h = fit(aspects.get(it["key"], 0.55), *person)
            placed.append({"key": it["key"], "copy": 0, "x": ox + x, "y": oy + f.floor - h / 2,
                           "w": w, "h": h, "rot": 0, "flip": -1 if role == "right" else 1})
        gaps = [x for r, x in sorted(spots.items(), key=lambda kv: kv[1]) if r not in taken]
        between = [(spots["left"] + spots["centre"]) / 2, (spots["centre"] + spots["right"]) / 2]
        gaps = gaps or between
        for it, x in zip(props, gaps + between):
            w, h = fit(aspects.get(it["key"], 1.0), *prop)
            placed.append({"key": it["key"], "copy": 0, "x": ox + x, "y": oy + f.floor - h / 2,
                           "w": w, "h": h, "rot": 0})
        if caption:
            marks.append({"kind": "label", "role": "caption", "text": caption,
                          "x": ox + f.w / 2, "y": oy + f.title_y, "chars": 22 if not wide else 36})

    elif layout == "diagram":
        # The diagram fills its box (compositor.diagrams draws it); up to
        # two pictures sit above it, or beside it in a wide frame.
        box = diagram_box(f, len(items), bool(title))
        if items:
            if wide:
                spots = [(left + 220, cy)] if len(items) == 1 else \
                    [(left + 220, cy - 165), (left + 220, cy + 175)]
                ibox = (380, 400) if len(items) == 1 else (340, 230)
            else:
                spots = [(cx, top + 130)] if len(items) == 1 else \
                    [(cx - 230, top + 130), (cx + 230, top + 130)]
                ibox = (420, 220) if len(items) == 1 else (330, 210)
            for (x, y), it in zip(spots, items[:2]):
                add(_place(it["key"], 0, x, y, ibox, aspects, tilt, origin, it.get("label"), 12,
                           40))
        marks.append({"kind": "diagram", "role": "diagram",
                      "box": [ox + box[0], oy + box[1], ox + box[2], oy + box[3]]})

    # Anything that speaks or thinks gets a bubble over its head (in a
    # lineup, each figure its own), kept clear of the title and the edges.
    by_ident = {(it["key"], it.get("_copy", 0)): it for it in reversed(items)}
    ceiling = oy + (f.title_y + 70 if title or caption else 30)
    for p in placed:
        it = by_ident.get((p["key"], p["copy"]))
        if it and it.get("says") and p.get("layer") != "back":
            marks.append({"kind": "bubble", "role": "bubble", "anchor": (p["key"], p["copy"]),
                          "text": it["says"], "thinks": bool(it.get("thinks")),
                          "x": p["x"] + (p["w"] * 0.12 if p.get("flip", 1) > 0 else -p["w"] * 0.12),
                          "y": p["y"] - p["h"] / 2 - 10, "min_y": ceiling,
                          "min_x": ox + 24, "max_x": ox + f.w - 24})
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
