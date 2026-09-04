"""
Generating a channel's syllabus: the outline, then one topic's subtopics.

Two calls with very different jobs.

`plan_outline` is asked for a *teaching order*, and that is the whole
point of it. Left alone, a model asked about mathematics produces a list
that is interesting and arbitrary — the Banach-Tarski paradox next to how
percentages work. The prompt below is mostly constraints on ordering,
because ordering is the thing that cannot be fixed later without
rewriting everything downstream of it.

`write_subtopics` is asked for one topic's worth, given the outline for
context and every title already in the syllabus so it cannot repeat one.
Repetition is the failure this exists to prevent, so it is constrained
twice: stated in the prompt, and enforced in
`core.curriculum.add_subtopics`, which drops duplicates whatever the
model says.

## Shape and cost

40 topics of 25 subtopics is 1000 videos — about eighteen months at two a
day. Measured on a real syllabus: an 8-topic outline cost $0.008 and a
call for a topic's subtopics about $0.010. A full 40-topic plan is 41
calls, lands comfortably under a dollar, is spread across the months it
takes to use, and is never made before the subtopics are needed.
"""

from __future__ import annotations

from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

# Enough for the reasoning and the answer. Thinking is billed from this,
# so a budget sized to the JSON alone would return nothing.
OUTLINE_MAX_TOKENS = 8000
SUBTOPICS_MAX_TOKENS = 8000

# Ordering is a judgement about an audience, which is what effort buys.
# Listing a topic's subtopics does not need it.
OUTLINE_EFFORT = "medium"
SUBTOPICS_EFFORT = "low"

DEFAULT_TOPIC_COUNT = 40
DEFAULT_TOTAL_SUBTOPICS = 1000

# Per call, not per topic: a topic wanting more simply takes two calls.
# Sized so the response comfortably fits the budget above — asking for 80
# in one go is how you get a truncated response and a topic that silently
# ends halfway.
MAX_SUBTOPICS_PER_CALL = 30


ORDERING_RULES = """\
The order is the point of this task. Judge it as if you were designing the
running order of a channel someone will watch from the beginning.

- Start with what the largest number of people can already follow. The
  first topic should contain the ideas someone with no background would
  recognise and want explained. Save what only an enthusiast would search
  for until late.
- Nothing may depend on an idea that has not appeared in an earlier topic.
  If topic 9 needs a term, topics 1-8 must have covered it.
- Move outward, not sideways. Each topic should feel like a step further
  in rather than a different corner of the same ground.
- Breadth first within a level. Cover the obvious things at one level of
  difficulty before going deeper on any one of them.
- The last topics should be genuinely specialist: the material an audience
  earns its way to, not filler.

A concrete test: someone who watches topic 1 and knows nothing about the
subject should understand every video in it. Someone who has watched
everything up to topic N should understand every video in topic N+1."""


def _outline_schema() -> dict:
    """No minItems/maxItems anywhere.

    The API rejects array bounds other than 0 and 1, and a schema it
    rejects is an HTTP 400 rather than a bad answer. Counts are stated in
    the prompt and checked afterwards.
    """
    return {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "One sentence naming what this channel covers.",
            },
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short name for this block of the syllabus.",
                        },
                        "summary": {
                            "type": "string",
                            "description": "One or two sentences: what this topic "
                                           "covers and what it assumes the viewer "
                                           "already knows.",
                        },
                        "level": {
                            "type": "string",
                            "enum": ["foundation", "intermediate", "advanced",
                                     "specialist"],
                        },
                        "target_subtopics": {
                            "type": "integer",
                            "description": "How many videos this topic should hold.",
                        },
                    },
                    "required": ["title", "summary", "level", "target_subtopics"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["subject", "topics"],
        "additionalProperties": False,
    }


def _subtopics_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "subtopics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "The subject of one video, specific "
                                           "enough that two subtopics in this "
                                           "topic could never produce the same "
                                           "script.",
                        },
                        "angle": {
                            "type": "string",
                            "description": "One sentence on what this particular "
                                           "video should do with it — the hook, "
                                           "the surprise, or the point.",
                        },
                    },
                    "required": ["title", "angle"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["subtopics"],
        "additionalProperties": False,
    }


