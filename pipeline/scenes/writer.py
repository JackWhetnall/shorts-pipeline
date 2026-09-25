"""
Script in, animated scenes out: the model call that turns narration into
scene data, and the checks that make that data safe to render.

Two calls, both on Sonnet:

1. **Plan** (cheap): which stretches of the script get a scene, grouped
   so one idea can be built up across consecutive segments (a triangle
   drawn in one segment is still there when the next names its sides),
   with a one-line concept each. The channel's `scenes.share` says
   roughly how much.
2. **Write**, once per scene: the elements and actions, each action
   anchored to the spoken word it happens on. Word anchors, not seconds,
   are what keep the picture in step with the voice; they're converted
   to seconds here from the real narration timings.

Then **check**. `validate` catches anything structurally wrong (a target
that doesn't exist, a prop never declared, a word past the end) and
fixes what's harmless (a draw running past the scene's end is
shortened). `layout_problems` builds the scene in the browser and
measures it: text off screen, text in the captions' space, labels on
top of each other. One repair round gets the problems back as notes. See
docs/specs/animated-scenes.md §3.5 and decision 035.
"""

from __future__ import annotations

import copy
import json

from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

PLAN_MAX_TOKENS = 6000
PLAN_EFFORT = "low"
WRITE_MAX_TOKENS = 16000
WRITE_EFFORT = "medium"      # the geometry and the timing both need real thought

FRAME_W, FRAME_H = 1080, 1920
SAFE_LEFT, SAFE_RIGHT, SAFE_TOP = 30, 1050, 60
CAPTION_TOP = 1320            # below this is the captions' space
MAX_ELEMENTS = 18
MAX_LABEL_CHARS = 40
MAX_NEW_PROPS = 2             # per scene

ELEMENT_TYPES = ("shape", "label", "prop", "counter", "chart")
SHAPE_KINDS = ("circle", "star", "polygon", "poly", "square", "angle", "line", "arrow", "rect",
               "beam")
ACTIONS = ("appear", "draw", "write", "count", "move", "highlight", "wiggle", "stack", "exit")
AREA_KINDS = ("circle", "polygon", "poly", "square", "rect")
COLOR_TOKENS = ("ink", "ink_soft", "label_fill", "accent1", "accent2", "accent3", "accent4", "accent5")

