"""
Beats to a stage: the timed data runtime.js plays.

Everything is timed to the narration's real words. Each object arrives
on the word that names it (a beat's first opens it); its label is written
in once it has landed; arrows, symbols and bubbles follow. What happens
between beats is the style's continuity:

- **move** (tabletop, board, model world): an object still needed moves
  to its new place, one that isn't leaves. One continuous performance.
- **fade** (a plain background): the same, but what isn't needed fades
  away rather than being carried off. Calm and exact.
- **persist** (a canvas): each beat has its own area of a large canvas and
  the camera travels there; what was drawn stays behind.
- **clear** (a whiteboard, chalkboard, notebook): the board is wiped and
  the next idea drawn fresh.
- **scene** (a puppet stage): a backdrop stays while the place does;
  puppets walk on and off from the wings, turn to each other, and rock as
  they speak; a new place slides in like a painted flat.

How things arrive is the style's entrance: set down from above (drop),
pressed on (pin), pushed on (slide), popped (pop), drawn in (draw), faded
up (fade), or walked on (puppet).

A beat's diagram (compositor.diagrams) is drawn element by element on its
words. When the next beat continues the same diagram, what's unchanged
stays, what changed moves (bars to new heights, points along the line)
and only what's new is drawn: an idea built up rather than a cut.

Times here are seconds from the start of the window; positions are in the
frame the stage is made for (pipeline.animation.frame).
"""

from __future__ import annotations

import math

from pipeline.animation import frame as frames
from pipeline.animation.compositor import diagrams, layouts

AREA_GAP = 260
CANVAS_COLUMNS = 3
LAND = 0.55            # seconds for an arrival
MOVE = 0.7             # seconds for a carried object to reach its new place
EXIT = 0.45
FADE = 0.4             # a plain background's arrivals and departures
WALK = 1.1             # seconds for a puppet to walk on from the wings
ERASE = 0.3
TRANSFORM = 0.65       # a continued diagram's bar or point moving to its new value
CARRIES = ("move", "fade", "scene")


def area_origin(index: int, mode: str, frame=None) -> tuple:
    if mode != "canvas":
        return 0, 0
    f = frames.get(frame)
    row, col = divmod(index, CANVAS_COLUMNS)
    if row % 2:                                   # snake, so each move is to a neighbour
        col = CANVAS_COLUMNS - 1 - col
    return col * (f.w + AREA_GAP), row * (f.h + AREA_GAP)


def world_size(beats: int, mode: str, frame=None) -> dict:
    f = frames.get(frame)
    if mode != "canvas":
        return {"w": f.w, "h": f.h}
    rows = math.ceil(max(1, beats) / CANVAS_COLUMNS)
    cols = min(CANVAS_COLUMNS, max(1, beats))
    return {"w": cols * f.w + (cols - 1) * AREA_GAP, "h": rows * f.h + (rows - 1) * AREA_GAP}


def host_spot(frame=None) -> dict:
    """Where the host stands (feet) and how tall, in this frame."""
    f = frames.get(frame)
    return {"x": 300, "y": 1270, "h": 900} if f.vertical else {"x": 360, "y": 1070, "h": 820}


def word_time(words: list, index: int, origin: float) -> float:
    return max(0.0, words[index].start - origin) if 0 <= index < len(words) else 0.0