def plan_outline(channel, topic_count: int = DEFAULT_TOPIC_COUNT,
                 total_subtopics: int = DEFAULT_TOTAL_SUBTOPICS,
                 subject_hint: str = "") -> dict:
    """The syllabus outline: ordered topics, no subtopics yet.

    `subject_hint` overrides what the channel's style prompt implies, for
    a channel whose prompt describes a format ("write dad jokes about…")
    rather than a subject.
    """
    system = [
        SystemBlock(
            "You design syllabuses for short-form video channels: the running "
            "order a channel should cover its subject in, from its first video "
            "to its thousandth.\n\n" + ORDERING_RULES,
            cacheable=True),
        SystemBlock(
            f"This channel's own description of what it makes:\n\n"
            f"{channel.style_prompt}"),
    ]

    subject_line = (f"The subject is: {subject_hint}\n\n" if subject_hint else "")
    per_topic = max(1, total_subtopics // max(1, topic_count))
    user = (
        f"{subject_line}"
        f"Design a syllabus of exactly {topic_count} topics covering roughly "
        f"{total_subtopics} short videos in total — about {per_topic} videos "
        f"per topic, with the targets summing to about {total_subtopics}.\n\n"
        f"Sizes need not be equal: an early topic covering the obvious ground "
        f"can be larger, a late specialist one smaller.\n\n"
        f"Order them so the level rises steadily from foundation to "
        f"specialist, and put the levels in that order."
    )

    data = call_json(system, user, _outline_schema(),
                     operation="curriculum_outline",
                     max_tokens=OUTLINE_MAX_TOKENS, effort=OUTLINE_EFFORT)

    topics = data.get("topics") or []
    if not topics:
        from core.errors import PipelineError
        raise PipelineError(
            "The outline came back with no topics.",
            user_message="Couldn't design a topic plan for this channel. Its "
                         "style prompt may be too vague to plan a syllabus from "
                         "— try again with a subject.",
        )
    if len(topics) != topic_count:
        # Not fatal. The ordering is what matters and a syllabus of 37
        # topics is as usable as one of 40; failing here would throw away
        # a good answer over a number nobody will notice.
        log.warning(f"Asked for {topic_count} topics, got {len(topics)}")
    return data


def write_subtopics(channel, curriculum: dict, topic: dict,
                    count: int = None) -> list:
    """One topic's subtopics, in the order they should be made.

    The outline goes in every call so a topic knows what came before it
    and what comes after — without that, topic 12 restates topic 4 in
    different words, which is the same failure as repeating a subtopic but
    harder to notice.
    """
    count = min(count or topic.get("target_subtopics", 25), MAX_SUBTOPICS_PER_CALL)

    outline = "\n".join(
        f"{i + 1}. [{row['level']}] {row['title']} — {row.get('summary', '')}"
        for i, row in enumerate(curriculum["topics"]))

    # Titles only, and only from earlier topics plus this one. The whole
    # syllabus would grow this prompt without bound as the channel runs,
    # and a topic cannot repeat something that has not been written yet.
    position = next((i for i, row in enumerate(curriculum["topics"])
                     if row["id"] == topic["id"]), 0)
    earlier_ids = {row["id"] for row in curriculum["topics"][:position + 1]}
    existing = [row["title"] for row in curriculum["subtopics"]
                if row["topic"] in earlier_ids]

    system = [
        SystemBlock(
            "You write the video list for one topic of a short-form video "
            "channel's syllabus. Each subtopic is one video.\n\n"
            "A subtopic must be narrow enough that it could not be confused "
            "with any other in the list — 'how interest works' and 'compound "
            "interest' are two videos; 'money' is not a subtopic at all. Stay "
            "inside the topic you are given: material belonging to a later "
            "topic must be left for it.",
            cacheable=True),
        SystemBlock(f"This channel's own description of what it makes:\n\n"
                    f"{channel.style_prompt}", cacheable=True),
        SystemBlock(f"The full syllabus, in order:\n\n{outline}"),
    ]

    already = ""
    if existing:
        listed = "\n".join(f"- {title}" for title in existing[-300:])
        already = (f"\n\nThese are already in the syllabus. Do not repeat any of "
                   f"them, and do not write a near-duplicate under a different "
                   f"name:\n{listed}")

    user = (
        f"Write {count} subtopics for topic {position + 1}, "
        f"\"{topic['title']}\" ({topic['level']}).\n\n"
        f"What this topic covers: {topic.get('summary', '')}\n\n"
        f"Order them so the easier ones come first within the topic."
        f"{already}"
    )

    data = call_json(system, user, _subtopics_schema(),
                     operation="curriculum_subtopics",
                     max_tokens=SUBTOPICS_MAX_TOKENS, effort=SUBTOPICS_EFFORT)

    written = data.get("subtopics") or []
    if len(written) < count:
        log.info(f"Topic {topic['id']}: asked for {count} subtopics, "
                 f"got {len(written)}")
    return written


def estimate_cost(topic_count: int = DEFAULT_TOPIC_COUNT) -> dict:
    """Roughly what a full syllabus costs, for the confirmation prompt.

    Deliberately an over-estimate. Someone deciding whether to spend money
    is better served by a figure that turns out generous than one that
    turns out short.
    """
    # Grounded in a real run: an 8-topic outline came in at 1016 in / 630
    # out ($0.0083), and a 15-subtopic call at ~1.1k in / 730 out
    # ($0.0095). Scaled up and then rounded up again, which is why a full
    # plan quotes near a dollar and has cost about half that.
    outline = (1_500 * 3 / 1e6) + (3_000 * 15 / 1e6)
    per_topic = (2_000 * 3 / 1e6) + (2_500 * 15 / 1e6)
    return {
        "outline_usd": outline,
        "per_topic_usd": per_topic,
        "full_usd": outline + per_topic * topic_count,
        "topic_count": topic_count,
    }