GUIDE = """
You design animated explainer scenes for vertical short videos. A scene is
DATA, never code: elements, and actions that bring them in, change them,
and take them away, each timed to the spoken word it happens on. An
engine draws the data in the channel's own art direction (its colours,
fonts, line weight, texture and motion are applied for you), so you
decide WHAT is on screen, WHERE, and WHEN. Never how it looks.

## The canvas

1080 wide by 1920 tall, origin top left, y downwards. Keep everything
inside x 60-1020 and y 110-1290. Below y 1300 is where the captions go:
put nothing there. Centre compositions around x 540. The strongest area
is y 250-1150.

## Elements

Every element has a unique `id` and a `type`. Colours are always tokens:
ink, ink_soft, label_fill, accent1, accent2, accent3, accent4, accent5.

shape: `kind` is one of
- circle: x, y, r
- star: x, y, r, points (count, default 5). Drawn as one continuous line
  through every second point, like a hand-drawn pentagram. Vertex 0 is
  the top; vertices run clockwise.
- polygon: regular polygon: x, y, r, points (count). Vertex 0 at the top.
- poly: any polygon from exact `vertices` [[x,y],...]: triangles, and any
  figure whose corners you work out. Vertices keep the order you give.
- square: the square standing on one side of another shape, facing
  outward: on {of: shape id, edge: i}. Edge i runs from vertex i to
  vertex i+1. The engine computes it, so it is always exact.
- angle: a corner mark at another shape's vertex: at {of, vertex},
  right: true for the small square of a right angle, false for an arc.
  Optional size (default 44).
- line / arrow: x, y, x2, y2.
- rect: centred box: x, y, w, h, optional radius.
- beam: a physical bar exactly between two points: x, y, x2, y2,
  thickness (default 56). rungs: true makes it a ladder (spacing between
  rungs, default 70). Use a beam for anything long that must line up with
  the geometry: a ladder, plank, ramp, pole, beam of a seesaw.
Optional: stroke (colour), fill (colour), fill_opacity (0-1, use about
0.2-0.4 for areas you want to read as shaded), width (line weight),
texture ("bricks", "planks" or "hatch") for a surface: a brick wall is a
rect with texture "bricks"; hatched ground is a rect with "hatch".

label: short text. `text`, or `parts` [{text, color}] for text in coloured
pieces (an equation whose terms match their shapes). size (44-100),
style: "title" for a heading, pill: false for bare text (default is a
rounded tag), dot: a colour token for a small coloured dot (a legend key),
color, font: "text" for the plainer body font. Unicode maths is fine:
² ³ √ × ÷ − π θ ≈ ≠ ≤. No LaTeX.

prop: an illustrated object from the channel's prop library: asset (a key
declared in this scene's `props`), w (and optionally h), x, y. fit:
"cover" fills the w-by-h box exactly (cropping). span: {from, to} lays a
long, thin object (a candle, a pencil, a sword) exactly along two points,
its top at `to`; each point is [x, y] or an anchor like {of, vertex}.

counter: a number that counts. from, prefix ("£"), suffix ("%"), decimals,
size (90-130), x, y. Counts to a value with the count action.

chart: kind "line" or "bar"; x, y (centre), w, h, values [numbers],
optional axis_labels [{text, at: "start"|"end", align: "start"|"end"}],
stroke or fill colour.

Positions: x/y, or an `anchor` that ties an element to another one and
is always exact: anchor {of: id} is the other element's centre;
{of, vertex: i, offset: px} is just outside that corner; {of, edge: i,
offset: px} is just outside the middle of that side (use this for side
labels like a, b, c); {of, side: "top"|"bottom"} for props; dx/dy nudge
any anchor. Prefer anchors over computed coordinates for anything that
labels something else.

template: true on an element means it is never shown itself, only copied
by a stack action. hidden: true means it is never shown at all: a
construction line or reference shape that only exists for others to
anchor to or be built on.

## Actions

Each action: target (an element id), do, word (the index of the spoken
word it starts on, from the numbered word list), optional delay
(seconds after that word), dur (seconds).

- appear: fades/pops the element in. style: pop (default), slide, drop,
  fade.
- draw: a shape or chart draws itself along its line (0.6-2 s). Shaded
  fills fill in as the line closes.
- write: a label writes itself word by word (or part by part).
- count: a counter counts to `to`.
- move: moves the element to `to_xy` [x, y].
- highlight: a brief pulse to point at something as it's named.
- wiggle: a small shake, for emphasis.
- stack: copies of a template prop drop one by one into another element:
  into (target id), count (2-9), spread (px). Good for accumulating.
- exit: fades the element out. Use it to clear the stage when the
  narration moves to a new idea.

Every visible element needs an entry action (appear, draw or write) on
the word that names it; one without is on screen from the first frame.

## What makes a good scene

- It shows exactly what is being said, as it is said. The picture never
  contradicts, embellishes or runs ahead of the words. Every number on
  screen matches the narration, is attached to the thing the narration
  attaches it to (if the wall is 8, the 8 labels the wall), and appears
  only once it has been said or worked out: never give away an answer
  the narration is still building towards.
- The whole narration is given for context, so a scene knows what came
  before and what the numbers stand for. Draw only your own stretch.
- One idea, big and clear. 3 to 8 elements on screen at once. Short text:
  labels of 1-4 words, titles of at most 5.
- The same thing keeps the same colour all the way through, and anything
  that labels it (a dot, an equation term) uses that colour too.
- Something changes at least every 2-3 seconds, but nothing flickers.
  Let a finished picture hold briefly while the point lands.
- Build up rather than dump: introduce parts one at a time, then
  highlight the relationship.
- Nothing overlaps unless it's meant to (a label inside the area it
  names). Labels never sit on top of other labels, and never straddle a
  line.
- Plan the FINISHED picture first, then build towards it. Anything that
  will later be built beside a side (a square on it, an arrow along it)
  takes that space: anchor the side's label to the new construction
  instead ({of: square id} puts it in the square's middle), or have the
  label move there as the construction appears.
- Give equations room: parts with spaces around operators ("a² ", "+ ",
  "b² ", "= ", "c²"), size 80-100, placed where nothing else will be.
- Geometry is exact. When you give coordinates, work them out: a 3-4-5
  triangle is 3:4:5, a right angle is square. Draw figures large: a main
  figure should span 400-700 px.
- Things that touch in the narration touch on screen, exactly. A ladder
  "against a wall" has its foot on the ground line and its top on the
  wall's top edge; a ball "on a ramp" sits on the ramp's line. Work out
  those contact points once, then use the SAME points for the objects
  and for any geometry drawn over them (the triangle's corners are the
  ladder's foot, the wall's foot and the ladder's top). A wall stands on
  the ground; an axis is never a stand-in for a wall.
- Props only for concrete, recognisable objects that add meaning (a
  coin, a candle, a piggy bank); never for text, numbers, arrows or
  geometric shapes, which you draw. Anything that must line up with the
  geometry (a ladder, a plank, a wall) is drawn: a beam or a rect. Reuse the channel's existing props by their
  exact names. Name a new prop generically ("wooden ladder"), because it
  will be drawn once and reused in future videos. At most two new props
  in a scene.
- Omit any field you'd leave at its default. Output only the scene.
""".strip()


