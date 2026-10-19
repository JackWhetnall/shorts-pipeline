"""
The angle: how a documentary wins the click and the first minute,
decided before a word of it is written (decision 086).

Most of a video's reach is settled by its idea, title and thumbnail, and
most of its retention by its first thirty seconds, so these come first,
not last. Six angles on the plan entry, each with a title, a thumbnail
idea, the promise it makes, the film's first line and the question it
leaves open, scored for how well they'd do; the best is chosen unless the
owner picks another. The outline, the script, the thumbnail and the
teasers all keep the chosen angle's promise.

Kept honest by checks the model can't argue with: a title past 55
characters, or one that opens on a label ("X and Y: ..."), is marked
down; a thumbnail gets four words at most.
"""

from __future__ import annotations

import re

from core import curriculum
from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

MAX_TOKENS = 8000
EFFORT = "medium"
ANGLES = 6
TITLE_MAX = 55                 # what a phone shows of a title, about
THUMB_WORDS = 4

SYSTEM = """
You are the packaging editor of a YouTube documentary channel. Before a
word of a film is written, you decide how it will win the click and keep
the viewer for the first minute. On YouTube the idea, the title and the
thumbnail decide most of a video's reach, and the first thirty seconds
decide most of its retention.

Pitch {angles} different angles on the film you're given. A good angle is
familiar but unexpected: a subject people already know, from a side they
don't (a contradiction, a surprising number, a "why", a myth against what
happened, a choice with real stakes, the moment everything turned). The
angles differ in kind, not just wording.

For each angle:
- `title`: at most 55 characters, the tension or the subject's name in
  the first words. A specific promise, never a label: not "Lincoln and
  the Gettysburg Address: The Speech Nobody Expected" but "Why Lincoln's
  2-Minute Speech Beat a 2-Hour One". No clickbait it can't pay off,
  and never a claim the film's own answer contradicts or walks back.
  The title, or failing that the thumbnail's words, names the familiar
  subject (the person, place, era or event: "plague", "Rome", "1665")
  so a stranger knows at a glance what it's about.
- `thumbnail`: what the thumbnail shows. `subject` is the one thing that
  fills about a third of the frame, usually a face with a specific
  expression, or one striking object; `words` is at most four words that
  ADD to the title rather than repeat it (a number, a contrast, a
  question), or "" for none.
- `promise`: one sentence, what the viewer will get by watching.
- `hook`: the film's first spoken line or two (at most 35 words). It
  states the promise in the first ten seconds, with the most surprising
  concrete thing in the film. Never a date and the weather, a greeting,
  "imagine", or backstory.
- `open_loop`: the question the hook raises that only the film's ending
  answers.
- `scores`: 1 to 10 each, honestly: `curiosity` (would a stranger
  scrolling past need to click?), `familiarity` (do enough people know
  the subject to care?), `clarity` (is the promise understood in one
  glance?), `payoff` (can the film really deliver it?).
- `why`: one short line on why it would do well.

Spoken lines are read by a voice engine: no dashes, numbers as they're
said.
""".strip()


def schema() -> dict:
    angle = {"type": "object", "properties": {
        "title": {"type": "string"},
        "thumbnail": {"type": "object", "properties": {
            "subject": {"type": "string"}, "words": {"type": "string"}},
            "required": ["subject", "words"], "additionalProperties": False},
        "promise": {"type": "string"}, "hook": {"type": "string"}, "open_loop": {"type": "string"},
        "scores": {"type": "object", "properties": {
            "curiosity": {"type": "integer"}, "familiarity": {"type": "integer"},
            "clarity": {"type": "integer"}, "payoff": {"type": "integer"}},
            "required": ["curiosity", "familiarity", "clarity", "payoff"], "additionalProperties": False},
        "why": {"type": "string"}},
        "required": ["title", "thumbnail", "promise", "hook", "open_loop", "scores", "why"],
        "additionalProperties": False}
    return {"type": "object", "properties": {"angles": {"type": "array", "items": angle}},
            "required": ["angles"], "additionalProperties": False}


LABEL_OPENING = re.compile(r"^[^:]{6,}:\s")       # "Lincoln and the Gettysburg Address: ..."


GENERIC = {"a", "an", "the", "day", "days", "life", "lives", "with", "from", "into", "about", "what", "when",
           "where", "history", "story", "of", "in", "on", "as", "and", "how", "why", "who"}


def subject_words(subject: str) -> set:
    """The words that say what a film is about, from its plan entry's
    title: "A Day in Plague London, 1665" -> plague, london, 1665."""
    return {w.lower() for w in re.findall(r"[A-Za-z0-9']+", subject or "")
            if (len(w) >= 4 or w.isdigit()) and w.lower() not in GENERIC and "'" not in w}


