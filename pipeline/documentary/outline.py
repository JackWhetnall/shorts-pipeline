"""
The outline: what a documentary says, chapter by chapter, and how each
part is shown (decisions 074, 086).

Written before any narration, so the script is fitted to a story that
has been planned to show well, rather than a script hoped to make a good
visual story. Each chapter has what it says and what's seen, and the
whole has one through-line (the question or turning point it pays off)
and one visual concept (a motif, a colour script) that carries every
picture. The cast is everyone and everything that recurs, described for
a painter; members already in the channel's library keep their exact
names and descriptions, so they're drawn the same in every video.

It keeps the chosen angle's promise (pipeline.documentary.pitch) and is
built for retention (decision 086): a cold open of a minute at most that
states the promise and opens the questions the ending answers, backstory
only where the story needs it, a turn in every chapter, the payoff near
the end. The first Lincoln film spent 43% of itself on background before
the speech its title promised; `problems` catches the shape of that.
"""

from __future__ import annotations

import re

from core import curriculum
from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

MAX_TOKENS = 16000
EFFORT = "medium"
EARLIER_SHOWN = 8
COLD_OPEN_MAX = 1.2             # minutes: the first chapter is the hook, not the start of the story
# Decision 092: where a film's pictures happen, each at one scale, so a
# person never stands beside a planet cut open in space.
SCALES = ("space", "planet", "landscape", "human", "small", "microscopic", "cutaway")

SYSTEM = """
You are the story editor of a documentary channel. Plan one long-form
widescreen video, before a word of narration is written: what it says,
chapter by chapter, and how each part is shown as illustrated scenes in
the channel's drawn style.

The plan:
- `through_line`: the one question, choice or turning point the whole
  film builds to and pays off. A life is not a list of dates; find the
  thing that explains the rest.
- `visual_concept`: the one visual idea that carries every picture: how
  the light and colour move through the film (following the real time
  of day: bright clear daylight when it's day, warm dusk, lamplit night;
  never a whole film in gloom), a way of framing the subject, perhaps a
  motif. A motif appears in at most one scene in five, and only where it
  belongs physically (no lit lamp on a stage in daylight). Two films on
  this channel should look like the same series but never like the same
  film.
- `promise`: what the viewer was promised (the chosen angle's), in one
  sentence. The film keeps it.
{want}
- `open_loops`: two to four questions the opening raises that later
  chapters answer, the angle's open question last (answered at the end).
- `chapters`: in order, built to keep a viewer watching:
  - The first is the cold open, a minute at most: it starts with the
    angle's first line, shows the most striking pictures in the film,
    states the promise and raises the open loops. It is never an
    introduction, a date and the weather, or the start of a biography.
{start}
  - Every chapter turns on something new: a reveal, a reversal, a
    question answered and a sharper one opened, and ends on it, so the
    next chapter is needed. Somewhere between minutes three and six the
    stakes rise again (a re-hook).
  - The payoff (keeping the promise, closing the last loop) comes in the
    final fifth, concretely; then the film ends quickly, no summary.
  For each chapter:
  - `title`: what someone would search for or ask ("How he actually
    wrote it", "Why the crowd was silent"), not a poetic label, and never
    "cold open" or "chapter": these titles are the video's chapter list;
  - `says`: what the narration covers, in two to four sentences, with
    the facts, names, numbers and dates it needs;
  - `turn`: the reveal, reversal or new question it ends on, in a line;
  - `shows`: what is on screen, as scenes a painter could draw: places,
    people, actions, framings. Be concrete and visual. Show, don't
    caption: the picture adds what the words can't. Mix in, where they
    help, a real painting of the period (if the channel allows them) and
    animated cards: a big number, a comparison, a quote on screen, a
    timeline, a map of where we are;
  - `sound`: what's heard behind the narration there, one of: none,
    interior_fire, street_quiet, street_busy, market, night, rain, bells,
    countryside, sea, battle, hall, workshop;
  - `minutes`: its share of the running time.
- `settings`: the places the film keeps returning to, three to six,
  each at one scale: a laboratory; the view down its
  microscope; the drilling site on the tundra; the inside of the
  borehole; the whole planet, cut open, seen from space. Each has a
  `name`, its `scale` (space, planet, landscape, human, small,
  microscopic or cutaway) and a `description` a painter could hold on
  to: what is there, the light, how big things are. Every picture
  happens in exactly one setting and shows only what exists there at
  that scale. Something from another setting is seen only through a real
  thing in this one (a creature on the lab's monitor, a globe on a desk,
  a map on a wall), never placed in it. A cutaway or microscopic setting
  holds only what is really inside it: a person exists there only if a
  person could really stand there. A picture the film doesn't return to
  (a visual metaphor, an example, a comparison) has a place of its own
  and isn't listed.
- `cast`: the people and particular objects that must look the same in
  more than one picture, with `kind` (character or object), `settings`
  (the names of every setting it can be seen in: a drill bit is in the
  shaft, and on the rig when it's hauled up; a person isn't inside a
  planet's cutaway, a microbe isn't on the lab bench) and a
  `description` a painter could hold on to: for a person, their age in
  this film, face, hair, build, period-accurate clothes and colours. A
  diagram, a cutaway, a symbol or an idea is never cast: each picture
  draws it as that moment needs. Places are settings, not cast. Keep the
  cast small. The same person at very different ages is
  two members ("George Washington (young surveyor)" and "George
  Washington (president)"). Describe who they are and how they look,
  never the medium or art style they're drawn in (no "felt figure", no
  "watercolour"): the channel's look supplies that, and may change.
  Members from the channel's library, listed with the request, keep
  their exact name and description, copied word for word.
- `title_options`: three titles, the chosen angle's first, each at most
  55 characters with the tension first.

The pictures never contain words: no signs, tags, labels, banners,
letters or written pages that can be read. A name, date or place the
viewer needs goes in an on-screen caption, which is added separately.

Accuracy: names, dates, titles and outcomes are right. Legend and
legitimate speculation are welcome when they're said to be legend or
speculation; nothing is invented and presented as fact. Never make
light of tragedy, illness, war or death.
""".strip()


