"""
An ordered syllabus for a channel: topics, each holding subtopics.

## The two levels

A **topic** is a block of the syllabus — "Basic Tools of the Craft" — with
a level, a summary and a target size. A **subtopic** is one video.

That is the vocabulary because it is the one people use about their own
channels. The code called them units and topics for a while, which meant
the UI and the code disagreed about what "topic" meant; version 2 of the
file format is that rename, migrated on read.

## Why the syllabus is generated in two layers

The obvious answer is "generate a thousand subtopics up front". That is
right about ordering and wrong about generation, for two reasons.

A thousand usable subtopics is 40-60k output tokens. That is not one
response; batching is unavoidable whatever the design says. And a list
written on day one is written with no information — by video 200 you know
which subtopics got discarded and why, and the remaining 800 were fixed
before any of that existed.

But ordering genuinely does have to be global. Deciding "what next" one
video at a time cannot produce accessible-before-specialist, because each
local decision has no view of the arc.

So the outline — 40 ordered topics — is one cheap call, and subtopics are
written a topic at a time as they are needed. 40 topics of 25 subtopics is
1000 videos, about eighteen months at two a day.

## Statuses

`pending` → `used` when a video is generated from it → `published` when
that video is published. `skipped` is a deliberate "not this one".

A discarded video **returns its subtopic to pending**. A take that did not
work is not a subtopic that has been covered, and losing it would silently
put a hole in the syllabus.

## Storage

One file per channel, `config/curricula/<key>.json`, an ordered list
rather than a database: it is read whole, written whole, a thousand
entries is well under a megabyte, and being able to open it in an editor
and fix a line by hand is worth more here than query speed.
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

# 1: {"units": [...], "topics": [...]}
# 2: {"topics": [...], "subtopics": [...]} — the same shape under the
#    names people actually use. Migrated in memory on read and persisted
#    on the next write, so nobody has to run anything.
SCHEMA_VERSION = 2

PENDING, USED, PUBLISHED, SKIPPED = "pending", "used", "published", "skipped"
STATUSES = (PENDING, USED, PUBLISHED, SKIPPED)

# Levels, easiest first. Ordering topics by this is a check on the model's
# own ordering rather than a replacement for it — the prompt asks for a
# sensible progression, and this catches an outline that ignored it.
LEVELS = ("foundation", "intermediate", "advanced", "specialist")

# How few pending subtopics is too few. At two videos a day this is about
# two weeks of runway: enough warning to generate more without ever being
# the thing that blocks a video.
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


def blank(channel_key: str) -> dict:
    return {"version": SCHEMA_VERSION, "channel": channel_key, "subject": "",
            "generated_at": "", "topics": [], "subtopics": []}


def _migrate(data: dict) -> dict:
    """Version 1 called topics "units" and subtopics "topics".

    Renamed in memory on read; the next write persists it. No flag day, no
    manual step — the same approach channels.json takes.
    """
    if "units" not in data:
        return data
    # Both old lists are read out BEFORE either new one is written: in
    # version 1 "topics" meant subtopics, so assigning the new "topics"
    # first would overwrite the very list the subtopics come from.
    old_units = data.pop("units", [])
    old_topics = data.pop("topics", [])

    data["topics"] = [
        {"id": unit["id"], "title": unit["title"], "summary": unit.get("summary", ""),
         "level": unit.get("level", "intermediate"),
         "target_subtopics": int(unit.get("target_topics", 25)),
         "filled": bool(unit.get("filled"))}
        for unit in old_units
    ]
    data["subtopics"] = [
        {**{k: v for k, v in row.items() if k != "unit"}, "topic": row.get("unit", "")}
        for row in old_topics
    ]
    data["version"] = SCHEMA_VERSION
    return data


def load(channel_key: str) -> dict:
    """The whole syllabus, or an empty one if there is no file.

    Returns the empty shape rather than raising, so every caller can ask
    "does this channel have a syllabus" by looking at `topics`.
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
    data = _migrate(data)
    data.setdefault("topics", [])
    data.setdefault("subtopics", [])
    return data