def title_problems(title: str, words: str = "", subject: str = "") -> list:
    """What's wrong with a title as packaging, or []. `words`: the
    thumbnail's; `subject`: the plan entry's title, which the title or
    the thumbnail must name."""
    problems = []
    if len(title) > TITLE_MAX:
        problems.append(f"{len(title)} characters (a phone shows about {TITLE_MAX})")
    if LABEL_OPENING.match(title) and " and " in title.split(":")[0]:
        problems.append("opens on a label")
    wanted = subject_words(subject)
    said = {w.lower() for w in re.findall(r"[A-Za-z0-9']+", f"{title} {words}")}
    if wanted and not wanted & said:
        problems.append(f"doesn't name its subject ({', '.join(sorted(wanted))})")
    return problems


def score(angle: dict) -> float:
    """The angle's score: the model's four, with the curiosity it brings to
    a stranger counted double, less a point for each problem."""
    s = angle.get("scores") or {}
    total = 2 * s.get("curiosity", 0) + s.get("familiarity", 0) + s.get("clarity", 0) + s.get("payoff", 0)
    return round(total / 5 - len(angle.get("problems") or []), 2)


def clean(data: dict, subject: str = "") -> dict:
    angles = []
    for a in data.get("angles") or []:
        title = " ".join(str(a.get("title") or "").split()).strip(" .")
        if not title:
            continue
        thumb = a.get("thumbnail") or {}
        words = " ".join(str(thumb.get("words") or "").split()[:THUMB_WORDS])
        scores = {k: max(1, min(10, int((a.get("scores") or {}).get(k) or 5)))
                  for k in ("curiosity", "familiarity", "clarity", "payoff")}
        angle = {"title": title,
                 "thumbnail": {"subject": " ".join(str(thumb.get("subject") or "").split()), "words": words},
                 "promise": " ".join(str(a.get("promise") or "").split()),
                 "hook": " ".join(str(a.get("hook") or "").split()),
                 "open_loop": " ".join(str(a.get("open_loop") or "").split()),
                 "scores": scores, "why": " ".join(str(a.get("why") or "").split())}
        angle["problems"] = title_problems(title, words, subject)
        angle["score"] = score(angle)
        angles.append(angle)
    if not angles:
        raise PipelineError("pitch had no angles", user_message="The angles came back empty. Try again.")
    chosen = max(range(len(angles)), key=lambda i: angles[i]["score"])
    return {"angles": angles, "chosen": chosen}


def earlier_titles(channel_key: str, subtopic_id: str) -> list:
    from core import production
    out = []
    for data in production.all_for(channel_key):
        if data["subtopic_id"] == subtopic_id:
            continue
        angle = production.chosen_angle(data)
        title = angle.get("title") or ((data.get("outline") or {}).get("title_options") or [""])[0]
        if title:
            out.append(title)
    return out[-12:]


def write(channel, row: dict, note: str = "") -> dict:
    """Angles for one plan entry, the best chosen. About two cents."""
    from core import lessons
    from pipeline.documentary import kinds
    topic = curriculum.find_topic(channel.key, row["topic"]) or {}
    extra = kinds.PITCH[kinds.of(channel)]
    system = [SystemBlock(SYSTEM.format(angles=ANGLES) + (f"\n\n{extra}" if extra else ""), cacheable=True),
              SystemBlock(f"The channel: {channel.channel_display_name or channel.key}. Its brief for "
                          f"its writers:\n\n{channel.style_prompt}"
                          + (f"\n\nHow it opens a video: {channel.hook_style}" if channel.hook_style else ""))]
    parts = [f"The film: {row['title']}" + (f" ({row['angle']})" if row.get("angle") else ""),
             f"Part of: {topic.get('title', '')}" + (f": {topic['summary']}" if topic.get("summary") else ""),
             f"Running time: about {float(channel.documentary.minutes):g} minutes."]
    taught = lessons.for_prompt(channel.key)
    if taught:
        parts.append(taught)
    before = earlier_titles(channel.key, row["id"])
    if before:
        parts.append("The channel's other films (don't repeat their angle or title shape):\n"
                     + "\n".join(f"- {t}" for t in before))
    if note:
        parts.append(f"The owner asks: {note}")
    data = call_json(system, "\n\n".join(parts), schema(), operation="documentary_pitch",
                     max_tokens=MAX_TOKENS, effort=EFFORT)
    return clean(data, row["title"])