def build(beats: list, words: list, origin: float, duration: float, aspects: dict,
          fmt: dict, style: dict) -> dict:
    """The stage for one animated window.

    `beats`: settled storyboard beats (pipeline.animation.beats), each with
    "start", "end" (narration seconds), "layout", "items", "title",
    "relation", "avatar", and for tables, scenes and diagrams "table",
    "backdrop", "caption" and "diagram". `aspects`: {kit key:
    width/height}. `fmt`: the compiled style's engine half, with the frame
    it's made for; `style`: its compositor theme (compositor.theme). The
    stage's "math" names the typeset pictures its diagrams need."""
    f = frames.get(fmt.get("frame"))
    mode = fmt.get("areas", "single")
    continuity = fmt.get("continuity", "move")
    entrance = fmt.get("entrance", "drop")
    carries = continuity in CARRIES
    sprites = {}             # sprite id -> sprite
    marks, camera, avatar_keys, talk = [], [], [], []
    previous = {}            # (key, copy) -> (placement, sprite id), on stage now
    backdrop = None          # (key, sprite id) behind a puppet scene now
    tilt = fmt.get("tilt", 3.0)
    no_labels = fmt.get("no_labels")
    ink = style.get("diagram") or {"ink": style["labels"].get("color", "#2B2A33"),
                                   "accent": style["labels"].get("accent", "#E4572E")}
    math_assets = {}
    beats = _harmonise(beats)
    live, live_id = {}, None                      # the diagram on screen: pid -> mark
    last_title = None                             # (text, mark) of the title on screen
    host = host_spot(f)

    for b_index, beat in enumerate(beats):
        t0 = max(0.0, beat["start"] - origin)
        t1 = min(duration, beat["end"] - origin)
        origin_xy = area_origin(b_index, mode, f)
        placed, beat_marks = layouts.arrange(
            beat["layout"], beat["items"], aspects, origin_xy, beat.get("relation", ""),
            "" if no_labels else beat.get("title", ""), tilt, table=beat.get("table"),
            backdrop=beat.get("backdrop", ""), caption=beat.get("caption", ""), frame=f)
        boxes = [m["box"] for m in beat_marks if m["kind"] == "diagram"]
        beat_marks = [m for m in beat_marks if m["kind"] != "diagram"]
        backs = [p for p in placed if p.get("layer") == "back"]
        placed = [p for p in placed if p.get("layer") != "back"]
        arrive = _arrivals(beat, placed, words, origin, t0, t1)
        now = {(p["key"], p["copy"]): p for p in placed}

        # --- the scenery: a new place slides in like a painted flat
        if backs and (backdrop is None or backs[0]["key"] != backdrop[0]):
            b = backs[0]
            sid = f"back_{b['key']}_{b_index}"
            slide_in = round(max(0.0, t0 - 0.2), 3) if backdrop else 0.0
            sprites[sid] = {"id": sid, "src": b["key"], "w": f.w, "h": f.h, "layer": "back",
                            "keys": [{"t": 0, "x": f.w / 2 + (f.w if backdrop else 0), "y": f.h / 2,
                                      "rot": 0, "scale": 1.0, "alpha": 1, "lift": 0},
                                     {"t": slide_in, "x": f.w / 2 + (f.w if backdrop else 0)},
                                     {"t": round(slide_in + 0.8, 3), "x": f.w / 2, "ease": "inout"}]}
            if backdrop:
                old = sprites[backdrop[1]]
                old["keys"] += [{"t": slide_in, "x": f.w / 2},
                                {"t": round(slide_in + 0.8, 3), "x": -f.w / 2, "ease": "inout"}]
            backdrop = (b["key"], sid)

        # --- objects and players
        if carries:
            for ident, (p, sid) in previous.items():
                if ident not in now:
                    _exit(sprites[sid], p, t0, continuity, f)
        elif continuity == "clear":
            for ident, (p, sid) in previous.items():
                _erase(sprites[sid], t0)
        entered = {}
        for p in placed:
            ident = (p["key"], p["copy"])
            sid = f"{p['key']}_{p['copy']}" if carries else f"{p['key']}_{p['copy']}_{b_index}"
            if carries and ident in previous:
                _move(sprites[sid], previous[ident][0], p, t0, arrive[ident], continuity)
            elif sid in sprites:
                # Back after leaving: the same object again.
                _enter(sprites[sid], p, arrive[ident], entrance, f, again=True)
            else:
                sprites[sid] = _new_sprite(p, sid)
                _enter(sprites[sid], p, arrive[ident], entrance, f)
            entered[ident] = (p, sid)
            speaks = next((it for it in beat["items"] if it["key"] == p["key"] and it.get("says")
                           and it.get("_copy", 0) == p["copy"]), None)
            if speaks and continuity == "scene":
                sprites[sid].setdefault("sway", []).append(
                    [round(arrive[ident] + WALK * 0.8, 3), round(max(t0, t1 - 0.2), 3)])
        previous = entered if continuity != "persist" else {}

        # --- marks
        persist = continuity == "persist"
        for m in beat_marks:
            m = dict(m)
            anchor = m.pop("anchor", None)
            role = m.pop("role", "")
            if no_labels and role in ("label", "caption"):
                continue
            landed = arrive.get(tuple(anchor), t0) + (WALK if entrance == "puppet" else LAND) \
                if anchor else t0
            if role == "title" and not persist and last_title and last_title[0] == m["text"]:
                last_title[1]["t1"] = round(t1 + 0.05, 3)          # the same title stays up
                continue
            if role in ("title", "statement", "caption"):
                m["t0"], m["draw"] = t0 + 0.12, 0.6
            elif role == "table":
                m["t0"], m["draw"] = t0 + 0.2, 1.4
            elif role == "relation":
                ends = [arrive.get(k, t0) for k in arrive]
                m["t0"], m["draw"] = max(landed, max(ends) + LAND * 0.6 if ends else landed), 0.45
            elif role == "highlight":
                m["t0"], m["draw"] = landed + 0.35, 0.55
            elif role == "bubble":
                m["t0"], m["draw"] = landed + 0.3, 0.35
            else:
                m["t0"], m["draw"] = landed + 0.1, 0.5
            m["t0"] = round(min(m["t0"], max(t0, t1 - 0.5)), 3)
            m["t1"] = None if persist else round(t1 + 0.05, 3)
            m["id"] = f"b{b_index}_{len(marks)}"
            marks.append(m)
            if role == "title":
                last_title = (m["text"], m)
        if not any(m.get("role") == "title" for m in beat_marks):
            last_title = None

        # --- the diagram
        diagram = beat.get("diagram")
        if diagram and boxes:
            prims, assets = diagrams.build(diagram, boxes[0], ink, f)
            math_assets.update(assets)
            same = not persist and live_id == diagram["id"]
            live = _diagram_marks(prims, words, origin, t0, t1, live if same else {}, persist,
                                  b_index, marks)
            live_id = diagram["id"]
        else:
            live, live_id = {}, None

        # --- camera
        cx, cy = origin_xy[0] + f.w / 2, origin_xy[1] + f.h / 2
        if mode == "canvas":
            if b_index == 0:
                camera.append({"t": 0.0, "x": cx, "y": cy, "zoom": 1.0})
            else:
                camera.append({"t": round(max(0.0, t0 - 0.45), 3), **_last_view(camera)})
                camera.append({"t": round(t0 + 0.35, 3), "x": cx, "y": cy, "zoom": 1.0,
                               "ease": "inout"})
            camera.append({"t": round(t1, 3), "x": cx, "y": cy - 12, "zoom": 1.035,
                           "ease": "linear"})
        else:
            push = {"move": 1.04, "fade": 1.015}.get(continuity, 1.025)
            focus = _focus(placed, cx, cy)
            camera.append({"t": round(t0, 3), "x": cx, "y": cy, "zoom": 1.0, "ease": "inout"})
            camera.append({"t": round(max(t0 + 0.4, t1 - 0.35), 3), "x": focus[0], "y": focus[1],
                           "zoom": push, "ease": "inout"})

        # --- the host
        pose = beat.get("avatar") or ""
        if fmt.get("avatar"):
            avatar_keys.append({"t": round(t0, 3), "pose": pose or None,
                                "x": origin_xy[0] + host["x"], "y": origin_xy[1] + host["y"]})
            if pose:
                talk += _talking(words, origin, t0, t1)

    for m in marks:
        for k in [k for k in m if k.startswith("_")]:
            del m[k]
    stage = {
        "duration": round(duration, 3),
        "frame": {"w": f.w, "h": f.h},
        "world": world_size(len(beats), mode, f),
        "step": style["step"], "jitter": style["jitter"],
        "camera_stepped": style["step"] > 0 and mode != "canvas",
        "depth_sort": bool(style.get("depth_sort")),
        "surface": style["surface"], "shadow": style["shadow"], "labels": style["labels"],
        "camera": _tidy(camera, f),
        "sprites": list(sprites.values()),
        "marks": marks,
        "math": {name: str(path) for name, path in math_assets.items()},
    }
    if fmt.get("avatar") and style.get("avatar"):
        stage["avatar"] = {**style["avatar"], **host, "keys": avatar_keys, "talk": _merge(talk)}
    return stage


