"""
An ordered syllabus of topics for a channel, and where it has got to.

## The problem this replaces

A topic channel had `topics: ["…", "…"]` and picked one at random. Three
things were wrong with that. The same topic came up twice. Nothing put
easy before hard, so a maths channel could open on an obscure lemma while
the obvious accessible ideas went unmade. And at two videos a day, a
hand-written list is exhausted in a fortnight.

## Why a syllabus is generated in two layers, not one

The obvious answer is "generate a thousand topics up front". That is
right about ordering and wrong about generation, for two reasons.

A thousand usable topics is 40-60k output tokens. That is not one
response; batching is unavoidable whatever the design says. And a list
written on day one is written with no information — by video 200 you know
which topics got discarded and why, and the remaining 800 were fixed
before any of that existed.

But ordering genuinely does have to be global. Deciding "what next" one
video at a time cannot produce accessible-before-specialist, because each
local decision has no view of the arc.

So the two things are separated:

- **The outline** — 20-30 units, ordered foundation to specialist,
  generated once in a single cheap call. This is where the pedagogy
  lives, and 25 unit titles are something a person can actually read and
  correct. A thousand topics are not.
- **The topics** — generated a unit at a time, on demand, each call given
  the outline for context and every title already used so it cannot
  repeat itself.

The result is a globally ordered thousand-topic curriculum that costs one
call per unit as you reach it, stays correctable, and can be informed by
what has already happened.

## Statuses

`pending` → `used` when a video is generated from it → `published` when
that video is published. `skipped` is a deliberate "not this one".

A discarded video **returns its topic to pending**. A take that did not
work is not a topic that has been covered, and losing it would silently
put a hole in the syllabus.

## Storage

One file per channel, `config/curricula/<key>.json`, kept as an ordered
list rather than a database: it is read whole, written whole, a thousand
entries is well under a megabyte, and being able to open it in an editor
and fix a topic by hand is worth more here than query speed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import PROJECT_ROOT, safe_join

log = get_logger(__name__)

CURRICULA_DIR = PROJECT_ROOT / "config" / "curricula"

SCHEMA_VERSION = 1

PENDING, USED, PUBLISHED, SKIPPED = "pending", "used", "published", "skipped"
STATUSES = (PENDING, USED, PUBLISHED, SKIPPED)

# Levels, easiest first. Ordering units by this is a check on the model's
# own ordering rather than a replacement for it — the prompt asks for a
# sensible progression, and this catches an outline that ignored it.
LEVELS = ("foundation", "intermediate", "advanced", "specialist")

# How few pending topics is too few. At two videos a day this is about
# two weeks of runway, which is enough warning to generate more without
# ever being the thing that blocks a video.
LOW_WATER_MARK = 30


class CurriculumError(PipelineError):
    """Something is wrong with a channel's syllabus."""


def path_for(channel_key: str) -> Path:
    return safe_join(CURRICULA_DIR, f"{channel_key}.json")


def exists(channel_key: str) -> bool:
    try:
        return path_for(channel_key).exists()
    except PipelineError:
        return False


