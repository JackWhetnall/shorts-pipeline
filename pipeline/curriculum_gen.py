"""
Generating a channel's syllabus: the outline, then a unit's topics.

Two calls with very different jobs.

`plan_outline` is asked for a *teaching order*, and that is the whole
point of it. Left alone, a model asked for topics about mathematics
produces a list that is interesting and arbitrary — the Banach-Tarski
paradox next to how percentages work. The prompt below is mostly
constraints on ordering, because ordering is the thing that cannot be
fixed later without rewriting everything downstream of it.

`write_unit_topics` is asked for a specific unit's worth, given the
outline for context and every title already in the syllabus so it cannot
repeat one. Repetition is the failure this exists to prevent, so it is
constrained twice: stated in the prompt, and enforced in
`core.curriculum.add_topics`, which drops duplicates whatever the model
says.

## Cost

Measured on a real 8-unit maths syllabus: the outline cost $0.008 and a
unit of topics about $0.010. A full 25-unit, 1000-topic plan is 26 calls
and lands comfortably under a dollar — spread over the eighteen months it
takes to use, and never made before the topics are needed.
"""

from __future__ import annotations

from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

# Enough for the outline's reasoning and its answer. Thinking is billed
# from this, so a budget sized to the JSON alone would return nothing.
OUTLINE_MAX_TOKENS = 8000
TOPICS_MAX_TOKENS = 8000

# Ordering is a judgement about an audience, which is what effort buys.
# The topics themselves are a listing task and do not need it.
OUTLINE_EFFORT = "medium"
TOPICS_EFFORT = "low"

DEFAULT_UNIT_COUNT = 25
DEFAULT_TOTAL_TOPICS = 1000

# Per call, not per unit: a unit's target can exceed this and simply takes
# two calls. Sized so the response comfortably fits the budget above —
# asking for 80 in one go is how you get a truncated response and a unit
# that silently ends halfway.
MAX_TOPICS_PER_CALL = 40


ORDERING_RULES = """\
The order is the point of this task. Judge it as if you were designing the
running order of a channel someone will watch from the beginning.

- Start with what the largest number of people can already follow. The
  first unit should contain the ideas someone with no background would
  recognise and want explained. Save what only an enthusiast would search
  for until late.
- Nothing may depend on an idea that has not appeared in an earlier unit.
  If unit 9 needs a term, unit 1-8 must have covered it.
- Move outward, not sideways. Each unit should feel like a step further
  in rather than a different corner of the same ground.
- Breadth first within a level. Cover the obvious things at one level of
  difficulty before going deeper on any one of them.
- The last units should be genuinely specialist: the material an audience
  earns its way to, not filler.

A concrete test: someone who watches unit 1 and knows nothing about the
subject should understand every video in it. Someone who has watched
everything up to unit N should understand every video in unit N+1."""


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
            "units": {
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
                            "description": "One or two sentences: what this unit "
                                           "covers and what it assumes the viewer "
                                           "already knows.",
                        },
                        "level": {
                            "type": "string",
                            "enum": ["foundation", "intermediate", "advanced",
                                     "specialist"],
                        },
                        "target_topics": {
                            "type": "integer",
                            "description": "How many videos this unit should hold.",
                        },
                    },
                    "required": ["title", "summary", "level", "target_topics"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["subject", "units"],
        "additionalProperties": False,
    }


def _topics_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "The subject of one video, specific "
                                           "enough that two topics in this unit "
                                           "could never produce the same script.",
                        },
                        "angle": {
                            "type": "string",
                            "description": "One sentence on what this particular "
                                           "video should do with the topic — the "
                                           "hook, the surprise, or the point.",
                        },
                    },
                    "required": ["title", "angle"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["topics"],
        "additionalProperties": False,
    }