# --- diagrams --------------------------------------------------------------------------

def _harmonise(beats: list) -> list:
    """A diagram continued over several beats keeps one scale throughout
    (a chart's axes, a number line's range, a plot's window), so what
    changes moves rather than the whole thing being redrawn."""
    out, run = [dict(b) for b in beats], []

    def close(run):
        ds = [b["diagram"] for b in run]
        kind = ds[0]["kind"]
        if len(ds) < 2 or kind not in ("chart", "number_line", "plot"):
            return
        if kind == "chart":
            values = [bar["value"] for d in ds for bar in d["bars"]]
            scale = (min(0.0, min(values)), max(0.0, max(values)))
            for b in run:
                b["diagram"] = dict(b["diagram"], scale=scale)
        else:
            lo = min(d["range"][0] for d in ds)
            hi = max(d["range"][1] for d in ds)
            for b in run:
                b["diagram"] = dict(b["diagram"], range=(lo, hi))
            if kind == "plot" and all(d.get("y_range") for d in ds):
                ylo = min(d["y_range"][0] for d in ds)
                yhi = max(d["y_range"][1] for d in ds)
                for b in run:
                    b["diagram"] = dict(b["diagram"], y_range=(ylo, yhi))

    for b in out + [{"diagram": None}]:
        d = b.get("diagram")
        if run and (not d or d["id"] != run[0]["diagram"]["id"] or d["kind"] != run[0]["diagram"]["kind"]):
            close(run)
            run = []
        if d:
            run.append(b)
    return out