def load(channel_key: str) -> dict:
    """The whole syllabus, or an empty one if there isn't a file.

    Returns the empty shape rather than raising, so every caller can ask
    "does this channel have a curriculum" by looking at `units`.
    """
    path = path_for(channel_key)
    if not path.exists():
        return blank(channel_key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CurriculumError(
            f"{path} is not valid JSON: {exc}",
            user_message=f"This channel's topic plan is damaged. Fix or delete "
                         f"config/curricula/{channel_key}.json.",
        )
    data.setdefault("units", [])
    data.setdefault("topics", [])
    return data


def blank(channel_key: str) -> dict:
    return {"version": SCHEMA_VERSION, "channel": channel_key, "subject": "",
            "generated_at": "", "units": [], "topics": []}


def save(data: dict) -> None:
    """Write the whole file.

    Via a temporary file and a replace: a syllabus is the record of what a
    channel has already covered, and a half-written one after a crash
    would mean regenerating topics that have been published.
    """
    path = path_for(data["channel"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- building -------------------------------------------------------

def start(channel_key: str, subject: str, units: list) -> dict:
    """Create a syllabus from a generated outline. No topics yet."""
    data = blank(channel_key)
    data["subject"] = subject
    data["generated_at"] = _now()
    data["units"] = [
        {"id": f"u{i + 1:02d}",
         "title": unit["title"],
         "summary": unit.get("summary", ""),
         "level": unit.get("level") if unit.get("level") in LEVELS else "intermediate",
         "target_topics": int(unit.get("target_topics", 40)),
         "filled": False}
        for i, unit in enumerate(units)
    ]
    save(data)
    return data


def add_topics(channel_key: str, unit_id: str, topics: list) -> dict:
    """Append one unit's topics, in the order given.

    Titles already anywhere in the syllabus are dropped rather than
    appended. The generator is told what exists and asked not to repeat,
    but "asked not to" is not a guarantee, and a duplicate topic is the
    exact failure this whole system is here to prevent.
    """
    data = load(channel_key)
    unit = _unit(data, unit_id)

    seen = {t["title"].strip().lower() for t in data["topics"]}
    position = len(data["topics"])
    added = 0
    for topic in topics:
        title = (topic.get("title") or "").strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        position += 1
        data["topics"].append({
            "id": f"t{position:04d}",
            "unit": unit_id,
            "position": position,
            "title": title,
            "angle": (topic.get("angle") or "").strip(),
            "status": PENDING,
            "video_stem": "",
            "used_at": "",
            "note": "",
        })
        added += 1

    unit["filled"] = True
    save(data)
    if added < len(topics):
        log.info(f"{channel_key}: dropped {len(topics) - added} duplicate topic(s) "
                 f"for unit {unit_id}")
    return data


def _unit(data: dict, unit_id: str) -> dict:
    for unit in data["units"]:
        if unit["id"] == unit_id:
            return unit
    raise CurriculumError(
        f"no unit {unit_id} in {data['channel']}",
        user_message="That part of the topic plan no longer exists.",
    )


def next_unfilled_unit(channel_key: str) -> dict:
    """The earliest unit with no topics yet, or None.

    Earliest, not any: units are filled in order so the buffer of pending
    topics always continues the arc rather than jumping ahead of it.
    """
    for unit in load(channel_key)["units"]:
        if not unit.get("filled"):
            return unit
    return None


# --- reading --------------------------------------------------------

def topics(channel_key: str, status: str = None, unit_id: str = None) -> list:
    rows = load(channel_key)["topics"]
    if status:
        rows = [t for t in rows if t["status"] == status]
    if unit_id:
        rows = [t for t in rows if t["unit"] == unit_id]
    return rows


def find(channel_key: str, topic_id: str) -> dict:
    for topic in load(channel_key)["topics"]:
        if topic["id"] == topic_id:
            return topic
    return None


def next_pending(channel_key: str) -> dict:
    """The next topic to make a video from, in syllabus order."""
    for topic in load(channel_key)["topics"]:
        if topic["status"] == PENDING:
            return topic
    return None


def pending_count(channel_key: str) -> int:
    return sum(1 for t in load(channel_key)["topics"] if t["status"] == PENDING)


def progress(channel_key: str) -> dict:
    """Counts, and how long the remaining topics last.

    `runway_days` assumes two videos a day because that is the cadence
    this was sized for; it is a rough "when do I need to think about
    this", not a schedule.
    """
    data = load(channel_key)
    rows = data["topics"]
    counts = {status: sum(1 for t in rows if t["status"] == status) for status in STATUSES}
    done = counts[USED] + counts[PUBLISHED]
    return {
        "has_curriculum": bool(data["units"]),
        "subject": data.get("subject", ""),
        "unit_count": len(data["units"]),
        "units_filled": sum(1 for u in data["units"] if u.get("filled")),
        "total": len(rows),
        "planned_total": sum(u.get("target_topics", 0) for u in data["units"]),
        **counts,
        "done": done,
        "percent_done": (done / len(rows) * 100) if rows else 0.0,
        "runway_days": counts[PENDING] // 2,
        "running_low": counts[PENDING] < LOW_WATER_MARK,
    }


def units_with_topics(channel_key: str) -> list:
    """The outline with its topics attached, for the curriculum page."""
    data = load(channel_key)
    by_unit = {}
    for topic in data["topics"]:
        by_unit.setdefault(topic["unit"], []).append(topic)

    rows = []
    for unit in data["units"]:
        mine = by_unit.get(unit["id"], [])
        rows.append({
            **unit,
            "topics": mine,
            "done": sum(1 for t in mine if t["status"] in (USED, PUBLISHED)),
            "skipped": sum(1 for t in mine if t["status"] == SKIPPED),
        })
    return rows


# --- status transitions ---------------------------------------------

def _set(channel_key: str, topic_id: str, **fields) -> dict:
    data = load(channel_key)
    for topic in data["topics"]:
        if topic["id"] == topic_id:
            topic.update(fields)
            save(data)
            return topic
    raise CurriculumError(
        f"no topic {topic_id} in {channel_key}",
        user_message="That topic is no longer in the plan.",
    )


def claim(channel_key: str, topic_id: str = None) -> dict:
    """Take a topic for a video that is about to be made.

    Given an id, claims that one if it is still pending. If it is not —
    which happens when several videos were queued from the same page and
    each captured the same "next" topic — the next pending one is claimed
    instead, so a queue of five produces five different videos rather than
    the same one five times.
    """
    data = load(channel_key)
    chosen = None
    if topic_id:
        chosen = next((t for t in data["topics"]
                       if t["id"] == topic_id and t["status"] == PENDING), None)
    if chosen is None:
        chosen = next((t for t in data["topics"] if t["status"] == PENDING), None)
    if chosen is None:
        return None

    chosen["status"] = USED
    chosen["used_at"] = _now()
    save(data)
    return chosen


def attach_video(channel_key: str, topic_id: str, video_stem: str) -> None:
    """Record which video a claimed topic became."""
    _set(channel_key, topic_id, video_stem=video_stem)


def mark_published(channel_key: str, video_stem: str) -> None:
    data = load(channel_key)
    for topic in data["topics"]:
        if topic["video_stem"] == video_stem and topic["status"] == USED:
            topic["status"] = PUBLISHED
            save(data)
            return


def release(channel_key: str, video_stem: str) -> None:
    """Put a discarded video's topic back in the queue.

    A take that did not work is not a topic that has been covered. Without
    this, discarding leaves a permanent hole in the syllabus that nothing
    would ever surface.
    """
    data = load(channel_key)
    for topic in data["topics"]:
        if topic["video_stem"] == video_stem and topic["status"] in (USED, PUBLISHED):
            topic["status"] = PENDING
            topic["video_stem"] = ""
            topic["used_at"] = ""
            save(data)
            log.info(f"{channel_key}: returned topic {topic['id']} to the queue")
            return


def skip(channel_key: str, topic_id: str, note: str = "") -> dict:
    return _set(channel_key, topic_id, status=SKIPPED, note=note.strip()[:200])


def unskip(channel_key: str, topic_id: str) -> dict:
    topic = find(channel_key, topic_id)
    if topic and topic["status"] != SKIPPED:
        return topic
    return _set(channel_key, topic_id, status=PENDING, note="")


def move_to_front(channel_key: str, topic_id: str) -> dict:
    """Make one topic the next one made, without reordering the file.

    Position is what the syllabus means, so it is not rewritten. Instead
    the topic is given a position ahead of every other pending one and the
    list is re-sorted — the arc is preserved for everything else, and
    "make this one next" stays a one-click decision.
    """
    data = load(channel_key)
    pending = [t for t in data["topics"] if t["status"] == PENDING]
    if not pending:
        raise CurriculumError(f"nothing pending in {channel_key}",
                              user_message="There are no topics waiting.")
    lowest = min(t["position"] for t in pending)
    for topic in data["topics"]:
        if topic["id"] == topic_id:
            topic["position"] = lowest - 1
            topic["status"] = PENDING
            data["topics"].sort(key=lambda t: t["position"])
            save(data)
            return topic
    raise CurriculumError(f"no topic {topic_id} in {channel_key}",
                          user_message="That topic is no longer in the plan.")


def delete(channel_key: str) -> None:
    """Throw the syllabus away. The channel falls back to its topic list."""
    path = path_for(channel_key)
    path.unlink(missing_ok=True)
