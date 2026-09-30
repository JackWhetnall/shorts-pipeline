"""
The storyboard for composited styles: one call writes the explanation
as beats (decisions 052, 053).

A beat is one clear picture for a stretch of narration: a designed layout
(pipeline.animation.compositor.layouts) filled with things from the kit,
their labels, a title, what joins them, who speaks, and the spoken word
each thing arrives on. The model chooses and fills; it never places
anything. The layouts it may use, and how it should think, come from the
channel's compiled style (pipeline.animation.style): a tabletop
demonstration, a diagram canvas, a whiteboard, a puppet play.

`settle` then makes the beats safe: cut on real words inside the animated
stretches, long enough to read, layouts that fit their contents and the
style, things that exist in the kit, words that fall inside their beat,
tables and bubbles that fit on screen.
"""

from __future__ import annotations

import re

from core.logging_setup import get_logger
from pipeline.animation import frame as frames
from pipeline.animation.compositor import diagrams, layouts
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

POSES = ("", "talk", "point", "shrug", "think")
KINDS = ("object", "character", "backdrop")
MIN_BEAT = 1.6
LEAD = 0.1
MAX_TOKENS = 16000
EFFORT = "medium"

GUIDE = """
You are directing an animated explainer as a sequence of beats. The narration is finished and
timed. Each beat is one clear picture for the words it covers, built from designed layouts
filled with things from a kit, labels and a title. The layouts place everything; you choose the
layout and fill it. Make it genuinely good: clear, clever and fun to watch, the picture always
adding to the words rather than repeating them.

WRITING THE BEATS
- One idea per beat, and change beat when the thought turns: about {mean} seconds each, never
  under two. The first beat is the hook: the most intriguing picture you can make of the opening
  line. The last beat lands the idea.
- Vary the layouts; never the same layout three times running.
- Everything shown is drawn once and reused: give each thing a key (lowercase, underscores) and,
  in the kit, a name, a kind (object, character or backdrop) and a short visual description for
  drawing it (shape, colour, one telling detail). Reuse the channel's existing kit by exactly the
  same key whenever one fits. A thing in a different state is a different thing in the kit (a
  meeple wearing a red hat is not the plain meeple).
- Labels: one to three words, exactly as they should appear. Only words or numbers the narration
  says or directly implies; never invent facts, figures, dates or names.
- Titles: at most five words, and only where they help: a question at the hook, a key term, the
  answer. Leave empty otherwise.
- on_word: the index of the spoken word that names or introduces the thing, so it arrives as
  it's said; -1 if nothing does.
- says: a few words a character says or thinks, in a bubble over them, when that makes the idea
  clearer (a guess, a choice, a reaction); set thinks for a thought. Leave it empty otherwise;
  most things say nothing. Never repeat the narration word for word.
- A beat starts on a spoken word (start_word) where the thought turns. Beats fall only inside
  stretches marked ANIMATE, and every ANIMATE stretch begins with a beat on its first word.
- relation: vs, plus, equals, arrow, or empty. highlight: true only to circle one in a group.
  count: how many copies (1 unless the layout shows several). role: only for scenes.
  table: only for the table layout, rows of short cells (the first row and column are headings).
  backdrop and caption: only for scenes. avatar: only for presenter beats.
""".strip()