def _length(points) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def _draw_time(p) -> float:
    kind = p["kind"]
    if kind == "math":
        return round(min(1.4, max(0.45, p["w"] / 700)), 3)
    if kind == "stroke":
        return round(min(1.1, max(0.3, _length(p["points"]) / 1400)), 3)
    return {"bar": 0.6, "dot": 0.3, "text": 0.3, "area": 0.6}.get(kind, 0.4)


def _shape(p) -> tuple:
    """What a primitive looks like, to tell unchanged from changed."""
    kind = p["kind"]
    if kind == "stroke":
        return ("stroke", tuple(map(tuple, p["points"])), p.get("color"), p.get("arrow"))
    if kind == "area":
        return ("area", tuple(map(tuple, p["points"])), p.get("color"))
    if kind == "bar":
        return ("bar", round(p["x"]), round(p["base"]), round(p["w"]), round(p["h"]), p["color"])
    if kind == "dot":
        return ("dot", round(p["x"]), round(p["y"]), p["r"], p["color"], p.get("hollow"))
    if kind == "math":
        return ("math", p["src"], round(p["x"]), round(p["y"]))
    return ("text", p["text"], round(p["x"]), round(p["y"]), p.get("size"))


def _diagram_marks(prims, words, origin, t0, t1, live, persist, b_index, marks) -> dict:
    """Timed marks for a diagram's primitives, carrying on from `live`
    (the same diagram's marks from the beat before); returns what's on
    screen now, by pid. Marks are appended to `marks`."""
    orders = sorted({p["order"] for p in prims})
    span = max(0.6, (t1 - t0) * 0.62)
    gap = min(1.1, span / max(1, len(orders)))
    starts = {o: t0 + 0.15 + k * gap for k, o in enumerate(orders)}
    end = None if persist else round(t1 + 0.05, 3)
    now = {}
    for p in prims:
        start = starts[p["order"]]
        w = p.get("on_word", -1)
        if 0 <= w < len(words) and t0 <= words[w].start - origin < t1:
            start = max(t0 + 0.05, words[w].start - origin - 0.1)
        start = round(min(start + p.get("stagger", 0), max(t0, t1 - 0.6)), 3)
        shape = _shape(p)
        old = live.get(p["pid"])
        if old is not None and old["kind"] == p["kind"]:
            before = old["_shape"]
            if before == shape:                                      # unchanged: it stays
                old["t1"] = end
                now[p["pid"]] = old
                continue
            moved = _transform(old, p, start)
            if moved:
                old["_shape"] = shape
                old["t1"] = end
                now[p["pid"]] = old
                continue
        mark = {k: v for k, v in p.items() if k not in ("pid", "order", "on_word", "stagger",
                                                         "rides")}
        mark.update(t0=start, draw=_draw_time(p), t1=end, id=f"b{b_index}_{len(marks)}",
                    _shape=shape)
        marks.append(mark)
        now[p["pid"]] = mark
    # What the diagram no longer shows fades as the beat turns.
    for pid, mark in live.items():
        if pid not in now:
            mark["t1"] = round(t0 + 0.05, 3)
    return now