def _plan_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "segments": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "need": {"type": "integer", "description": "0-10, by the rubric."},
                    "idea": {"type": "string", "description": "What would be built up on screen "
                                                              "if this segment is animated."},
                    "builds_on_previous": {"type": "boolean",
                                           "description": "True when its picture continues the "
                                                          "previous segment's."},
                },
                "required": ["index", "need", "idea", "builds_on_previous"],
                "additionalProperties": False}},
        },
        "required": ["segments"], "additionalProperties": False,
    }


NEED_RUBRIC = """
For each segment, score how much it NEEDS an animated explanation rather
than stock footage, 0-10. Judge the segment alone, the same way every
time:

10     It can't really be followed without seeing it: a construction, a
       proof, a calculation, a structure whose named parts matter, a
       process whose order matters.
7-9    A picture makes it much clearer: quantities compared, a timeline, a
       cause-and-effect chain, a symbol explained part by part.
4-6    A picture helps a little: one number, a named idea that can be
       shown simply.
1-3    Mood, story, reflection, speaking to the viewer: footage carries it
       as well or better.
0      Nothing to show beyond a feeling.
""".strip()


def need_threshold(share: int):
    """The slider as a bar each segment's need must clear. None: never
    animate. 0: always. In between, the closer to the stock end, the more
    essential a picture must be: 10 -> only segments that can't be followed
    without one; 50 -> anything a picture helps; 90 -> almost everything."""
    if share <= 0:
        return None
    if share >= 100:
        return 0
    return 10 - share / 10


SCENE_FORMAT = """
Answer with one JSON object and nothing else:
{"props": [{"key": "...", "name": "...", "detail": "..."}],
 "elements": [{"id": "...", "type": "...", ...fields for that type...}],
 "actions": [{"target": "...", "do": "...", "word": 0, "dur": 1.0, ...}]}
`props` declares every prop the scene uses: key (what elements' `asset`
refers to), name (generic object name, or an existing library name
exactly), detail (anything the drawing must get right, or "").
""".strip()


# --- the calls ---------------------------------------------------------------

def _style_note(style: dict) -> str:
    colours = ", ".join(f"{k} {v}" for k, v in style["colors"].items())
    return (f"This channel's art direction: {style.get('label', style['key'])}. "
            f"{style.get('description', '')} Colours: {colours}. Background "
            f"{style['background']['color']}. Pick colours that read well on it.")


def plan(segments: list, share: int, subject: str) -> list:
    """[{first, last, idea}] for the stretches that get a scene, in order,
    not overlapping. Segments not covered keep stock footage.

    The slider is a threshold, not a quota (decision 037): every segment
    is scored for how much it needs a picture, independently of the
    slider, and animated when its score clears the slider's bar.
    Consecutive animated segments that build on one picture become one
    scene.
    """
    threshold = need_threshold(share)
    if threshold is None:
        return []
    lines = "\n".join(f"[{i}] ({s.duration:.1f}s) {s.text}\n    shot brief: {s.shot_brief}"
                      for i, s in enumerate(segments))
    user = (f"The video is about: {subject}\n\nIts segments:\n{lines}\n\n{NEED_RUBRIC}\n\n"
            f"For every segment give its score, the picture you'd build for it, and whether "
            f"that picture continues the previous segment's.")
    data = call_json([SystemBlock(GUIDE, cacheable=True)], user, _plan_schema(),
                     operation="scene_plan", max_tokens=PLAN_MAX_TOKENS, effort=PLAN_EFFORT)
    rated = {}
    for row in data.get("segments") or []:
        i = row.get("index")
        if isinstance(i, int) and 0 <= i < len(segments) and i not in rated:
            rated[i] = row

    scenes = []
    for i, segment in enumerate(segments):
        row = rated.get(i, {})
        need = int(row.get("need") or 0)
        if need < threshold:
            log.info(f"  [scene] segment {i}: need {need} < {threshold:g}, stock footage")
            continue
        idea = (row.get("idea") or "").strip() or segment.shot_brief or f"Show what is said: {segment.text}"
        if scenes and scenes[-1]["last"] == i - 1 and row.get("builds_on_previous"):
            scenes[-1]["last"] = i
            scenes[-1]["idea"] += f" Then: {idea}"
        else:
            scenes.append({"first": i, "last": i, "idea": idea})
    return scenes