LAYOUT_GUIDE = {
    "hero": "hero: one thing, big, with its label. Introducing a thing. With count > 1, a crowd of it.",
    "pair": "pair: two things side by side, joined by a relation: vs (a contrast), plus (combining), "
            "equals (what it amounts to), arrow (this leads to that). Either side can be several copies.",
    "row": "row: two or three things in a row, joined by arrows (a sequence) or plus signs, or nothing.",
    "grid": "grid: four to six things, each labelled: examples, kinds, parts of a set.",
    "steps": "steps: two to four numbered steps, top to bottom, each a thing and a label: a process.",
    "cycle": "cycle: three to five things round a circle, joined by arrows: a loop that repeats.",
    "group": "group: many copies of one thing (count up to 30), one circled when highlight is true: "
             "a proportion (\"1 in 10\"), a crowd, a large amount.",
    "travel": "travel: a thing moving along a dotted path, optionally from one thing to another: something "
              "passing, spreading or being sent. Items: the traveller first, then where it starts, "
              "then where it arrives.",
    "scale": "scale: two to four things from small to large: sizes, amounts, growth.",
    "lineup": "lineup: two to eight characters or things standing side by side in one row (the prisoners "
              "in a logic puzzle, the players of a game, a queue), each labelled, any of them able to "
              "speak or think in a bubble.",
    "table": "table: a small grid of words (up to 4 by 4), with up to two things above it: a payoff matrix, "
             "a comparison of options, a tally. The first row and column are headings.",
    "statement": "statement: a short title set big (a number, a two- or three-word answer) with at most one "
                 "small thing: a hook, a punchline, the key fact.",
    "presenter": "presenter: the host on screen with at most one thing; pose talk while explaining, point "
                 "when introducing something, shrug at uncertainty or irony, think for a question.",
    "scene": "scene: a puppet play. backdrop: the key of the scene's painted backdrop (kind backdrop; its "
             "description is the place, with no people). Up to three characters, each with a role (left, "
             "centre, right), and up to two props (role prop). caption: a name card when a person, a "
             "place or a year is introduced, otherwise empty. Keep the same backdrop key while the place "
             "stays the same; characters who stay keep their keys and walk to new spots.",
    "diagram": "diagram: one exact diagram drawn on screen (a formula, a chart, a number line...: see "
               "DIAGRAMS), with up to two small things from the kit beside it. The layout for "
               "anything with numbers, maths or structure.",
}

DIAGRAM_GUIDE = """
DIAGRAMS: a beat with the diagram layout has a diagram (for every other layout, diagram kind is
"" and its lists empty). They are drawn exactly, element by element on their words (on_word), so
prefer them wherever the idea is maths, numbers, structure or change: a formula being written, a
chart, a number line, a curve. Keep a diagram's id while the idea continues, so the next beat
builds on it (more lines, bars that change, points that move) instead of starting again; change the
id for a new diagram. Write maths in LaTeX between $...$ (\\frac, ^, _, \\sqrt, \\sum, Greek);
never invent numbers the narration doesn't give or imply.
""".strip()


def schema(fmt: dict) -> dict:
    item = {"type": "object", "properties": {
        "key": {"type": "string"}, "label": {"type": "string"},
        "on_word": {"type": "integer"}, "count": {"type": "integer"},
        "highlight": {"type": "boolean"},
        "role": {"type": "string", "enum": list(layouts.ROLES)},
        "says": {"type": "string"}, "thinks": {"type": "boolean"}},
        "required": ["key", "label", "on_word", "count", "highlight", "role", "says", "thinks"],
        "additionalProperties": False}
    beat = {"type": "object", "properties": {
        "start_word": {"type": "integer"},
        "layout": {"type": "string", "enum": allowed_layouts(fmt)},
        "title": {"type": "string"},
        "relation": {"type": "string", "enum": list(layouts.RELATIONS)},
        "avatar": {"type": "string", "enum": list(POSES)},
        "backdrop": {"type": "string"}, "caption": {"type": "string"},
        "table": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
        "items": {"type": "array", "items": item},
        "why": {"type": "string"}},
        "required": ["start_word", "layout", "title", "relation", "avatar", "backdrop", "caption",
                     "table", "items", "why"],
        "additionalProperties": False}
    kinds = diagram_kinds(fmt)
    if kinds:
        shape = diagrams.schema()
        shape["properties"]["kind"]["enum"] = [""] + kinds
        beat["properties"]["diagram"] = shape
        beat["required"].append("diagram")
    kit = {"type": "object", "properties": {
        "key": {"type": "string"}, "name": {"type": "string"},
        "kind": {"type": "string", "enum": list(KINDS)}, "description": {"type": "string"}},
        "required": ["key", "name", "kind", "description"], "additionalProperties": False}
    return {"type": "object", "properties": {
        "concept": {"type": "string"},
        "kit": {"type": "array", "items": kit},
        "beats": {"type": "array", "items": beat}},
        "required": ["concept", "kit", "beats"], "additionalProperties": False}