def _transform(old: dict, new: dict, start: float) -> bool:
    """Moves a continued diagram's element to its new value (a bar's
    height, a point's place, a label riding with them); False when it
    changed in a way that means drawing it again."""
    kind = old["kind"]
    end = round(start + TRANSFORM, 3)
    if kind == "bar" and (round(old["x"]), round(old["base"]), round(old["w"])) == \
            (round(new["x"]), round(new["base"]), round(new["w"])):
        keys = old.setdefault("keys", [])
        keys += [{"t": start, "h": old.get("_h", old["h"])}, {"t": end, "h": new["h"]}]
        old["_h"] = new["h"]
        return True
    if kind == "dot" and (old["r"], old["color"]) == (new["r"], new["color"]):
        keys = old.setdefault("keys", [])
        was = old.get("_xy", (old["x"], old["y"]))
        keys += [{"t": start, "x": was[0], "y": was[1]}, {"t": end, "x": new["x"], "y": new["y"]}]
        old["_xy"] = (new["x"], new["y"])
        return True
    if kind in ("math", "text") and (old.get("src"), old.get("text")) == \
            (new.get("src"), new.get("text")):
        keys = old.setdefault("keys", [])
        was = old.get("_xy", (old["x"], old["y"]))
        keys += [{"t": start, "x": was[0], "y": was[1]}, {"t": end, "x": new["x"], "y": new["y"]}]
        old["_xy"] = (new["x"], new["y"])
        return True
    return False


# --- objects ----------------------------------------------------------------------------

def _arrivals(beat, placed, words, origin, t0, t1) -> dict:
    """When each placed object arrives: on the word that names it, copies
    of one object in quick succession, never too late to be seen."""
    by_key = {}
    for it in beat["items"]:
        by_key.setdefault(it["key"], it)
    out, used = {}, {}
    latest = max(t0, t1 - LAND - 0.35)
    length = max(0.1, t1 - t0)
    first_key = placed[0]["key"] if placed else None
    for p in placed:
        it = by_key.get(p["key"], {})
        base = word_time(words, it.get("on_word", -1), origin) if it.get("on_word", -1) >= 0 else t0
        # The beat's first object opens it (never an empty stage while the
        # words catch up); the rest arrive on their words, but in time to
        # be seen.
        cap = t0 + (0.25 if p["key"] == first_key else 0.6) * length
        base = min(max(t0, base - 0.12), cap, latest)
        n = used.get(p["key"], 0)
        used[p["key"]] = n + 1
        out[(p["key"], p["copy"])] = round(min(base + n * 0.07, latest + 0.3), 3)
    return out


def _new_sprite(p, sid) -> dict:
    return {"id": sid, "src": p["key"], "w": p["w"], "h": p["h"],
            "z": 1 + p["copy"] % 5, "idle": "none", "keys": []}


def _enter(sp, p, t, entrance, frame=None, again=False):
    """Keys that bring something on at time t. `again`: it has been on
    before (and left), so it starts hidden from wherever it went."""
    keys = _entrance(p, t, entrance, frame)
    factor = p["w"] / sp["w"]                  # a returning object may be placed at a new size
    for k in keys:
        if "scale" in k:
            k["scale"] = round(k["scale"] * factor, 4)
    if again:
        # The time-0 key belongs to a first appearance: fold its full
        # starting state into the arrival's first key instead.
        first, keys = keys[0], keys[1:]
        keys[0] = {**first, **keys[0]}
    sp["keys"] += keys