def save(data: dict) -> None:
    """Write the whole file.

    Via a temporary file and a replace: a syllabus is the record of what a
    channel has already covered, and a half-written one after a crash
    would mean regenerating subtopics that have been published.
    """
    data["version"] = SCHEMA_VERSION
    path = path_for(data["channel"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- building -------------------------------------------------------

def start(channel_key: str, subject: str, topics: list) -> dict:
    """Create a syllabus from a generated outline. No subtopics yet."""
    data = blank(channel_key)
    data["subject"] = subject
    data["generated_at"] = _now()
    data["topics"] = [
        {"id": f"u{i + 1:02d}",
         "title": topic["title"],
         "summary": topic.get("summary", ""),
         "level": topic.get("level") if topic.get("level") in LEVELS else "intermediate",
         "target_subtopics": int(topic.get("target_subtopics")
                                 or topic.get("target_topics") or 25),
         "filled": False}
        for i, topic in enumerate(topics)
    ]
    save(data)
    return data


def add_subtopics(channel_key: str, topic_id: str, subtopics: list) -> dict:
    """Append one topic's subtopics, in the order given.

    Titles already anywhere in the syllabus are dropped rather than
    appended. The generator is told what exists and asked not to repeat,
    but "asked not to" is not a guarantee, and a duplicate is the exact
    failure this whole system is here to prevent.
    """
    data = load(channel_key)
    topic = _topic(data, topic_id)

    seen = {t["title"].strip().lower() for t in data["subtopics"]}
    position = len(data["subtopics"])
    added = 0
    for row in subtopics:
        title = (row.get("title") or "").strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        position += 1
        data["subtopics"].append({
            "id": f"t{position:04d}",
            "topic": topic_id,
            "position": position,
            "title": title,
            "angle": (row.get("angle") or "").strip(),
            "status": PENDING,
            "video_stem": "",
            "used_at": "",
            "note": "",
            "script": None,
            "script_written_at": "",
        })
        added += 1

    topic["filled"] = True
    save(data)
    if added < len(subtopics):
        log.info(f"{channel_key}: dropped {len(subtopics) - added} duplicate "
                 f"subtopic(s) for topic {topic_id}")
    return data


def _topic(data: dict, topic_id: str) -> dict:
    for topic in data["topics"]:
        if topic["id"] == topic_id:
            return topic
    raise CurriculumError(
        f"no topic {topic_id} in {data['channel']}",
        user_message="That part of the topic plan no longer exists.",
    )


def find_topic(channel_key: str, topic_id: str) -> dict:
    for topic in load(channel_key)["topics"]:
        if topic["id"] == topic_id:
            return topic
    return None


def next_unfilled_topic(channel_key: str) -> dict:
    """The earliest topic with no subtopics yet, or None.

    Earliest, not any: topics fill in order so the buffer of pending
    subtopics always continues the arc rather than jumping ahead of it.
    """
    for topic in load(channel_key)["topics"]:
        if not topic.get("filled"):
            return topic
    return None


# --- reading --------------------------------------------------------

def subtopics(channel_key: str, status: str = None, topic_id: str = None) -> list:
    rows = load(channel_key)["subtopics"]
    if status:
        rows = [t for t in rows if t["status"] == status]
    if topic_id:
        rows = [t for t in rows if t["topic"] == topic_id]
    return rows


def find(channel_key: str, subtopic_id: str) -> dict:
    for row in load(channel_key)["subtopics"]:
        if row["id"] == subtopic_id:
            return row
    return None


def next_pending(channel_key: str, topic_id: str = None) -> dict:
    """The next subtopic to make a video from, in syllabus order.

    `topic_id` narrows it to one topic, for "give me the next one from
    this block" rather than the next one overall.
    """
    for row in load(channel_key)["subtopics"]:
        if row["status"] != PENDING:
            continue
        if topic_id and row["topic"] != topic_id:
            continue
        return row
    return None


def pending_count(channel_key: str) -> int:
    return sum(1 for t in load(channel_key)["subtopics"] if t["status"] == PENDING)


def progress(channel_key: str) -> dict:
    """Counts, and how long the remaining subtopics last.

    `runway_days` assumes two videos a day because that is the cadence
    this was sized for; it is a rough "when do I need to think about
    this", not a schedule.
    """
    data = load(channel_key)
    rows = data["subtopics"]
    counts = {status: sum(1 for t in rows if t["status"] == status) for status in STATUSES}
    done = counts[USED] + counts[PUBLISHED]
    return {
        "has_curriculum": bool(data["topics"]),
        "subject": data.get("subject", ""),
        "topic_count": len(data["topics"]),
        "topics_filled": sum(1 for t in data["topics"] if t.get("filled")),
        "total": len(rows),
        "planned_total": sum(t.get("target_subtopics", 0) for t in data["topics"]),
        **counts,
        "done": done,
        "percent_done": (done / len(rows) * 100) if rows else 0.0,
        "runway_days": counts[PENDING] // 2,
        "running_low": counts[PENDING] < LOW_WATER_MARK,
    }


def topics_with_subtopics(channel_key: str) -> list:
    """The outline with its subtopics attached, for the plan page."""
    data = load(channel_key)
    by_topic = {}
    for row in data["subtopics"]:
        by_topic.setdefault(row["topic"], []).append(row)

    rows = []
    for topic in data["topics"]:
        mine = by_topic.get(topic["id"], [])
        rows.append({
            **topic,
            "subtopics": mine,
            "pending": sum(1 for t in mine if t["status"] == PENDING),
            "done": sum(1 for t in mine if t["status"] in (USED, PUBLISHED)),
            "skipped": sum(1 for t in mine if t["status"] == SKIPPED),
        })
    return rows


# How many subtopic "chips" a table row shows at most — enough to read
# as a progress strip, not so many that a 40-subtopic topic renders 40
# little squares. The row's own pending/done/published/total counts
# carry the real numbers regardless of how many chips are drawn.
MAX_ROW_SAMPLE = 6


def table_rows(channel, current_subtopic: dict = None, max_topics: int = 8) -> dict:
    """A curated window of topics for the Create Video table.

    Never every topic — a 40-topic plan would be as overwhelming on
    screen as it already is to choose from with dropdowns. Always
    includes the topic holding `current_subtopic` (the ordering policy's
    live pick — the full subtopic dict from `core.ordering.
    choose_next_subtopic`, not just its topic, since the pick is marked
    at the subtopic level too), then the topics with the most recent
    activity ("where you've been"), then — only when `channel.ordering.
    topic_order` is "sequential" — a couple of topics after the current
    one in file order ("where you're headed"); skipped entirely for
    random topic order, since a channel that could jump anywhere next
    shouldn't render a run of untouched topics as if they were queued up.

    Returns `{"rows": [...], "hidden_topics": int}` — the omitted count,
    never a silent drop, so the page can offer "+N more — open the full
    plan" rather than pretending the rest doesn't exist.
    """
    current_topic_id = current_subtopic["topic"] if current_subtopic else None
    current_subtopic_id = current_subtopic["id"] if current_subtopic else None

    data = load(channel.key)
    topics = data["topics"]
    by_topic = {}
    for row in data["subtopics"]:
        by_topic.setdefault(row["topic"], []).append(row)

    def last_activity(topic_id: str) -> str:
        made = [r["used_at"] for r in by_topic.get(topic_id, [])
               if r["status"] in (USED, PUBLISHED) and r.get("used_at")]
        return max(made) if made else ""

    by_id = {t["id"]: t for t in topics}
    order = [t["id"] for t in topics]

    selected_ids = []
    if current_topic_id and current_topic_id in by_id:
        selected_ids.append(current_topic_id)

    by_recency = sorted((t["id"] for t in topics if t["id"] not in selected_ids),
                        key=last_activity, reverse=True)
    for topic_id in by_recency:
        if len(selected_ids) >= max_topics or not last_activity(topic_id):
            break
        selected_ids.append(topic_id)

    if channel.ordering.topic_order == "sequential" and current_topic_id in order:
        start = order.index(current_topic_id)
        for topic_id in order[start + 1:]:
            if len(selected_ids) >= max_topics:
                break
            if topic_id not in selected_ids:
                selected_ids.append(topic_id)

    # Still room and nothing left to add on purpose — fall back to
    # whatever's next in file order so a fresh plan with no history yet
    # still shows more than just its first topic. Not for random topic
    # order: padding with untouched topics would imply they're "coming
    # up next" for a channel that could jump anywhere, which is exactly
    # what this windowing exists to avoid.
    if channel.ordering.topic_order != "random":
        for topic_id in order:
            if len(selected_ids) >= max_topics:
                break
            if topic_id not in selected_ids:
                selected_ids.append(topic_id)

    rows = []
    for topic_id in selected_ids:
        topic = by_id[topic_id]
        mine = by_topic.get(topic_id, [])
        pending = [r for r in mine if r["status"] == PENDING]
        done = [r for r in mine if r["status"] in (USED, PUBLISHED)]
        sample = (done[-MAX_ROW_SAMPLE:] if len(done) <= MAX_ROW_SAMPLE
                 else done[-(MAX_ROW_SAMPLE - 2):]) + pending[:2]
        sample = sample[:MAX_ROW_SAMPLE]

        # The exact subtopic the policy would make next, when it's this
        # row — not just "some pending one in this topic". Guaranteed a
        # spot in the sample even if it wouldn't otherwise make the cut
        # (e.g. random subtopic order landed past the first couple).
        if topic_id == current_topic_id and current_subtopic_id:
            if not any(r["id"] == current_subtopic_id for r in sample):
                sample = sample[:-1] + [next(r for r in mine if r["id"] == current_subtopic_id)]

        rows.append({
            "topic_id": topic_id,
            "title": topic["title"],
            "level": topic["level"],
            "is_current": topic_id == current_topic_id,
            "pending": len(pending),
            "done": sum(1 for r in mine if r["status"] == USED),
            "published": sum(1 for r in mine if r["status"] == PUBLISHED),
            "total": len(mine),
            "subtopics": [{"id": r["id"], "title": r["title"], "status": r["status"],
                          "is_next": r["id"] == current_subtopic_id}
                         for r in sample],
        })

    return {"rows": rows, "hidden_topics": max(0, len(topics) - len(selected_ids))}


def covered_in_topic(channel_key: str, topic_id: str) -> list:
    """Subtopics of this topic that already became videos, in order.

    For channels whose videos build on each other: a script for subtopic 7
    can be told what 1-6 already said, so it stops re-explaining the same
    groundwork.
    """
    return [row for row in subtopics(channel_key, topic_id=topic_id)
            if row["status"] in (USED, PUBLISHED)]


def covered_titles(channel_key: str, topic_id: str, scope: str,
                   recent_topics: int = 3) -> list:
    """Earlier videos a script for this topic should already assume the
    viewer has seen, per `scope` (`core.channels.ChannelConfig.
    context_scope`):

    "topic" — this topic's own earlier videos only (`covered_in_topic`,
      unchanged — the original, still-default behaviour).
    "recent_topics" — this topic plus the `recent_topics` immediately
      before it. Topics fill in teaching order, so "before" is a real
      position in the syllabus, not an arbitrary cut.
    "all" — every topic up to and including this one.

    Rows, oldest first — the same shape `covered_in_topic` already
    returns, so callers that do `row["title"] for row in ...` need no
    change. An unrecognised scope, or a topic_id no longer in the
    syllabus, falls back to the "topic" behaviour rather than raising —
    context is a bonus, never a blocker.
    """
    if scope not in ("recent_topics", "all"):
        return covered_in_topic(channel_key, topic_id)

    data = load(channel_key)
    topic_ids = [t["id"] for t in data["topics"]]
    if topic_id not in topic_ids:
        return covered_in_topic(channel_key, topic_id)
    position = topic_ids.index(topic_id)

    if scope == "all":
        window = set(topic_ids[:position + 1])
    else:
        start = max(0, position - max(0, recent_topics))
        window = set(topic_ids[start:position + 1])

    return [row for row in data["subtopics"]
           if row["topic"] in window and row["status"] in (USED, PUBLISHED)]


# --- status transitions ---------------------------------------------

def _set(channel_key: str, subtopic_id: str, **fields) -> dict:
    data = load(channel_key)
    for row in data["subtopics"]:
        if row["id"] == subtopic_id:
            row.update(fields)
            save(data)
            return row
    raise CurriculumError(
        f"no subtopic {subtopic_id} in {channel_key}",
        user_message="That subtopic is no longer in the plan.",
    )


def claim(channel_key: str, subtopic_id: str = None) -> dict:
    """Take a subtopic for a video that is about to be made.

    Given an id, claims that one if it is still pending. If it is not —
    which happens when several videos were queued from the same page and
    each captured the same "next" one — the next pending one is claimed
    instead, so a queue of five produces five different videos rather than
    the same one five times.
    """
    data = load(channel_key)
    chosen = None
    if subtopic_id:
        chosen = next((t for t in data["subtopics"]
                       if t["id"] == subtopic_id and t["status"] == PENDING), None)
    if chosen is None:
        chosen = next((t for t in data["subtopics"] if t["status"] == PENDING), None)
    if chosen is None:
        return None

    chosen["status"] = USED
    chosen["used_at"] = _now()
    save(data)
    return chosen


def attach_video(channel_key: str, subtopic_id: str, video_stem: str) -> None:
    """Record which video a claimed subtopic became."""
    _set(channel_key, subtopic_id, video_stem=video_stem)


def set_script(channel_key: str, subtopic_id: str, script: dict) -> None:
    """Write, or overwrite, one subtopic's script.

    The one function behind three different actions: the batch writer's
    first pass, a blind or prompted regenerate, and a manual edit all
    just produce a script dict and hand it here. Deliberately independent
    of `status` — a script can be written, read, and rewritten on a
    subtopic that has never been rendered and on one that already has a
    published video, since editing the writing and deciding what to do
    with an existing video are two different actions (see `release`).
    """
    _set(channel_key, subtopic_id, script=script, script_written_at=_now())


def mark_published(channel_key: str, video_stem: str) -> None:
    data = load(channel_key)
    for row in data["subtopics"]:
        if row["video_stem"] == video_stem and row["status"] == USED:
            row["status"] = PUBLISHED
            save(data)
            return


def release(channel_key: str, video_stem: str) -> None:
    """Put a discarded video's subtopic back in the queue.

    A take that did not work is not a subtopic that has been covered.
    Without this, discarding leaves a permanent hole in the syllabus that
    nothing would ever surface.
    """
    data = load(channel_key)
    for row in data["subtopics"]:
        if row["video_stem"] == video_stem and row["status"] in (USED, PUBLISHED):
            row["status"] = PENDING
            row["video_stem"] = ""
            row["used_at"] = ""
            save(data)
            log.info(f"{channel_key}: returned subtopic {row['id']} to the queue")
            return


def release_unattached(channel_key: str, subtopic_id: str) -> None:
    """Put back a claim that never became a video.

    `claim()` marks a subtopic used the moment generation starts, before
    anything has actually been produced — deliberately, so two videos
    queued back to back claim different subtopics rather than racing for
    the same one. If generation then fails (a script call errors, a TTS
    quota runs out, anything before `attach_video` runs), that claim was
    never converted into a real video and would otherwise sit "used"
    forever with nothing to discard and no way back to pending. Guarded
    on an empty `video_stem` so this never undoes a claim that already
    became a real file — that case is a discard decision, made through
    `release()` instead.
    """
    data = load(channel_key)
    for row in data["subtopics"]:
        if row["id"] == subtopic_id and row["status"] == USED and not row.get("video_stem"):
            row["status"] = PENDING
            row["used_at"] = ""
            save(data)
            log.info(f"{channel_key}: released subtopic {subtopic_id} after a failed generation")
            return


def skip(channel_key: str, subtopic_id: str, note: str = "") -> dict:
    return _set(channel_key, subtopic_id, status=SKIPPED, note=note.strip()[:200])


def unskip(channel_key: str, subtopic_id: str) -> dict:
    row = find(channel_key, subtopic_id)
    if row and row["status"] != SKIPPED:
        return row
    return _set(channel_key, subtopic_id, status=PENDING, note="")


def move_to_front(channel_key: str, subtopic_id: str) -> dict:
    """Make one subtopic the next one made, without reordering the file.

    Position is what the syllabus means, so it is not rewritten. Instead
    the subtopic is given a position ahead of every other pending one and
    the list is re-sorted — the arc is preserved for everything else, and
    "make this one next" stays a one-click decision.
    """
    data = load(channel_key)
    pending = [t for t in data["subtopics"] if t["status"] == PENDING]
    if not pending:
        raise CurriculumError(f"nothing pending in {channel_key}",
                              user_message="There are no subtopics waiting.")
    lowest = min(t["position"] for t in pending)
    for row in data["subtopics"]:
        if row["id"] == subtopic_id:
            row["position"] = lowest - 1
            row["status"] = PENDING
            data["subtopics"].sort(key=lambda t: t["position"])
            save(data)
            return row
    raise CurriculumError(f"no subtopic {subtopic_id} in {channel_key}",
                          user_message="That subtopic is no longer in the plan.")


def delete(channel_key: str) -> None:
    """Throw the syllabus away. The channel falls back to its topic list."""
    path_for(channel_key).unlink(missing_ok=True)
