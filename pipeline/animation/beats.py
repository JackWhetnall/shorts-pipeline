"""
The storyboard for composited formats (tabletop, canvas): one call
writes the explanation as beats (decision 052).

A beat is one clear picture for a stretch of narration: a designed layout
(pipeline.animation.compositor.layouts) filled with objects from the kit,
their labels, a title, what joins them, and the spoken word each object
arrives on. The model chooses and fills; it never places anything. Every
label is the exact text shown, so it's held to what the narration says.

`settle` then makes the beats safe: cut on real words inside the animated
stretches, long enough to read, layouts that fit their objects, objects
that exist in the kit, and words that fall inside their beat.
"""

from __future__ import annotations

import re

from core.logging_setup import get_logger
from pipeline.animation.compositor import layouts
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

POSES = ("", "talk", "point", "shrug", "think")
MIN_BEAT = 1.6
LEAD = 0.1
MAX_TOKENS = 16000
EFFORT = "medium"

GUIDE = """
You are directing an animated explainer as a sequence of beats. The narration is finished and
timed. Each beat is one clear picture for the words it covers, built from a fixed set of
designed layouts filled with objects, labels and a title. The layouts place everything; you
choose the layout and fill it. Make it genuinely good: clear, clever and fun to watch, the
picture always adding to the words rather than repeating them.

LAYOUTS
- hero: one object, big, with its label. Introducing a thing. With count > 1, a crowd of it.
- pair: two objects side by side, joined by a relation: vs (a contrast), plus (combining),
  equals (what it amounts to), arrow (this leads to that). Either side can be several copies.
- row: two or three objects in a row, joined by arrows (a sequence) or plus signs, or nothing.
- grid: four to six objects, each labelled: examples, kinds, parts of a set.
- steps: two to four numbered steps, top to bottom, each an object and a label: a process.
- cycle: three to five objects round a circle, joined by arrows: a loop that repeats.
- group: many copies of one object (count up to 30), one of them circled when highlight is
  true: a proportion ("1 in 10"), a crowd, a large amount.
- travel: an object moving along a dotted path, optionally from one object to another:
  something passing, spreading, flowing or being sent. Items: the traveller first, then where it
  starts, then where it arrives.
- scale: two to four objects from small to large: sizes, amounts, growth.
- statement: a short title set big (a number, a two- or three-word answer) with at most one
  small object: a hook, a punchline, the key fact.
- presenter: the narrator on screen with at most one object (only when there is a narrator).

WRITING THE BEATS
- One idea per beat, and change beat when the thought turns: about {mean} seconds each, never
  under two. The first beat is the hook: the most intriguing picture you can make of the opening
  line. The last beat lands the idea.
- Vary the layouts; never use the same layout three times running.
- Objects are concrete things, each drawn once and reused: key (lowercase, underscores), and in
  the kit a name and a short visual description (shape, colour, one detail) for drawing it.
  Reuse the channel's existing objects by exactly the same key whenever one fits.
- Labels: one to three words, exactly as they should appear. Only words or numbers the narration
  says or directly implies; never invent facts, figures, dates or names.
- Titles: at most five words, and only where they help: a question at the hook, a key term,
  the answer. Leave empty otherwise.
- on_word: the index of the spoken word that names or introduces the object, so it arrives as
  it's said; -1 if nothing does.
- A beat starts on a spoken word (start_word) where the thought turns. Beats fall only inside
  stretches marked ANIMATE, and every ANIMATE stretch begins with a beat on its first word.
- avatar: the narrator's pose for presenter beats (talk, point, shrug, think); empty otherwise.
- relation: vs, plus, equals, arrow, or empty. highlight: true only to circle one in a group.
- count: how many copies (1 unless the layout shows several).
""".strip()


def schema() -> dict:
    item = {"type": "object", "properties": {
        "key": {"type": "string"}, "label": {"type": "string"},
        "on_word": {"type": "integer"}, "count": {"type": "integer"},
        "highlight": {"type": "boolean"}},
        "required": ["key", "label", "on_word", "count", "highlight"],
        "additionalProperties": False}
    beat = {"type": "object", "properties": {
        "start_word": {"type": "integer"},
        "layout": {"type": "string", "enum": list(layouts.LAYOUTS)},
        "title": {"type": "string"},
        "relation": {"type": "string", "enum": list(layouts.RELATIONS)},
        "avatar": {"type": "string", "enum": list(POSES)},
        "items": {"type": "array", "items": item},
        "why": {"type": "string"}},
        "required": ["start_word", "layout", "title", "relation", "avatar", "items", "why"],
        "additionalProperties": False}
    kit = {"type": "object", "properties": {
        "key": {"type": "string"}, "name": {"type": "string"},
        "description": {"type": "string"}},
        "required": ["key", "name", "description"], "additionalProperties": False}
    return {"type": "object", "properties": {
        "concept": {"type": "string"},
        "kit": {"type": "array", "items": kit},
        "beats": {"type": "array", "items": beat}},
        "required": ["concept", "kit", "beats"], "additionalProperties": False}


def _narration(segments, words, windows) -> str:
    animate = {i for w in windows for i in range(w["first"], w["last"] + 1)}
    lines = []
    for s_index, segment in enumerate(segments):
        idx = [i for i, w in enumerate(words) if segment.start - 0.05 <= w.start < segment.end]
        mark = "ANIMATE" if s_index in animate else "not animated"
        text = " ".join(f"{i}:{words[i].word}@{words[i].start:.1f}" for i in idx)
        lines.append(f"[segment {s_index}, {segment.start:.1f}-{segment.end:.1f}s, {mark}] {text}")
    return "\n".join(lines)