def words_for(word_timings: list, start: float, end: float) -> list:
    """[(word, seconds from the scene's start)] for the narration inside
    [start, end)."""
    return [(w.word, round(w.start - start, 2)) for w in word_timings if start <= w.start < end]


def write(idea: str, words: list, duration: float, style: dict, library: list,
          before: str = "", after: str = "", narration: str = "", reserve: str = "",
          previous: dict = None, problems: list = None) -> dict:
    """One scene's data (with word anchors), for `words` spoken over
    `duration` seconds. `previous` and `problems` ask for a repair."""
    numbered = " ".join(f"{i}:{w}@{t:.2f}" for i, (w, t) in enumerate(words))
    user = [f"The whole video's narration, for context:\n{narration}"] if narration else []
    user += [f"Scene concept: {idea}",
            f"Duration: {duration:.2f} seconds.",
            f"Spoken words (index:word@seconds from the scene's start):\n{numbered}"]
    if before:
        user.append(f"The previous scene showed: {before}")
    if after:
        user.append(f"The next scene will show: {after}")
    if reserve:
        user.append(reserve)
    user.append("Props already in this channel's library: "
                + (", ".join(library) if library else "(none yet)"))
    if previous is not None:
        user.append("Your previous version of this scene:\n" + json.dumps(previous)
                    + "\n\nIt has these problems. Fix all of them and keep what works:\n- "
                    + "\n- ".join(problems or []))
    system = [SystemBlock(GUIDE, cacheable=True), SystemBlock(_style_note(style))]
    user.append(SCENE_FORMAT)
    return call_json(system, "\n\n".join(user), None,
                     operation="scene_write" if previous is None else "scene_repair",
                     max_tokens=WRITE_MAX_TOKENS, effort=WRITE_EFFORT)


# --- checks --------------------------------------------------------------------