def _entrance(p, t, entrance, frame=None) -> list:
    width = frames.get(frame).w
    x, y, rot = p["x"], p["y"], p["rot"]
    ax, ay = p.get("from") or (x, y)            # a traveller arrives at its start
    flip = p.get("flip", 1)
    start = {"rot": rot, "scale": 1.0, "alpha": 0, "lift": 0, "flip": flip, "reveal": 1}
    t = round(t, 3)
    if entrance == "drop":                      # set down from above
        keys = [{"t": 0, "x": ax, "y": ay - 40, **start, "scale": 1.22, "lift": 1},
                {"t": t, "x": ax, "y": ay - 40, "scale": 1.22, "lift": 1, "alpha": 0},
                {"t": round(t + 0.06, 3), "alpha": 1},
                {"t": round(t + LAND, 3), "x": ax, "y": ay, "scale": 1.0, "lift": 0,
                 "rot": rot, "ease": "land"}]
    elif entrance == "pin":                     # pressed onto the board
        keys = [{"t": 0, "x": ax, "y": ay - 12, **start, "scale": 1.1, "lift": 0.5},
                {"t": t, "x": ax, "y": ay - 12, "scale": 1.1, "lift": 0.5, "alpha": 0},
                {"t": round(t + 0.05, 3), "alpha": 1},
                {"t": round(t + 0.32, 3), "x": ax, "y": ay, "scale": 1.0, "lift": 0,
                 "ease": "back"}]
    elif entrance == "draw":                    # drawn in, as if by hand
        keys = [{"t": 0, "x": ax, "y": ay, **start, "reveal": 0},
                {"t": t, "x": ax, "y": ay, "reveal": 0, "alpha": 0},
                {"t": round(t + 0.02, 3), "alpha": 1},
                {"t": round(t + 0.85, 3), "reveal": 1, "ease": "inout"}]
    elif entrance == "fade":                    # faded up, settling a hair
        keys = [{"t": 0, "x": ax, "y": ay + 10, **start, "scale": 0.97},
                {"t": t, "x": ax, "y": ay + 10, "scale": 0.97, "alpha": 0},
                {"t": round(t + FADE, 3), "x": ax, "y": ay, "scale": 1.0, "alpha": 1,
                 "ease": "out"}]
    elif entrance == "puppet":                  # walks on from the nearer wing
        wing = -p["w"] / 2 - 40 if ax < width / 2 else width + p["w"] / 2 + 40
        way = 1 if ax > wing else -1
        mid = (wing + ax) / 2
        keys = [{"t": 0, "x": wing, "y": ay, **start, "alpha": 1, "flip": way},
                {"t": t, "x": wing, "y": ay, "flip": way},
                {"t": round(t + WALK / 2, 3), "x": mid, "y": ay, "ease": "linear", "hop": 18},
                {"t": round(t + WALK, 3), "x": ax, "y": ay, "ease": "out", "hop": 18},
                {"t": round(t + WALK + 0.01, 3), "flip": flip}]
    elif entrance == "slide":                   # pushed on from the nearer side
        side = -p["w"] if ax < width / 2 else width + p["w"]
        keys = [{"t": 0, "x": side, "y": ay, **start, "alpha": 1, "lift": 0.25},
                {"t": t, "x": side, "y": ay, "lift": 0.25, "alpha": 1},
                {"t": round(t + LAND * 1.3, 3), "x": ax, "y": ay, "lift": 0, "ease": "out",
                 "hop": 30}]
    else:                                       # pop: flat graphics
        keys = [{"t": 0, "x": ax, "y": ay, **start, "scale": 0.0},
                {"t": t, "x": ax, "y": ay, "scale": 0.0, "alpha": 0},
                {"t": round(t + 0.05, 3), "alpha": 1},
                {"t": round(t + LAND * 0.8, 3), "scale": 1.0, "ease": "back"}]
    if p.get("from"):                           # then along its path to where it's going
        keys.append({"t": round(t + LAND + 0.25, 3), "x": ax, "y": ay})
        keys.append({"t": round(t + LAND + 1.6, 3), "x": x, "y": y, "ease": "inout", "hop": 70})
    return keys