def diagram_kinds(fmt: dict) -> list:
    """The diagrams this style draws (none for most drawn-picture styles)."""
    return [k for k in fmt.get("diagrams") or [] if k in diagrams.KINDS]


def allowed_layouts(fmt: dict) -> list:
    allowed = [l for l in fmt.get("layouts") or layouts.LAYOUTS if l in layouts.LAYOUTS]
    if not fmt.get("avatar"):
        allowed = [l for l in allowed if l != "presenter"]
    if diagram_kinds(fmt):
        allowed += [] if "diagram" in allowed else ["diagram"]
    else:
        allowed = [l for l in allowed if l != "diagram"]
    return allowed or ["hero", "statement"]


def _narration(segments, words, windows) -> str:
    animate = {i for w in windows for i in range(w["first"], w["last"] + 1)}
    lines = []
    for s_index, segment in enumerate(segments):
        idx = [i for i, w in enumerate(words) if segment.start - 0.05 <= w.start < segment.end]
        mark = "ANIMATE" if s_index in animate else "not animated"
        text = " ".join(f"{i}:{words[i].word}@{words[i].start:.1f}" for i in idx)
        lines.append(f"[segment {s_index}, {segment.start:.1f}-{segment.end:.1f}s, {mark}] {text}")
    return "\n".join(lines)


def brief(fmt: dict, look: dict, existing: dict) -> str:
    """What the storyboard is told about the channel's style."""
    layout_lines = "\n".join("- " + LAYOUT_GUIDE[l] for l in allowed_layouts(fmt))
    kit_lines = "\n".join(f"- {k} ({v.get('kind', 'object')}): {v['name']}"
                          for k, v in sorted(existing.items())) or "(none yet)"
    kinds = diagram_kinds(fmt)
    diagram_lines = (DIAGRAM_GUIDE + "\n" + "\n".join("- " + diagrams.GUIDE[k] for k in kinds)
                     if kinds else "")
    shape = frames.get(fmt.get("frame"))
    return "\n\n".join(p for p in [
        f"THE STYLE: {look['description']}",
        f"THE FRAME: {shape.label}." + ("" if shape.vertical else
                                        " A longer video: beats can hold a little more."),
        f"HOW TO THINK:\n{fmt['guide']}",
        f"How people look: {look['people']}" if look.get("people") else "",
        f"THE LAYOUTS YOU MAY USE:\n{layout_lines}",
        diagram_lines,
        "There is a host on screen for presenter beats." if fmt.get("avatar") else "",
        "Use no labels or titles: leave label, title and caption empty." if fmt.get("no_labels") else "",
        f"The channel's existing kit (reuse by key):\n{kit_lines}",
    ] if p)