def validate(raw: dict, words: list, duration: float) -> tuple:
    """(scene ready for the renderer, problems). Word anchors become
    seconds; harmless slips are fixed; anything that would draw wrongly is
    a problem."""
    scene = copy.deepcopy(raw)
    problems = []
    elements = scene.get("elements") or []
    for e in elements:
        # A natural shorthand: {"type": "poly"} for {"type": "shape", "kind": "poly"}.
        if e.get("type") in SHAPE_KINDS:
            e["kind"], e["type"] = e["type"], "shape"
    for e in elements:
        if e.get("type") not in ELEMENT_TYPES:
            problems.append(f"Element {e.get('id')!r} has type {e.get('type')!r}; the types are "
                            f"{', '.join(ELEMENT_TYPES)}.")
    elements = [e for e in elements if e.get("type") in ELEMENT_TYPES]
    scene["elements"] = elements
    ids = [e.get("id") for e in elements]
    by_id = {e.get("id"): e for e in elements}
    props = {p["key"]: p for p in scene.get("props") or [] if p.get("key")}

    if not elements:
        problems.append("The scene has no elements.")
    if len(elements) > MAX_ELEMENTS:
        problems.append(f"The scene has {len(elements)} elements; keep it to {MAX_ELEMENTS} at most.")
    if len(set(ids)) != len(ids) or not all(ids):
        problems.append("Every element needs its own unique id.")

    seen = set()
    for e in elements:
        eid, kind = e.get("id"), e.get("kind")
        where = f"Element {eid!r}"
        if e.get("type") == "shape":
            need = {"circle": ("x", "y", "r"), "star": ("x", "y", "r"), "polygon": ("x", "y", "r"),
                    "line": ("x", "y", "x2", "y2"), "arrow": ("x", "y", "x2", "y2"),
                    "rect": ("x", "y", "w", "h")}.get(kind, ())
            missing = [k for k in need if e.get(k) is None]
            if kind not in SHAPE_KINDS:
                problems.append(f"{where} is a shape with kind {kind!r}, which doesn't exist.")
            elif missing:
                problems.append(f"{where} ({kind}) is missing {', '.join(missing)}.")
            if kind == "poly" and len(e.get("vertices") or []) < 3:
                problems.append(f"{where} is a poly with fewer than 3 vertices.")
            for ref_key in ("on", "at"):
                if kind in ("square", "angle") and ref_key == ("on" if kind == "square" else "at"):
                    ref = e.get(ref_key) or {}
                    target = by_id.get(ref.get("of"))
                    if ref.get("of") not in seen or not target or target.get("kind") not in (
                            "poly", "polygon", "star", "square"):
                        problems.append(f"{where} ({kind}) must refer, with {ref_key}.of, to a shape "
                                        f"with corners listed before it.")
        elif e.get("type") == "label":
            text = e.get("text") or "".join(p.get("text", "") for p in e.get("parts") or [])
            if not text.strip():
                problems.append(f"{where} is a label with no text.")
            elif len(text) > MAX_LABEL_CHARS:
                problems.append(f"{where} has {len(text)} characters of text; keep labels "
                                f"under {MAX_LABEL_CHARS}.")
        elif e.get("type") == "prop":
            if e.get("asset") not in props:
                problems.append(f"{where} uses prop {e.get('asset')!r}, which isn't declared in props.")
        elif e.get("type") == "chart":
            if len(e.get("values") or []) < 2 or not all(e.get(k) for k in ("w", "h")):
                problems.append(f"{where} is a chart that needs w, h and at least two values.")
        if e.get("type") in ("label", "prop", "counter"):
            if not e.get("anchor") and (e.get("x") is None or e.get("y") is None):
                problems.append(f"{where} needs x and y, or an anchor.")
        anchor = e.get("anchor")
        if anchor and anchor.get("of") not in by_id:
            problems.append(f"{where} is anchored to {anchor.get('of')!r}, which doesn't exist.")
        for key in ("stroke", "fill", "dot", "color"):
            if e.get(key) and e[key] not in COLOR_TOKENS:
                e[key] = "ink" if key in ("stroke", "color") else "accent1"
        for part in e.get("parts") or []:
            if part.get("color") and part["color"] not in COLOR_TOKENS:
                part["color"] = "ink"
        seen.add(eid)

    actions = []
    for a in scene.get("actions") or []:
        target = by_id.get(a.get("target"))
        where = f"The {a.get('do')} action on {a.get('target')!r}"
        if target is None:
            problems.append(f"{where} targets an element that doesn't exist.")
            continue
        word = a.pop("word", None)
        if not isinstance(word, int) or not 0 <= word < max(1, len(words)):
            problems.append(f"{where} starts on word {word}, but the words run 0-{len(words) - 1}.")
            continue
        start = (words[word][1] if words else 0.0) + max(0.0, float(a.pop("delay", 0) or 0))
        a["at"] = round(min(max(0.0, start), max(0.0, duration - 0.15)), 3)
        a["dur"] = round(max(0.1, min(float(a.get("dur") or 0.6), duration - a["at"])), 3)
        if a["do"] == "count" and a.get("to") is None:
            problems.append(f"{where} has no `to` value.")
        if a["do"] == "move":
            if not a.get("to_xy") or len(a["to_xy"]) != 2:
                problems.append(f"{where} needs to_xy [x, y].")
            else:
                a["to"] = a.pop("to_xy")
        if a["do"] == "stack":
            if a.get("into") not in by_id:
                problems.append(f"{where} stacks into {a.get('into')!r}, which doesn't exist.")
                continue
            target["template"] = True
            a["count"] = int(min(9, max(2, a.get("count") or 5)))
        actions.append(a)
    scene["actions"] = actions
    # After the actions, which make a stacked prop a template.
    entering = {a["target"] for a in actions if a["do"] in ("appear", "draw", "write")}
    for e in elements:
        if not (e.get("template") or e.get("hidden") or e.get("id") in entering):
            problems.append(f"Element {e.get('id')!r} has no appear, draw or write action, so it "
                            f"is on screen from the first frame. Give it an entry on the word "
                            f"that names it, or mark it hidden: true if it only exists to "
                            f"anchor others.")
    scene["duration"] = round(duration, 3)
    scene["props"] = props
    return scene, problems