def write(segments, words, windows, *, subject: str, fmt: dict, look: dict, existing: dict,
          avoid: list, mean: float) -> dict:
    """The raw beats from the model (see `settle`)."""
    kit_lines = "\n".join(f"- {k}: {v['name']}" for k, v in sorted(existing.items())) or "(none yet)"
    user = [
        f"The video is about: {subject}",
        f"FORMAT: {fmt['label']}. {fmt['guide']}",
        f"The look: {look['label']}: {look['description']}",
        "There is a narrator on screen for presenter beats." if fmt.get("avatar")
        else "There is no narrator on screen: never use presenter.",
        f"The channel's existing objects (reuse by key):\n{kit_lines}",
        f"Never show: {', '.join(avoid)}." if avoid else "",
        "The narration, each word as index:word@seconds:\n" + _narration(segments, words, windows),
    ]
    return call_json([SystemBlock(GUIDE.replace("{mean}", f"{mean:.1f}"), cacheable=True)],
                     "\n\n".join(p for p in user if p), schema(),
                     operation="animation_beats", max_tokens=MAX_TOKENS, effort=EFFORT)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def settle(raw: dict, windows: list, words: list, fmt: dict) -> tuple:
    """(beats, kit, notes). Beats carry "start", "end" (narration seconds)
    and "window"; kit is {key: {"name", "description"}} for every object
    the beats use."""
    notes = []
    kit = {}
    for k in raw.get("kit") or []:
        key = slug(k.get("key") or k.get("name"))
        if key and key not in kit:
            kit[key] = {"name": (k.get("name") or key).strip()[:60],
                        "description": (k.get("description") or "").strip()[:300]}

    window_of = {i: w for w, win in enumerate(windows) for i in win["words"]}
    beats = []
    for b in raw.get("beats") or []:
        word = b.get("start_word")
        if not isinstance(word, int) or word not in window_of:
            notes.append(f"a beat on word {word}, outside the animation; dropped")
            continue
        items = []
        travel = b.get("layout") == "travel"
        for position, it in enumerate(b.get("items") or []):
            key = slug(it.get("key"))
            # Each object once in a beat (copies are `count`, not repeats).
            if not key or any(i["key"] == key for i in items):
                continue
            if travel and position in (1, 2):
                # Travel items are the traveller, its start, its end: keep
                # which is which even if one is dropped above.
                it = dict(it, place="start" if position == 1 else "end")
            if key not in kit:
                kit[key] = {"name": key.replace("_", " "), "description": ""}
            items.append({"key": key, "label": " ".join(str(it.get("label") or "").split())[:28],
                          "on_word": it.get("on_word") if isinstance(it.get("on_word"), int) else -1,
                          "count": max(1, min(layouts.MAX_COUNT, int(it.get("count") or 1))),
                          "highlight": bool(it.get("highlight")),
                          **({"place": it["place"]} if it.get("place") else {})})
        layout = b.get("layout") if b.get("layout") in layouts.LAYOUTS else "hero"
        if layout == "presenter" and not fmt.get("avatar"):
            layout = "hero" if items else "statement"
        layout = _fitting(layout, items)
        beats.append({"start_word": word, "window": window_of[word], "layout": layout,
                      "title": " ".join(str(b.get("title") or "").split())[:40],
                      "relation": b.get("relation") if b.get("relation") in layouts.RELATIONS else "",
                      "avatar": (b.get("avatar") if b.get("avatar") in POSES else "")
                      if fmt.get("avatar") else "",
                      "items": items, "why": b.get("why") or ""})
    beats.sort(key=lambda b: b["start_word"])
    beats = [b for i, b in enumerate(beats) if i == 0 or b["start_word"] != beats[i - 1]["start_word"]]

    for w_index, window in enumerate(windows):
        if not window["words"]:
            continue
        mine = [b for b in beats if b["window"] == w_index]
        if not mine:
            beats.append({"start_word": window["words"][0], "window": w_index,
                          "layout": "statement", "title": "", "relation": "", "avatar": "",
                          "items": [], "why": "", "missing": True})
            notes.append(f"window {w_index + 1} had no beats")
        else:
            mine[0]["start_word"] = window["words"][0]
    beats.sort(key=lambda b: b["start_word"])

    _time(beats, windows, words)
    beats = _merge_short(beats, windows, words)
    for b in beats:
        lo = b["start_word"]
        hi = max((i for i in windows[b["window"]]["words"] if words[i].start < b["end"]), default=lo)
        for it in b["items"]:
            if not lo <= it["on_word"] <= hi:
                it["on_word"] = -1
    used = {it["key"] for b in beats for it in b["items"]}
    return beats, {k: v for k, v in kit.items() if k in used}, notes


def _fitting(layout: str, items: list) -> str:
    """A layout that can take this many objects."""
    lo, hi = layouts.ITEM_LIMITS[layout]
    n = len(items)
    if lo <= n <= hi or (layout in ("statement", "presenter") and n <= hi):
        return layout
    if layout in ("statement", "presenter"):
        return layout
    if n == 0:
        return "statement"
    return {1: "hero", 2: "pair", 3: "row"}.get(n, "grid")


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
