"""
Beats to a stage: the timed data runtime.js plays.

Everything is timed to the narration's real words. Each object arrives
on the word that names it; its label is written in once it has landed;
arrows and symbols follow once both their ends are there. What happens
between beats depends on the format:

- **move** (tabletop): an object that's still needed moves to its new
  place, and one that isn't slides off the table. The table is one
  continuous performance, never a cut.
- **persist** (canvas): each beat has its own area of a large canvas and
  the camera travels there; what was drawn stays behind, so the video
  builds a picture the way a good explainer does.

Times here are seconds from the start of the animated window.
"""

from __future__ import annotations

import math

from pipeline.animation.compositor import layouts

W, H = 1080, 1920
AREA_GAP = 260
CANVAS_COLUMNS = 3
LAND = 0.55            # seconds for an arrival
MOVE = 0.7             # seconds for a carried object to reach its new place
EXIT = 0.45


def area_origin(index: int, mode: str) -> tuple:
    if mode != "canvas":
        return 0, 0
    row, col = divmod(index, CANVAS_COLUMNS)
    if row % 2:                                   # snake, so each move is to a neighbour
        col = CANVAS_COLUMNS - 1 - col
    return col * (W + AREA_GAP), row * (H + AREA_GAP)


def world_size(beats: int, mode: str) -> dict:
    if mode != "canvas":
        return {"w": W, "h": H}
    rows = math.ceil(max(1, beats) / CANVAS_COLUMNS)
    cols = min(CANVAS_COLUMNS, max(1, beats))
    return {"w": cols * W + (cols - 1) * AREA_GAP, "h": rows * H + (rows - 1) * AREA_GAP}


def word_time(words: list, index: int, origin: float) -> float:
    return max(0.0, words[index].start - origin) if 0 <= index < len(words) else 0.0


def build(beats: list, words: list, origin: float, duration: float, aspects: dict,
          fmt: dict, style: dict) -> dict:
    """The stage for one animated window.

    `beats`: settled storyboard beats (pipeline.animation.beats), each with
    "start", "end" (narration seconds), "layout", "items", "title",
    "relation", "avatar". `aspects`: {kit key: width/height}. `fmt`: the
    format; `style`: the resolved label style, surface and shadow."""
    mode = fmt.get("areas", "single")
    continuity = fmt.get("continuity", "move")
    entrance = fmt.get("entrance", "drop")
    sprites = {}             # (key, copy, area) -> sprite
    marks, camera, avatar_keys, talk = [], [], [], []
    previous = {}            # (key, copy) -> placement, on the table now
    tilt = fmt.get("tilt", 3.0)

    for b_index, beat in enumerate(beats):
        t0 = max(0.0, beat["start"] - origin)
        t1 = min(duration, beat["end"] - origin)
        origin_xy = area_origin(b_index, mode)
        placed, beat_marks = layouts.arrange(beat["layout"], beat["items"], aspects, origin_xy,
                                             beat.get("relation", ""), beat.get("title", ""),
                                             tilt)
        arrive = _arrivals(beat, placed, words, origin, t0, t1)
        now = {(p["key"], p["copy"]): p for p in placed}

        # --- objects
        if continuity == "move":
            for ident, p in previous.items():
                if ident not in now:
                    _exit(sprites[(ident[0], ident[1], 0)], p, t0)
        for p in placed:
            ident = (p["key"], p["copy"])
            area = 0 if continuity == "move" else b_index
            sid = (p["key"], p["copy"], area)
            if continuity == "move" and ident in previous:
                _move(sprites[sid], previous[ident], p, t0, arrive[ident])
            elif sid in sprites:
                # Back on the table after leaving it: the same object again.
                _enter(sprites[sid], p, arrive[ident], entrance, style, again=True)
            else:
                sp = _new_sprite(p, sid, style)
                sprites[sid] = sp
                _enter(sp, p, arrive[ident], entrance, style)
        previous = now if continuity == "move" else {}

        # --- marks
        for m in beat_marks:
            m = dict(m)
            anchor = m.pop("anchor", None)
            role = m.pop("role", "")
            landed = arrive.get(tuple(anchor), t0) + LAND if anchor else t0
            if role == "title" or role == "statement":
                m["t0"], m["draw"] = t0 + 0.12, 0.6
            elif role == "relation":
                ends = [arrive.get(k, t0) for k in arrive]
                m["t0"], m["draw"] = max(landed, max(ends) + LAND * 0.6 if ends else landed), 0.45
            elif role == "highlight":
                m["t0"], m["draw"] = landed + 0.35, 0.55
            else:
                m["t0"], m["draw"] = landed + 0.1, 0.5
            m["t0"] = round(min(m["t0"], max(t0, t1 - 0.5)), 3)
            m["t1"] = round(t1 + 0.05, 3) if continuity == "move" else None
            m["id"] = f"b{b_index}_{len(marks)}"
            marks.append(m)

        # --- camera
        cx, cy = origin_xy[0] + W / 2, origin_xy[1] + H / 2
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
            focus = _focus(placed, cx, cy)
            camera.append({"t": round(t0, 3), "x": cx, "y": cy, "zoom": 1.0, "ease": "inout"})
            camera.append({"t": round(max(t0 + 0.4, t1 - 0.35), 3), "x": focus[0], "y": focus[1],
                           "zoom": 1.04, "ease": "inout"})

        # --- the narrator
        pose = beat.get("avatar") or ""
        if fmt.get("avatar"):
            avatar_keys.append({"t": round(t0, 3), "pose": pose or None,
                                "x": origin_xy[0] + 300, "y": origin_xy[1] + 1270})
            if pose:
                talk += _talking(words, origin, t0, t1)

    stage = {
        "duration": round(duration, 3),
        "world": world_size(len(beats), mode),
        "step": style["step"], "jitter": style["jitter"],
        "camera_stepped": style["step"] > 0 and mode != "canvas",
        "surface": style["surface"], "shadow": style["shadow"], "labels": style["labels"],
        "camera": _tidy(camera),
        "sprites": list(sprites.values()),
        "marks": marks,
    }
    if fmt.get("avatar") and style.get("avatar"):
        stage["avatar"] = {**style["avatar"], "keys": avatar_keys, "talk": _merge(talk)}
    return stage


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
        # The beat's first object opens it (never an empty table while the
        # words catch up); the rest arrive on their words, but in time to
        # be seen.
        cap = t0 + (0.25 if p["key"] == first_key else 0.6) * length
        base = min(max(t0, base - 0.12), cap, latest)
        n = used.get(p["key"], 0)
        used[p["key"]] = n + 1
        out[(p["key"], p["copy"])] = round(min(base + n * 0.07, latest + 0.3), 3)
    return out