def write(segments, words, windows, *, subject: str, fmt: dict, look: dict, existing: dict,
          avoid: list, mean: float) -> dict:
    """The raw beats from the model (see `settle`)."""
    user = [
        f"The video is about: {subject}",
        brief(fmt, look, existing),
        f"Never show: {', '.join(avoid)}." if avoid else "",
        "The narration, each word as index:word@seconds:\n" + _narration(segments, words, windows),
    ]
    return call_json([SystemBlock(GUIDE.replace("{mean}", f"{mean:.1f}"), cacheable=True)],
                     "\n\n".join(p for p in user if p), schema(fmt),
                     operation="animation_beats", max_tokens=MAX_TOKENS, effort=EFFORT)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def _clean(text, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def settle(raw: dict, windows: list, words: list, fmt: dict) -> tuple:
    """(beats, kit, notes). Beats carry "start", "end" (narration seconds)
    and "window"; kit is {key: {"name", "kind", "description"}} for
    everything the beats use."""
    notes = []
    kit = {}
    for k in raw.get("kit") or []:
        key = slug(k.get("key") or k.get("name"))
        if key and key not in kit:
            kit[key] = {"name": _clean(k.get("name") or key, 60),
                        "kind": k.get("kind") if k.get("kind") in KINDS else "object",
                        "description": _clean(k.get("description"), 300)}
    allowed = allowed_layouts(fmt)
    kinds = diagram_kinds(fmt)
    window_of = {i: w for w, win in enumerate(windows) for i in win["words"]}
    beats = []
    for b in raw.get("beats") or []:
        word = b.get("start_word")
        if not isinstance(word, int) or word not in window_of:
            notes.append(f"a beat on word {word}, outside the animation; dropped")
            continue
        items = []
        travel = b.get("layout") == "travel"
        repeats = b.get("layout") == "lineup"     # a line of prisoners can repeat a figure
        for position, it in enumerate(b.get("items") or []):
            key = slug(it.get("key"))
            # Each thing once in a beat (copies are `count`, not repeats),
            # except in a lineup, where the same figure can stand twice.
            if not key or (not repeats and any(i["key"] == key for i in items)):
                continue
            if travel and position in (1, 2):
                # Travel items are the traveller, its start, its end: keep
                # which is which even if one is dropped above.
                it = dict(it, place="start" if position == 1 else "end")
            if key not in kit:
                kit[key] = {"name": key.replace("_", " "), "kind": "object", "description": ""}
            items.append({"key": key, "label": _clean(it.get("label"), 28),
                          "on_word": it.get("on_word") if isinstance(it.get("on_word"), int) else -1,
                          "count": max(1, min(layouts.MAX_COUNT, int(it.get("count") or 1))),
                          "highlight": bool(it.get("highlight")),
                          "role": it.get("role") if it.get("role") in layouts.ROLES else "",
                          "says": _clean(it.get("says"), 48), "thinks": bool(it.get("thinks")),
                          **({"place": it["place"]} if it.get("place") else {})})
        table = [[_clean(c, 16) for c in row[:4]] for row in (b.get("table") or [])[:4] if row]
        backdrop = slug(b.get("backdrop"))
        layout = b.get("layout") if b.get("layout") in allowed else _first(allowed, items)
        if layout == "table" and not table:
            layout = _first([l for l in allowed if l != "table"], items)
        if layout == "scene":
            if backdrop:
                entry = kit.setdefault(backdrop, {"name": backdrop.replace("_", " "), "kind": "backdrop",
                                                  "description": backdrop.replace("_", " ")})
                entry["kind"] = "backdrop"
            items = [it for it in items if it["key"] != backdrop]
        else:
            backdrop = ""
        # A diagram makes the beat a diagram beat (with at most two things
        # beside it); a diagram layout without one is another layout.
        diagram = diagrams.settle(b.get("diagram"), kinds) if kinds else None
        if diagram and "diagram" in allowed:
            layout, items = "diagram", items[:2]
        else:
            diagram = None
            if layout == "diagram":
                layout = _first([l for l in allowed if l != "diagram"], items)
            layout = _fitting(layout, items, allowed)
        beats.append({"start_word": word, "window": window_of[word], "layout": layout,
                      "diagram": diagram,
                      "title": _clean(b.get("title"), 40),
                      "relation": b.get("relation") if b.get("relation") in layouts.RELATIONS else "",
                      "avatar": (b.get("avatar") if b.get("avatar") in POSES else "")
                      if fmt.get("avatar") else "",
                      "backdrop": backdrop, "caption": _clean(b.get("caption"), 40),
                      "table": table if layout == "table" else [],
                      "items": items, "why": b.get("why") or ""})
    beats.sort(key=lambda b: b["start_word"])
    beats = [b for i, b in enumerate(beats) if i == 0 or b["start_word"] != beats[i - 1]["start_word"]]

    for w_index, window in enumerate(windows):
        if not window["words"]:
            continue
        mine = [b for b in beats if b["window"] == w_index]
        if not mine:
            beats.append({"start_word": window["words"][0], "window": w_index,
                          "layout": "statement" if "statement" in allowed else allowed[0],
                          "title": "", "relation": "", "avatar": "", "backdrop": "", "caption": "",
                          "table": [], "items": [], "why": "", "missing": True})
            notes.append(f"window {w_index + 1} had no beats")
        else:
            mine[0]["start_word"] = window["words"][0]
    beats.sort(key=lambda b: b["start_word"])

    # A scene without a backdrop keeps the one before it.
    last = ""
    for b in beats:
        if b["layout"] == "scene":
            b["backdrop"] = b["backdrop"] or last
            last = b["backdrop"]

    _time(beats, windows, words)
    beats = _merge_short(beats, windows, words)
    for b in beats:
        lo = b["start_word"]
        hi = max((i for i in windows[b["window"]]["words"] if words[i].start < b["end"]), default=lo)
        for it in b["items"]:
            if not lo <= it["on_word"] <= hi:
                it["on_word"] = -1
        for part in _diagram_parts(b.get("diagram")):
            if not lo <= part["on_word"] <= hi:
                part["on_word"] = -1
    used ={it["key"] for b in beats for it in b["items"]} | {b["backdrop"] for b in beats if b["backdrop"]}
    return beats, {k: v for k, v in kit.items() if k in used}, notes


def _diagram_parts(diagram) -> list:
    """The elements of a diagram that arrive on words."""
    if not diagram:
        return []
    return [p for name in ("lines", "bars", "points", "jumps", "curves", "edges")
            for p in diagram.get(name) or [] if "on_word" in p]


def _first(allowed, items) -> str:
    for l in allowed:
        lo, hi = layouts.ITEM_LIMITS[l]
        if lo <= len(items) <= hi:
            return l
    return allowed[0]


def _fitting(layout: str, items: list, allowed: list = None) -> str:
    """A layout that can take this many things (and that the style allows)."""
    allowed = allowed or list(layouts.LAYOUTS)
    lo, hi = layouts.ITEM_LIMITS[layout]
    n = len(items)
    if layout in ("statement", "presenter", "scene", "table") or lo <= n <= hi:
        return layout
    for candidate in ({1: "hero", 2: "pair", 3: "row"}.get(n, "grid"), "lineup", "hero", "statement"):
        if candidate in allowed:
            c_lo, c_hi = layouts.ITEM_LIMITS[candidate]
            if c_lo <= n <= c_hi or candidate == "statement":
                return candidate
    return allowed[0]


def _time(beats, windows, words) -> None:
    for b in beats:
        window = windows[b["window"]]
        if b["start_word"] == window["words"][0]:
            b["start"] = window["start"]
        else:
            b["start"] = max(window["start"], words[b["start_word"]].start - LEAD)
    for i, b in enumerate(beats):
        nxt = beats[i + 1] if i + 1 < len(beats) else None
        b["end"] = nxt["start"] if nxt and nxt["window"] == b["window"] else windows[b["window"]]["end"]


def _merge_short(beats, windows, words) -> list:
    changed = True
    while changed:
        changed = False
        _time(beats, windows, words)
        for i, b in enumerate(beats):
            if b["end"] - b["start"] >= MIN_BEAT:
                continue
            if i > 0 and beats[i - 1]["window"] == b["window"]:
                del beats[i]
            elif i + 1 < len(beats) and beats[i + 1]["window"] == b["window"]:
                beats[i + 1]["start_word"] = b["start_word"]
                del beats[i]
            else:
                continue
            changed = True
            break
    _time(beats, windows, words)
    return beats