def system_text(channel) -> str:
    """The plan's instructions for this channel's kind of film (decision 089)."""
    from pipeline.documentary import kinds
    kind = kinds.of(channel)
    return (SYSTEM.replace("{want}", kinds.OUTLINE_WANT[kind]).replace("{start}", kinds.OUTLINE_START[kind])
            + kinds.OUTLINE_SOUND[kind])


def _sounds():
    from pipeline.documentary.ambience import SOUNDS
    return SOUNDS.keys()


def schema() -> dict:
    chapter = {"type": "object", "properties": {
        "title": {"type": "string"}, "says": {"type": "string"}, "turn": {"type": "string"},
        "shows": {"type": "string"}, "sound": {"type": "string", "enum": list(_sounds())},
        "minutes": {"type": "number"}},
        "required": ["title", "says", "turn", "shows", "sound", "minutes"], "additionalProperties": False}
    member = {"type": "object", "properties": {
        "name": {"type": "string"}, "kind": {"type": "string", "enum": ["character", "place", "object"]},
        "settings": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"}},
        "required": ["name", "kind", "settings", "description"], "additionalProperties": False}
    setting = {"type": "object", "properties": {
        "name": {"type": "string"}, "scale": {"type": "string", "enum": list(SCALES)},
        "description": {"type": "string"}},
        "required": ["name", "scale", "description"], "additionalProperties": False}
    return {"type": "object", "properties": {
        "title_options": {"type": "array", "items": {"type": "string"}},
        "through_line": {"type": "string"},
        "promise": {"type": "string"},
        "want": {"type": "string"},
        "open_loops": {"type": "array", "items": {"type": "string"}},
        "visual_concept": {"type": "string"},
        "chapters": {"type": "array", "items": chapter},
        "settings": {"type": "array", "items": setting},
        "cast": {"type": "array", "items": member}},
        "required": ["title_options", "through_line", "promise", "want", "open_loops", "visual_concept",
                     "chapters", "settings", "cast"],
        "additionalProperties": False}


def earlier(channel_key: str, subtopic_id: str) -> str:
    """The channel's other planned videos, for continuity: the series
    should feel like one, and no two films alike."""
    from core import production
    rows = [p for p in production.all_for(channel_key)
            if p["subtopic_id"] != subtopic_id and p.get("outline")][-EARLIER_SHOWN:]
    return "\n".join(f"- {p.get('title') or p['subtopic_id']}: through-line: "
                     f"{p['outline'].get('through_line', '')} Visual concept: "
                     f"{p['outline'].get('visual_concept', '')}" for p in rows)


def angle_text(angle: dict) -> str:
    """The chosen angle, as the writers after the pitch are told it."""
    if not angle:
        return ""
    thumb = angle.get("thumbnail") or {}
    words = f' with the words "{thumb["words"]}"' if thumb.get("words") else ""
    return (f"The film's chosen angle (keep its promise):\n- Title: {angle.get('title', '')}\n"
            f"- Thumbnail: {thumb.get('subject', '')}{words}\n"
            f"- Promise: {angle.get('promise', '')}\n- First line: {angle.get('hook', '')}\n"
            f"- The question only the ending answers: {angle.get('open_loop', '')}")


def problems(outline: dict, minutes: float) -> list:
    """What breaks the retention rules in an outline, or []."""
    found = []
    chapters = outline.get("chapters") or []
    if chapters and chapters[0]["minutes"] > COLD_OPEN_MAX:
        found.append(f"The cold open (chapter 1) runs {chapters[0]['minutes']:g} minutes; it must be at "
                     f"most {COLD_OPEN_MAX:g}, ending on the open loops, with the story starting in chapter 2.")
    flat = [c["title"] for c in chapters if not c.get("turn")]
    if flat:
        found.append("These chapters don't turn on anything: " + "; ".join(flat[:4]))
    if not outline.get("open_loops"):
        found.append("No open loops: the opening must raise questions the later chapters answer.")
    untitled = [str(n) for n, c in enumerate(chapters, start=1) if c.get("untitled")]
    if untitled:
        found.append(f"Chapter(s) {', '.join(untitled)} have no real title; give each the question or "
                     f"idea a viewer would look for, never 'cold open', 'intro' or 'chapter'.")
    if not outline.get("settings"):
        found.append("No settings: name the places the pictures happen in, each at one scale.")
    homeless = [m["name"] for m in outline.get("cast") or [] if outline.get("settings") and not m.get("settings")]
    if homeless:
        found.append("These cast members exist in no setting: " + "; ".join(homeless[:4]))
    return found


def write(channel, row: dict, note: str = "", angle: dict = None) -> dict:
    """The outline for one plan entry, keeping `angle`'s promise. About
    three cents; one more round if it breaks the retention rules."""
    from core import lessons
    from pipeline.documentary import cast as library
    topic = curriculum.find_topic(channel.key, row["topic"]) or {}
    minutes = float(channel.documentary.minutes)
    system = [SystemBlock(system_text(channel), cacheable=True),
              SystemBlock(f"The channel's brief for its writers:\n\n{channel.style_prompt}"
                          + (f"\n\nHow it opens a video: {channel.hook_style}" if channel.hook_style else ""))]
    look = _look_text(channel)
    parts = [f"The video: {row['title']}" + (f" ({row['angle']})" if row.get("angle") else ""),
             f"Part of: {topic.get('title', '')}" + (f": {topic['summary']}" if topic.get("summary") else ""),
             angle_text(angle or {}),
             f"Running time: about {minutes:g} minutes, in {_chapters_for(minutes)} chapters "
             f"(the cold open counted).",
             f"The channel's drawn style: {look}" if look else "",
             "Real paintings of the period may be shown." if _paintings(channel) else "",
             lessons.for_prompt(channel.key)]
    known = library.for_prompt(channel.key)
    if known:
        parts.append("The channel's cast library (reuse a member's exact name and description "
                     "whenever they appear):\n" + known)
    before = earlier(channel.key, row["id"])
    if before:
        parts.append("The channel's other films, for a series that feels like one but never "
                     "repeats a film:\n" + before)
    if channel.avoid_imagery:
        parts.append("Never show (the channel rules these out; keep them out of every chapter's "
                     "pictures): " + ", ".join(channel.avoid_imagery))
    if note:
        parts.append(f"The owner asks: {note}")
    user = "\n\n".join(p for p in parts if p)
    data = clean(call_json(system, user, schema(), operation="documentary_outline",
                           max_tokens=MAX_TOKENS, effort=EFFORT), minutes)
    found = problems(data, minutes)
    if found:
        log.info(f"  [documentary] outline breaks the retention rules ({'; '.join(found)[:200]}); once more")
        again = clean(call_json(system, user + "\n\nYour last outline broke these rules; fix them:\n- "
                                + "\n- ".join(found), schema(), operation="documentary_outline",
                                max_tokens=MAX_TOKENS, effort=EFFORT), minutes)
        if len(problems(again, minutes)) <= len(found):
            data = again
    if angle and angle.get("title"):
        data["title_options"] = [angle["title"]] + [t for t in data["title_options"] if t != angle["title"]][:2]
    return data


def _paintings(channel) -> bool:
    from pipeline import artwork
    return artwork.allowed(channel)


def _chapters_for(minutes: float) -> str:
    low = max(3, round(minutes / 2))
    return f"{low} to {low + 2}"


def _look_text(channel) -> str:
    if not channel.animation.style:
        return ""           # not chosen yet: nothing to write for
    try:
        from pipeline.animation import style
        _, look = style.compile(channel.animation, frame="wide")
        return f"{look['label']}: {look['description']}"
    except Exception:  # noqa: BLE001 - the outline is still worth writing without it
        return ""


PRODUCTION_WORDS = re.compile(r"^\s*(?:cold open|opening|intro(?:duction)?|chapter\s+\w+|part\s+\w+)\s*[:\-–—.]*\s*",
                              re.IGNORECASE)


def chapter_title(raw, turn: str = "") -> str:
    """A chapter's title as viewers see it in the chapter list: without
    "Cold open -" or "Chapter 2:" in front, and without dashes. A title
    that was only "Cold Open" takes the chapter's turn instead."""
    title = " ".join(str(raw or "").split())
    stripped = PRODUCTION_WORDS.sub("", title).strip(" -–—:")
    if not stripped and turn:
        first = re.split(r"(?<=[.!?])\s", " ".join(str(turn).split()))[0].rstrip(".")
        stripped = first if len(first) <= 60 else " ".join(first[:60].split()[:-1])
    title = stripped or title
    return re.sub(r"\s*[–—]\s*|\s+-\s+", ": ", title, count=1)


def clean(data: dict, minutes: float) -> dict:
    # A title that was only "Cold open" falls back to what the chapter says
    # (decision 093): its turn was once a production note, "The question is
    # stated as a promise: ...", which became the video's first chapter.
    chapters = [{"title": chapter_title(c.get("title"), c.get("says")),
                 **({"untitled": True} if not PRODUCTION_WORDS.sub("", str(c.get("title") or "")).strip(" -–—:")
                    else {}),
                 "says": str(c.get("says") or "").strip(), "turn": str(c.get("turn") or "").strip(),
                 "shows": str(c.get("shows") or "").strip(),
                 "sound": c.get("sound") if c.get("sound") in _sounds() else "none",
                 "minutes": max(0.2, float(c.get("minutes") or 1))}
                for c in data.get("chapters") or [] if str(c.get("says") or "").strip()]
    if not chapters:
        raise PipelineError("outline had no chapters",
                            user_message="The outline came back without any chapters. Try again.")
    # Shares of the running time, whatever they summed to.
    total = sum(c["minutes"] for c in chapters)
    for c in chapters:
        c["minutes"] = round(c["minutes"] * minutes / total, 1)
    settings, named = [], {}
    for s in data.get("settings") or []:
        name = " ".join(str(s.get("name") or "").split())
        if name and name.lower() not in named:
            named[name.lower()] = name
            settings.append({"name": name, "scale": s.get("scale") if s.get("scale") in SCALES else "human",
                             "description": " ".join(str(s.get("description") or name).split())})
    cast, seen = [], set()
    for m in data.get("cast") or []:
        name = " ".join(str(m.get("name") or "").split())
        if name and name.lower() not in seen and name.lower() not in named:
            seen.add(name.lower())
            member = {"name": name, "kind": m.get("kind") if m.get("kind") in ("character", "place", "object")
                      else "character", "description": " ".join(str(m.get("description") or name).split())}
            if settings:
                member["settings"] = [named[w.strip().lower()] for w in m.get("settings") or []
                                      if w.strip().lower() in named]
            cast.append(member)
    return {"title_options": [t.strip() for t in data.get("title_options") or [] if t.strip()][:3],
            "through_line": str(data.get("through_line") or "").strip(),
            "promise": str(data.get("promise") or "").strip(),
            "want": str(data.get("want") or "").strip(),
            "open_loops": [" ".join(str(q).split()) for q in data.get("open_loops") or [] if str(q).strip()][:4],
            "visual_concept": str(data.get("visual_concept") or "").strip(),
            "chapters": chapters, "settings": settings, "cast": cast}