def _new_sprite(p, sid, style) -> dict:
    return {"id": f"{sid[0]}_{sid[1]}_{sid[2]}", "src": p["key"], "w": p["w"], "h": p["h"],
            "z": 1 + sid[1] % 5, "idle": style.get("idle", "none"), "keys": []}


def _enter(sp, p, t, entrance, style, again=False):
    """Keys that bring an object on at time t. `again`: it has been on
    before (and left), so it starts hidden from wherever it went."""
    keys = _entrance(p, t, entrance)
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


def _entrance(p, t, entrance) -> list:
    x, y, rot = p["x"], p["y"], p["rot"]
    ax, ay = p.get("from") or (x, y)            # a traveller arrives at its start
    start = {"rot": rot, "scale": 1.0, "alpha": 0, "lift": 0}
    t = round(t, 3)
    if entrance == "drop":                      # set down from above onto the table
        keys = [{"t": 0, "x": ax, "y": ay - 40, **start, "scale": 1.22, "lift": 1},
                {"t": t, "x": ax, "y": ay - 40, "scale": 1.22, "lift": 1, "alpha": 0},
                {"t": round(t + 0.06, 3), "alpha": 1},
                {"t": round(t + LAND, 3), "x": ax, "y": ay, "scale": 1.0, "lift": 0,
                 "rot": rot, "ease": "land"}]
    elif entrance == "slide":                   # pushed on from the nearer side
        side = -p["w"] if ax < W / 2 else W + p["w"]
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


def _move(sp, old, new, t0, t):
    """A carried object walks to its new place (and size) as the beat turns."""
    start = round(max(t0, t - 0.15), 3)
    sp["keys"].append({"t": start, "x": old["x"], "y": old["y"], "rot": old["rot"], "lift": 0,
                       "scale": 1.0 * old["w"] / sp["w"]})
    sp["keys"].append({"t": round(start + MOVE, 3), "x": new["x"], "y": new["y"],
                       "rot": new["rot"], "scale": new["w"] / sp["w"], "lift": 0,
                       "ease": "inout", "hop": 26})


def _exit(sp, p, t0):
    side = -p["w"] if p["x"] < W / 2 else W + p["w"]
    start = round(max(0.0, t0 - 0.05), 3)
    # Fully there until it goes: without this key its fade would be spread
    # over its whole time on the table.
    sp["keys"].append({"t": start, "x": p["x"], "y": p["y"], "lift": 0, "alpha": 1})
    sp["keys"].append({"t": round(start + EXIT, 3), "x": side, "y": p["y"] - 30, "lift": 0.35,
                       "ease": "in"})
    sp["keys"].append({"t": round(start + EXIT + 0.01, 3), "alpha": 0})


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


def _tidy(camera) -> list:
    out = []
    for k in sorted(camera, key=lambda k: k["t"]):
        if out and abs(out[-1]["t"] - k["t"]) < 1e-3:
            out[-1] = k
        else:
            out.append(k)
    return out or [{"t": 0, "x": W / 2, "y": H / 2, "zoom": 1.0}]


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
