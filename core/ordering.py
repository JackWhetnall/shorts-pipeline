"""
Which subtopic "make the next video" picks, for a channel with a topic
plan.

`core.curriculum` stores the syllabus — topics, subtopics, status. This
module is the one policy question sitting on top of it: given everything
at hand, which pending subtopic is next. It used to be a single hardcoded
answer (`curriculum.next_pending`, file order, no exceptions); it is now
a channel setting (`core.channels.Ordering`), because "finish this topic
before starting the next" and "cycle through every topic a subtopic at a
time" and "grow organically, mostly staying on one thread" are all
legitimate production styles and none of them is universally right.

Three independent knobs — topic order, subtopic order, grouping — cover
every combination of "sequential vs random" at either level and "finish
a topic vs interleave them". "natural" is qualitatively different: a
weighted continuation rather than a fixed sequence, so it is its own
mode rather than a fourth knob bolted onto the other three. See
docs/decisions/024-ordering-and-title-cards.md.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

from core import curriculum


def choose_next_subtopic(channel, curriculum_data: dict = None, rng=None) -> dict:
    """The subtopic to offer next, per `channel.ordering`. None if
    nothing is pending.

    `curriculum_data` lets a caller that already loaded the syllabus for
    this request avoid loading it twice. `rng` is for deterministic
    tests — anything with `.choice`/`.choices`/`.random`, defaulting to
    the `random` module itself.
    """
    rng = rng or random
    data = curriculum_data if curriculum_data is not None else curriculum.load(channel.key)
    topics = data["topics"]
    subtopics = data["subtopics"]
    ordering = channel.ordering

    by_topic = {}
    for row in subtopics:
        by_topic.setdefault(row["topic"], []).append(row)

    pending_topics = [t for t in topics if _pending(by_topic, t["id"])]
    if not pending_topics:
        return None

    if ordering.mode == "natural":
        topic = _natural_choice(topics, by_topic, ordering, rng)
    else:
        topic = _structured_choice(topics, pending_topics, by_topic, ordering, rng)

    pending = _pending(by_topic, topic["id"])
    if ordering.mode != "natural" and ordering.subtopic_order == "random":
        return rng.choice(pending)
    return pending[0]  # already in file/position order


def _pending(by_topic: dict, topic_id: str) -> list:
    return [r for r in by_topic.get(topic_id, []) if r["status"] == curriculum.PENDING]


def _last_made_topic_id(by_topic: dict) -> str:
    """The topic of the most recently made video, or None if nothing has
    been made yet. `used_at` is an ISO timestamp, so lexical max is
    chronological max."""
    made = [row for rows in by_topic.values() for row in rows
           if row["status"] in (curriculum.USED, curriculum.PUBLISHED) and row.get("used_at")]
    if not made:
        return None
    return max(made, key=lambda row: row["used_at"])["topic"]


def _structured_choice(topics: list, pending_topics: list, by_topic: dict,
                       ordering, rng) -> dict:
    last_topic_id = _last_made_topic_id(by_topic)

    if ordering.grouping == "topic_first" and last_topic_id:
        current = next((t for t in pending_topics if t["id"] == last_topic_id), None)
        if current:
            return current
        # The topic that was in progress just ran out — advance, same as
        # round_robin does on every call.

    return _advance_topic(topics, pending_topics, last_topic_id, ordering, rng)


def _advance_topic(topics: list, pending_topics: list, last_topic_id: str,
                   ordering, rng) -> dict:
    """The topic after `last_topic_id`, per `topic_order`. Used by
    topic_first once its current topic is exhausted, and always by
    round_robin — the two grouping modes differ only in *whether* they
    stay put, never in how they move on."""
    if ordering.topic_order == "random":
        candidates = ([t for t in pending_topics if t["id"] != last_topic_id]
                      or pending_topics)
        return rng.choice(candidates)

    # sequential: cycle forward from wherever we were, wrapping around —
    # not always collapsing back to the first topic in the file, which
    # would make round_robin indistinguishable from topic_first once the
    # first topic is exhausted.
    if last_topic_id:
        ids_in_order = [t["id"] for t in topics]
        if last_topic_id in ids_in_order:
            start = ids_in_order.index(last_topic_id)
            for topic_id in ids_in_order[start + 1:] + ids_in_order[:start + 1]:
                match = next((t for t in pending_topics if t["id"] == topic_id), None)
                if match:
                    return match
    return pending_topics[0]


def _natural_choice(topics: list, by_topic: dict, ordering, rng) -> dict:
    """With probability `stickiness`, continue the topic in progress.
    Otherwise branch to a topic weighted toward the least attention so
    far — every topic keeps getting pulled toward eventually, rather
    than the loudest one winning forever."""
    last_topic_id = _last_made_topic_id(by_topic)
    current = next((t for t in topics
                    if t["id"] == last_topic_id and _pending(by_topic, t["id"])), None)
    if current and rng.random() < ordering.stickiness:
        return current

    candidates = [t for t in topics if _pending(by_topic, t["id"])]
    weights = [1.0 / (1 + _made_count(by_topic, t["id"])) for t in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def _made_count(by_topic: dict, topic_id: str) -> int:
    return sum(1 for r in by_topic.get(topic_id, [])
              if r["status"] in (curriculum.USED, curriculum.PUBLISHED))


def simulate(settings: dict, topic_count: int = 6, subtopics_per_topic: int = 5,
            steps: int = 24, rng=None) -> dict:
    """A run of `choose_next_subtopic` against synthetic dummy data, for
    the Ordering settings page's "preview this ordering" animation.

    Deliberately calls the real function above rather than a second
    implementation of the same rules — a preview that could show
    behaviour the channel wouldn't actually produce would be worse than
    no preview at all. `settings` mirrors `core.channels.Ordering`'s own
    fields, taken as a plain dict (not a saved channel) since the whole
    point is trying a setting before committing to it.

    Returns `{"rows": [...], "steps": [...]}`. `rows` is the all-pending
    starting table, in exactly the shape `core.curriculum.table_rows`
    produces, so the page's one table renderer draws both the real Create
    Video table and this animation without knowing which is which.
    `steps` is up to `steps` `{"topic_id", "subtopic_id"}` picks in the
    order they'd happen — fewer if the dummy plan runs out first — for
    the caller to reveal one at a time against those same rows.
    """
    rng = rng or random
    channel = SimpleNamespace(key="__ordering_preview__", ordering=SimpleNamespace(**settings))

    topics = [{"id": f"t{i + 1}", "title": f"Topic {i + 1}", "summary": "",
              "level": "foundation", "target_subtopics": subtopics_per_topic, "filled": True}
             for i in range(topic_count)]
    subtopics = []
    position = 0
    for topic in topics:
        for j in range(subtopics_per_topic):
            position += 1
            subtopics.append({
                "id": f"s{position}", "topic": topic["id"], "position": position,
                "title": f"{topic['title']} #{j + 1}", "angle": "",
                "status": curriculum.PENDING, "video_stem": "", "used_at": "",
                "note": "", "script": None, "script_written_at": "",
            })
    data = {"topics": topics, "subtopics": subtopics}
    by_topic = {t["id"]: [s for s in subtopics if s["topic"] == t["id"]] for t in topics}

    rows = [{
        "topic_id": t["id"], "title": t["title"], "level": t["level"], "is_current": False,
        "pending": subtopics_per_topic, "done": 0, "published": 0, "total": subtopics_per_topic,
        "subtopics": [{"id": s["id"], "title": s["title"], "status": curriculum.PENDING,
                      "is_next": False} for s in by_topic[t["id"]]],
    } for t in topics]

    results = []
    for step in range(steps):
        pick = choose_next_subtopic(channel, data, rng=rng)
        if pick is None:
            break
        # Mutated in place: `pick` is the same dict object sitting inside
        # `data["subtopics"]` (choose_next_subtopic never copies), so this
        # is exactly what a real claim does to the real syllabus.
        pick["status"] = curriculum.USED
        pick["used_at"] = f"{step:06d}"
        results.append({"topic_id": pick["topic"], "subtopic_id": pick["id"]})
    return {"rows": rows, "steps": results}