def plan_outline(channel, unit_count: int = DEFAULT_UNIT_COUNT,
                 total_topics: int = DEFAULT_TOTAL_TOPICS,
                 subject_hint: str = "") -> dict:
    """The syllabus outline: ordered units, no topics yet.

    `subject_hint` overrides what the channel's style prompt implies,
    for a channel whose prompt describes a format ("write dad jokes
    about…") rather than a subject.
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
    user = (
        f"{subject_line}"
        f"Design a syllabus of exactly {unit_count} units covering roughly "
        f"{total_topics} short videos in total, so the unit targets should sum "
        f"to about {total_topics}.\n\n"
        f"Sizes need not be equal: an early unit covering the obvious ground "
        f"can be large, a late specialist unit small.\n\n"
        f"Order the units so that the level rises steadily from foundation to "
        f"specialist, and put the levels in that order."
    )

    data = call_json(system, user, _outline_schema(),
                     operation="curriculum_outline",
                     max_tokens=OUTLINE_MAX_TOKENS, effort=OUTLINE_EFFORT)

    units = data.get("units") or []
    if not units:
        from core.errors import PipelineError
        raise PipelineError(
            "The outline came back with no units.",
            user_message="Couldn't design a topic plan for this channel. Its "
                         "style prompt may be too vague to plan a syllabus from "
                         "— try again with a subject.",
        )
    if len(units) != unit_count:
        # Not fatal. The ordering is what matters and a syllabus of 23
        # units is as usable as one of 25; failing here would throw away
        # a good answer over a number nobody will notice.
        log.warning(f"Asked for {unit_count} units, got {len(units)}")
    return data


def write_unit_topics(channel, curriculum: dict, unit: dict,
                      count: int = None) -> list:
    """One unit's topics, in the order they should be made.

    The outline goes in every call so a unit knows what came before it and
    what comes after — without that, unit 12 restates unit 4 in different
    words, which is the same failure as repeating a topic but harder to
    notice.
    """
    count = min(count or unit.get("target_topics", 40), MAX_TOPICS_PER_CALL)

    outline = "\n".join(
        f"{i + 1}. [{u['level']}] {u['title']} — {u.get('summary', '')}"
        for i, u in enumerate(curriculum["units"]))

    # Titles only, and only from earlier units plus this one. The whole
    # syllabus would grow this prompt without bound as the channel runs,
    # and a unit cannot repeat something that has not been written yet.
    position = next((i for i, u in enumerate(curriculum["units"])
                     if u["id"] == unit["id"]), 0)
    earlier_ids = {u["id"] for u in curriculum["units"][:position + 1]}
    existing = [t["title"] for t in curriculum["topics"] if t["unit"] in earlier_ids]

    system = [
        SystemBlock(
            "You write the topic list for one unit of a short-form video "
            "channel's syllabus. Each topic is one video.\n\n"
            "A topic must be narrow enough that it could not be confused with "
            "any other in the list — 'how interest works' and 'compound "
            "interest' are two videos; 'money' is not a topic at all. Stay "
            "inside the unit you are given: material belonging to a later unit "
            "must be left for it.",
            cacheable=True),
        SystemBlock(f"This channel's own description of what it makes:\n\n"
                    f"{channel.style_prompt}", cacheable=True),
        SystemBlock(f"The full syllabus, in order:\n\n{outline}"),
    ]

    already = ""
    if existing:
        listed = "\n".join(f"- {title}" for title in existing[-300:])
        already = (f"\n\nThese topics are already in the syllabus. Do not repeat "
                   f"any of them, and do not write a near-duplicate under a "
                   f"different name:\n{listed}")

    user = (
        f"Write {count} topics for unit {position + 1}, "
        f"\"{unit['title']}\" ({unit['level']}).\n\n"
        f"What this unit covers: {unit.get('summary', '')}\n\n"
        f"Order them so the easier ones come first within the unit."
        f"{already}"
    )

    data = call_json(system, user, _topics_schema(),
                     operation="curriculum_topics",
                     max_tokens=TOPICS_MAX_TOKENS, effort=TOPICS_EFFORT)

    written = data.get("topics") or []
    if len(written) < count:
        log.info(f"Unit {unit['id']}: asked for {count} topics, got {len(written)}")
    return written


def estimate_cost(unit_count: int = DEFAULT_UNIT_COUNT) -> dict:
    """Roughly what a full syllabus costs, for the confirmation prompt.

    Deliberately an over-estimate. Someone deciding whether to spend money
    is better served by a figure that turns out generous than one that
    turns out short.
    """
    # Grounded in a real run: an 8-unit outline came in at 1016 in / 630
    # out ($0.008), and a 15-topic unit at ~1.1k in / 730 out ($0.010).
    # Scaled up to 25 units and 40 topics and then rounded up again, which
    # is why a full plan quotes near a dollar and has cost about half that
    # in practice.
    outline = (1_500 * 3 / 1e6) + (3_000 * 15 / 1e6)
    per_unit = (2_000 * 3 / 1e6) + (2_500 * 15 / 1e6)
    return {
        "outline_usd": outline,
        "per_unit_usd": per_unit,
        "full_usd": outline + per_unit * unit_count,
        "unit_count": unit_count,
    }