def _move(sp, old, new, t0, t, continuity):
    """A carried object goes to its new place (and size) as the beat turns;
    a puppet walks there, facing the way it goes, then turns back."""
    start = round(max(t0, t - 0.15), 3)
    walking = continuity == "scene" and abs(new["x"] - old["x"]) > 20
    first = {"t": start, "x": old["x"], "y": old["y"], "rot": old["rot"], "lift": 0,
             "scale": 1.0 * old["w"] / sp["w"]}
    if walking:
        first["flip"] = 1 if new["x"] > old["x"] else -1
    sp["keys"].append(first)
    end = round(start + (WALK if walking else MOVE), 3)
    sp["keys"].append({"t": end, "x": new["x"], "y": new["y"], "rot": new["rot"],
                       "scale": new["w"] / sp["w"], "lift": 0, "ease": "inout",
                       "hop": 16 if walking else (0 if continuity == "fade" else 26)})
    if walking or "flip" in new:
        sp["keys"].append({"t": round(end + 0.01, 3), "flip": new.get("flip", 1)})


def _exit(sp, p, t0, continuity="move", frame=None):
    width = frames.get(frame).w
    side = -p["w"] if p["x"] < width / 2 else width + p["w"]
    start = round(max(0.0, t0 - 0.05), 3)
    # Fully there until it goes: without this key its fade would be spread
    # over its whole time on stage.
    first = {"t": start, "x": p["x"], "y": p["y"], "lift": 0, "alpha": 1}
    if continuity == "scene":                   # walks off into the nearer wing
        first["flip"] = -1 if side < 0 else 1
        sp["keys"].append(first)
        sp["keys"].append({"t": round(start + WALK, 3), "x": side, "y": p["y"], "ease": "in",
                           "hop": 18})
        sp["keys"].append({"t": round(start + WALK + 0.01, 3), "alpha": 0})
        return
    if continuity == "fade":                    # simply fades where it stands
        sp["keys"].append(first)
        sp["keys"].append({"t": round(start + FADE * 0.8, 3), "alpha": 0, "ease": "in"})
        return
    sp["keys"].append(first)
    sp["keys"].append({"t": round(start + EXIT, 3), "x": side, "y": p["y"] - 30, "lift": 0.35,
                       "ease": "in"})
    sp["keys"].append({"t": round(start + EXIT + 0.01, 3), "alpha": 0})


def _erase(sp, t0):
    """Wiped off the board as the next idea begins."""
    start = round(max(0.0, t0 - 0.05), 3)
    sp["keys"].append({"t": start, "alpha": 1})
    sp["keys"].append({"t": round(start + ERASE, 3), "alpha": 0, "ease": "in"})


def _focus(placed, cx, cy) -> tuple:
    """A gentle push towards what the beat is about, never far."""
    if not placed:
        return cx, cy
    mx = sum(p["x"] for p in placed) / len(placed)
    my = sum(p["y"] for p in placed) / len(placed)
    return cx + (mx - cx) * 0.25, cy + (my - cy) * 0.25


def _last_view(camera) -> dict:
    last = camera[-1]
    return {"x": last["x"], "y": last["y"], "zoom": last["zoom"]}


def _tidy(camera, frame=None) -> list:
    f = frames.get(frame)
    out = []
    for k in sorted(camera, key=lambda k: k["t"]):
        if out and abs(out[-1]["t"] - k["t"]) < 1e-3:
            out[-1] = k
        else:
            out.append(k)
    return out or [{"t": 0, "x": f.w / 2, "y": f.h / 2, "zoom": 1.0}]


def _talking(words, origin, t0, t1) -> list:
    return [(round(max(t0, w.start - origin), 3), round(min(t1, w.end - origin), 3))
            for w in words if t0 <= w.start - origin < t1]


def _merge(spans) -> list:
    out = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] < 0.12:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out
