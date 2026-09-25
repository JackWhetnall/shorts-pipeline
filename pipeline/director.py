"""
The visual director: for each segment, the kind of picture that fits.

    footage       real people, animals, places, objects and actions (stock)
    illustration  something that can't be filmed, drawn in the channel's style
    template      a designed motion graphic: a number, a comparison, a list, a
                  process, a timeline, a definition, an equation... (pipeline.templates)
    diagram       a free-form constructed drawing, for geometry and plots only
    artwork       a public-domain painting or engraving (pipeline.artwork), when
                  the channel allows it; a real picture, so not held to the bar

One Sonnet call reads the whole script and chooses, with a reason, a
brief, and a score for how much the segment needs something other than
real footage. The channel's slider is the bar that score must clear
(pipeline.scenes.writer.need_threshold): all the way to footage never
leaves it, all the way the other way never uses it, in between a
segment gets a graphic only when it genuinely beats footage. The
director is never told the slider, so the same script is judged the same
way on every channel. See decision 040.
"""

from __future__ import annotations

from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json
from pipeline.scenes.writer import need_threshold
from pipeline.templates import library

log = get_logger(__name__)

MEDIA = ("footage", "illustration", "template", "diagram", "artwork")
GRAPHICS = ("illustration", "template", "diagram")
MAX_TOKENS = 5000
EFFORT = "low"

INTRO = """
You are the visual director of a short vertical explainer video. For each
spoken segment, choose what is on screen while it's said:

- footage: real stock video. Best for people, animals, places, objects and
  actions: anything a camera can film. A dog yawning is footage.
""".strip()

ARTWORK = """
- artwork: a real public-domain painting, engraving or print from a museum
  collection, slowly panned. For history, historical people, myths,
  scripture, literature and art itself, when a well-known work would show
  what's being said. Never for anything modern. Its brief is a museum
  search of 2-4 words: names and titles ("Samson Delilah", "Battle of
  Trafalgar", "Ophelia").
""".strip()

GRAPHICS_GUIDE = """
- illustration: one image drawn in the channel's style, slowly pushed in.
  For what can't be filmed: inside the body, the past, a metaphor, a
  scene from a story or scripture.
- template: a designed motion graphic, filled with the segment's words and
  numbers. For structure the viewer should see: a number, a comparison, a
  list, steps, a timeline, a definition, a quote, an equation, a
  proportion, sizes. The templates:
{catalogue}
- diagram: a free-form constructed drawing. Only for geometry (shapes,
  angles, constructions) and plotted graphs. Never for anything else.
""".strip()

OUTRO = """
Also score how much each segment NEEDS something other than footage, 0-10:
10 means footage genuinely can't carry it (a calculation, a structure with
named parts, a statistic that is the point); 5 means a graphic helps but
footage would do; 0 means footage is clearly best. Judge the segment by
itself.

Make it a good video, not a slideshow: vary the media and never use the
same template twice in a row. The opening segment should be the most
striking picture you can get. Everything must match what the words say.

For each segment give: medium, template (name, when medium is template),
brief (for footage: what to film; for illustration: the image to draw,
concretely; for template: what it shows, with the words' actual numbers;
for diagram: the construction; for artwork: the museum search), need, and
reason (a few words).
""".strip()


def _guide(media: list) -> str:
    parts = [INTRO]
    if "artwork" in media:
        parts.append(ARTWORK)
    if "template" in media:
        parts.append(GRAPHICS_GUIDE.format(catalogue=library.catalogue()))
    return "\n".join(parts) + "\n\n" + OUTRO


def _schema(media: list = MEDIA) -> dict:
    return {"type": "object", "properties": {"segments": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "medium": {"type": "string", "enum": list(media)},
            "template": {"type": "string", "enum": ["", *library.TEMPLATES]},
            "brief": {"type": "string"},
            "need": {"type": "integer"},
            "reason": {"type": "string"},
        },
        "required": ["index", "medium", "template", "brief", "need", "reason"],
        "additionalProperties": False}}},
        "required": ["segments"], "additionalProperties": False}


def direct(segments: list, subject: str, share: int, skip: set = frozenset(),
           artwork: bool = False) -> list:
    """[{index, medium, template, brief, need, reason}] for every segment
    not in `skip` (already pictured), with the channel's bar applied to
    graphics: below it, footage. `artwork` offers museum paintings too,
    which are real pictures and so are never held to the bar."""
    bar = need_threshold(share)
    todo = [i for i in range(len(segments)) if i not in skip]
    media = ["footage", *(["artwork"] if artwork else []), *(GRAPHICS if bar is not None else [])]
    if media == ["footage"] or not todo:
        return [{"index": i, "medium": "footage", "template": "", "brief": segments[i].shot_brief,
                 "need": 0, "reason": "the channel uses footage"} for i in todo]
    lines = "\n".join(f"[{i}] ({segments[i].duration:.1f}s) {segments[i].text}" for i in todo)
    data = call_json([SystemBlock(_guide(media), cacheable=True)],
                     f"The video is about: {subject}\n\nSegments:\n{lines}", _schema(media),
                     operation="director", max_tokens=MAX_TOKENS, effort=EFFORT)
    chosen = {r["index"]: r for r in data.get("segments") or []
              if isinstance(r.get("index"), int) and r["index"] in todo}
    out = []
    for i in todo:
        r = dict(chosen.get(i) or {"medium": "footage", "template": "", "brief": "", "need": 0,
                                   "reason": "not directed"})
        r["index"] = i
        r["brief"] = (r.get("brief") or "").strip() or segments[i].shot_brief or segments[i].text
        if r.get("medium") not in media:
            r["medium"] = "footage"
        if r["medium"] == "template" and r.get("template") not in library.TEMPLATES:
            r["medium"] = "illustration"
        if r["medium"] in GRAPHICS and int(r.get("need") or 0) < bar:
            log.info(f"  [director] segment {i}: {r['medium']} scores {r.get('need')} < {bar:g}; footage")
            r["medium"] = "footage"
            r["brief"] = segments[i].shot_brief or r["brief"]
        if r["medium"] == "footage" and bar == 0:
            # All the way to "always animated": never footage.
            r["medium"] = "illustration"
        out.append(r)
    return out
