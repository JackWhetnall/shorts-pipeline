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