def layout_problems(boxes_over_time: list) -> list:
    """What the layout check reports, from `[(t, [{id, type, box}])]`
    measured in the browser."""
    problems = {}

    def note(key, text):
        problems.setdefault(key, text)

    for t, items in boxes_over_time:
        for it in items:
            left, top, right, bottom = it["box"]
            if right - left <= 1 or bottom - top <= 1:
                continue
            if left < SAFE_LEFT or right > SAFE_RIGHT or top < SAFE_TOP:
                note(("off", it["id"]), f"{it['id']!r} goes off the edge of the screen "
                                        f"(at {t:.1f}s it spans x {left:.0f}-{right:.0f}, "
                                        f"y {top:.0f}-{bottom:.0f}).")
            if bottom > CAPTION_TOP:
                note(("low", it["id"]), f"{it['id']!r} reaches y {bottom:.0f}, into the captions' "
                                        f"space below y {CAPTION_TOP}.")
        texts = [it for it in items if it["type"] in ("label", "counter")]
        for i, a in enumerate(texts):
            for b in texts[i + 1:]:
                if _overlap(a["box"], b["box"]) > 0.12:
                    note(("overlap", *sorted((a["id"], b["id"]))),
                         f"{a['id']!r} and {b['id']!r} overlap (at {t:.1f}s).")
        # Text half in, half out of an area reads as text sitting on a line.
        areas = [it for it in items if it["type"] == "shape" and it.get("kind") in AREA_KINDS]
        for text in texts:
            for area in areas:
                share = _overlap(text["box"], area["box"], of="first")
                if 0.2 < share < 0.8:
                    note(("edge", text["id"], area["id"]),
                         f"{text['id']!r} sits across the edge of {area['id']!r} (at {t:.1f}s); "
                         f"put it clearly inside or clearly outside.")
    return list(problems.values())


STAGE_MIN_W, STAGE_MIN_H = 560, 520    # the finished picture should fill at least this


def too_small(boxes_over_time: list) -> list:
    """A note when the finished picture huddles in a corner of the stage."""
    if not boxes_over_time:
        return []
    items = [it for it in boxes_over_time[-1][1] if it["box"][2] - it["box"][0] > 1]
    if not items:
        return []
    left = min(it["box"][0] for it in items)
    right = max(it["box"][2] for it in items)
    top = min(it["box"][1] for it in items)
    bottom = max(it["box"][3] for it in items)
    if right - left < STAGE_MIN_W and bottom - top < STAGE_MIN_H:
        return [f"The finished picture only fills x {left:.0f}-{right:.0f}, y {top:.0f}-{bottom:.0f}. "
                f"Draw it bigger: the stage is x 60-1020, y 110-1290."]
    return []


PICTURE_MODEL = "claude-haiku-4-5"
PICTURE_SYSTEM = """
You check an animated explainer scene before it is rendered. You see
stills from it, each with the words spoken up to that moment, and the
whole scene's narration. Report only real problems, as short fix
instructions for the scene's designer:

- Something the words name is missing or wrong: a ladder "against a
  wall" with no wall, a number attached to the wrong thing, an answer
  shown before it is worked out.
- Objects that should touch don't (floating, not resting where the words
  put them), or a picture that makes no sense for the words.
- Clutter or unreadable text: overlapping labels, text on busy lines,
  labels on things they don't describe.
- The picture is small and leaves most of the stage empty.

The bottom third is kept empty on purpose (captions go there); never
report that. The first still is mid-way, so things still to come are
fine there. Don't report style preferences. Return an empty list when
the scene is right.
""".strip()


def picture_problems(stills: list, spoken: list, narration: str) -> list:
    """Problems a look at the scene's stills finds: what measuring boxes
    can't, like a wall the words name that was never drawn. A failed call
    finds nothing: the frame check on the finished video still runs."""
    import base64
    from core.errors import PipelineError

    content = [{"type": "text", "text": f"The scene's narration: {narration}"}]
    for n, (image, said) in enumerate(zip(stills, spoken), 1):
        content.append({"type": "text", "text": f'Still {n}, after the words: "{said}"'})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.b64encode(image).decode("ascii")}})
    schema = {"type": "object",
              "properties": {"problems": {"type": "array", "items": {"type": "string"}}},
              "required": ["problems"], "additionalProperties": False}
    try:
        data = call_json(PICTURE_SYSTEM, content, schema, operation="scene_look",
                         model=PICTURE_MODEL, max_tokens=1500, effort=None)
    except PipelineError as exc:
        log.info(f"  [scene] picture check didn't run ({exc})")
        return []
    return [f"Picture check: {p}" for p in data.get("problems") or [] if p]


def _overlap(a, b, of: str = "smaller") -> float:
    """Intersection as a share of the smaller box (or of the first)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    base = area_a if of == "first" else min(area_a, (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / (base or 1)
