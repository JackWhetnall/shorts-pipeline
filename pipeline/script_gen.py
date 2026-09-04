"""
Turning a seed into a structured script.

Two seed shapes, one output shape — that equivalence is what lets every
later stage (voiceover, captions, footage, assembly) stay completely
generic about content format:

  - a quote: the source text is fixed and must not be altered, so the
    model supplies only its shot brief and keywords plus the analysis
    segments;
  - a topic: nothing is fixed, so every segment is generated.

What kind of content a topic channel produces — jokes, a science
explainer, anything else — lives entirely in the channel's style prompt.
There is no format-specific logic in this module and there shouldn't be.

**Shot briefs.** Each segment carries a literal, filmable description of
what should be on screen, separate from what is being said. This is the
fix for the footage matching that never worked: the generator used to
emit abstract theme keywords — "integrity", "dignity", "conviction" —
and 63% of them appeared nowhere in any clip description in the library,
because nothing can film an abstract noun. Clip descriptions are
intensely literal ("prayer beads coiled on a polished wooden table"), so
matching literal against abstract was never going to work, at any
confidence threshold. The brief closes that gap at the only point where
it is cheap to close: while the model still has the passage in front of
it and is already being paid for a call. See
docs/decisions/012-shot-briefs.md.

Output is schema-constrained, so the old ask-for-JSON-then-regex-it-out
step is gone. Note that the schema deliberately carries no `minItems` /
`maxItems`: the API rejects array bounds other than 0 or 1, so the
segment count is stated in the prompt and verified in code below.
"""

from __future__ import annotations

from core import job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline import llm
from pipeline.plan import Script, Seed, Segment

log = get_logger(__name__)

SHOT_BRIEF_GUIDANCE = """
"shot_brief" is what the viewer should SEE while this line is spoken —
one short sentence, literal and filmable, describing a real scene a stock
clip could contain. Concrete nouns and visible actions only.

Good: "hands opening slowly, palms up, in soft window light"
Good: "an empty country road at dusk, low sun behind bare trees"
Good: "steam rising from a mug on a kitchen table, morning light"
Bad:  "a sense of quiet integrity"        (not a thing you can film)
Bad:  "the weight of generational memory"  (not a thing you can film)

If the line is abstract, choose an image that carries its FEELING. That
is what background footage is for — you are briefing an editor on what to
cut to, not illustrating a dictionary definition.

"keywords" are 2-4 short, concrete, searchable terms drawn from that same
image — the things a stock footage site would have tagged. "open hands",
"country road", "steam", "candle". Never abstract nouns like "hope",
"integrity" or "clarity": nothing in a footage library is tagged with
those, so they match nothing.
""".strip()


def _segment_properties() -> dict:
    return {
        "text": {"type": "string"},
        "shot_brief": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
    }


PACKAGING_GUIDANCE = """
"title_options" are 3 candidate video titles: 3-8 words, specific to THIS
passage, written to make someone stop scrolling without overpromising or
resorting to clickbait punctuation. No quotation marks, no all-caps, no
trailing exclamation marks.

"description_body" is the top of the video description: one or two
sentences that say what this video is actually about, then a blank line,
then 3-5 relevant hashtags on one line. Do not include the reference, any
links, or a call to action — those are added afterwards from the
channel's own settings.
""".strip()

PACKAGING_SCHEMA = {
    "title_options": {"type": "array", "items": {"type": "string"}},
    "description_body": {"type": "string"},
}


def _segments_schema(extra: dict = None) -> dict:
    """The response schema.

    No array length bounds: the API rejects `minItems`/`maxItems` values
    other than 0 or 1, so asking for "exactly 3 segments" that way returns
    a 400. The count is stated in the prompt and checked after the fact
    by `_check_count`.
    """
    schema = {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": _segment_properties(),
                    "required": ["text", "shot_brief", "keywords"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["segments"],
        "additionalProperties": False,
    }
    schema["properties"].update(PACKAGING_SCHEMA)
    if extra:
        schema["properties"].update(extra)
    schema["required"] = list(schema["properties"])
    return schema


QUOTE_SCHEMA_EXTRA = {
    "quote_shot_brief": {"type": "string"},
    "quote_keywords": {"type": "array", "items": {"type": "string"}},
}


# Measured across this project's own finished videos: 158 words in 63.8s,
# 106 in 44.6s, 59 in 22.8s — 2.5 words per second of finished video,
# including the pauses between segments and the outro. Steady enough to
# turn a target duration into a word budget.
WORDS_PER_SECOND = 2.5


def word_budget(pacing, count: int, spoken_words: int = 0) -> dict:
    """How many words this video's segments should come to.

    `spoken_words` is text that will be read but is not ours to write —
    the quote in a static-corpus video. It comes out of the budget first,
    because a 60-word verse and a 12-word one leave very different room
    for the analysis around them.

    Floors at 12 words a segment: below that the model writes captions
    rather than sentences, and the result is not worth rendering.
    """
    total = max(0, int(pacing.target_seconds * WORDS_PER_SECOND) - spoken_words)
    per_segment = max(12, total // max(1, count))
    return {
        "total_words": per_segment * count,
        "per_segment": per_segment,
        "target_seconds": pacing.target_seconds,
    }


def _quote_instructions(count: int, budget: dict) -> str:
    return (
        f"Write original analysis of this quote, split into EXACTLY {count} segments "
        f"of roughly {budget['per_segment']} words each "
        f"({budget['total_words']} words in total). Return exactly {count} "
        f"entries in \"segments\" — no more, no fewer.\n\n"
        "This has to be real, substantive analysis grounded in the specifics of this "
        "exact passage — who said it, its surrounding context, the historical moment, a "
        "concrete modern parallel. Not a fill-in-the-blank reading that would work just "
        f"as well for any other passage. The finished video needs to run about "
        f"{budget['target_seconds']:.0f} seconds, so a thin one-liner isn't an option "
        f"— and going long is just as wrong.\n\n"
        "Each segment is spoken on its own, so it must read naturally as a standalone "
        "chunk rather than as a fragment of a longer sentence.\n\n"
        '"quote_shot_brief" and "quote_keywords" describe the footage for the quote '
        "itself; each segment's own fields describe the footage for that segment.\n\n"
        f"{SHOT_BRIEF_GUIDANCE}\n\n{PACKAGING_GUIDANCE}"
    )


def _topic_instructions(count: int, budget: dict) -> str:
    return (
        f"Write EXACTLY {count} segments on this topic, following the style and format "
        f"given in your instructions. Return exactly {count} entries in \"segments\" — "
        f"no more, no fewer.\n\n"
        f"Aim for roughly {budget['per_segment']} words per segment "
        f"({budget['total_words']} in total): the finished video needs to run about "
        f"{budget['target_seconds']:.0f} seconds. Going long is as wrong as going "
        f"short.\n\n"
        "Each segment is spoken on its own, so it must read naturally as a standalone "
        "chunk rather than as a fragment of a longer sentence.\n\n"
        f"{SHOT_BRIEF_GUIDANCE}\n\n{PACKAGING_GUIDANCE}"
    )


# How many earlier videos to name. Enough to place this one in its topic;
# not so many that the prompt grows without bound as a topic fills up, or
# that the model tries to reference all of them.
CONTINUITY_LIMIT = 8


def _continuity(channel, seed) -> str:
    """What earlier videos in this subtopic's own topic already covered.

    Off by default. Right for a channel teaching something in order, where
    video 7 should not re-explain what videos 1-6 established; wrong for
    one whose videos are meant to stand alone and be found individually,
    which most short-form is.

    Titles only, and only from the same topic: enough to say "this ground
    is taken", not enough to invite a recap.
    """
    if not getattr(channel, "build_on_previous", False) or not seed.topic_id:
        return ""
    try:
        from core import curriculum

        entry = curriculum.find(channel.key, seed.topic_id)
        if not entry:
            return ""
        earlier = [row["title"] for row in
                   curriculum.covered_in_topic(channel.key, entry["topic"])
                   if row["id"] != seed.topic_id]
    except Exception:  # noqa: BLE001 - context is a bonus, never a blocker
        log.debug("Could not read earlier subtopics for continuity", exc_info=True)
        return ""

    if not earlier:
        return ""
    listed = "\n".join(f"- {title}" for title in earlier[-CONTINUITY_LIMIT:])
    return (
        f"This channel's videos build on each other. Earlier videos in this "
        f"same part of the syllabus have already covered:\n{listed}\n\n"
        f"Assume the viewer has seen those. Do not re-explain them, and do "
        f"not repeat their examples — you may refer back briefly where it "
        f"genuinely helps. This video is still about its own subject.\n\n"
    )


def _clean(text: str) -> str:
    """Collapse whitespace. Generated text sometimes arrives with line
    breaks that would otherwise reach the TTS engine and the captions."""
    return " ".join((text or "").split())


def _check_count(segments: list, wanted: int) -> None:
    """Warn, don't fail, when the model returns the wrong number.

    A count mismatch changes pacing but still produces a usable video, and
    failing a run that already paid for a script over a cosmetic
    difference would be the wrong trade. It is worth saying out loud,
    though — a persistent mismatch means the prompt needs work.
    """
    if len(segments) != wanted:
        log.warning(f"  [script] asked for {wanted} segment(s), got {len(segments)}. "
                    f"Continuing with what came back.")


def _to_segment(raw: dict) -> Segment:
    return Segment(
        text=_clean(raw["text"]),
        shot_brief=_clean(raw.get("shot_brief", "")),
        keywords=[k.strip().lower() for k in (raw.get("keywords") or []) if k and k.strip()],
    )


def generate_script(seed: Seed, channel) -> Script:
    """Seed plus channel config in, Script out.

    Takes the whole channel rather than an unpacked style prompt and
    pacing dict, so adding a channel-level knob that affects script
    generation doesn't change this signature.
    """
    count = channel.pacing.segment_count

    if seed.type == "quote":
        # The quote is spoken too, and its length is not ours to choose —
        # they are someone else's words. Its share comes out of the budget
        # first, so a 60-word verse and a 12-word one leave the analysis
        # the right amount of room rather than the same amount.
        budget = word_budget(channel.pacing, count,
                             spoken_words=len(seed.text.split()))
        schema = _segments_schema(extra=QUOTE_SCHEMA_EXTRA)
        user_msg = (f'Quote: "{seed.text}"\n'
                    f"Reference: {seed.reference}\n\n"
                    f"{_quote_instructions(count, budget)}")
    elif seed.type == "topic":
        budget = word_budget(channel.pacing, count)
        schema = _segments_schema()
        user_msg = (f'Topic: "{seed.topic}"\n\n'
                    f"{_continuity(channel, seed)}"
                    f"{_topic_instructions(count, budget)}")
    else:
        raise PipelineError(
            f"unknown seed type {seed.type!r}",
            user_message="This channel produced a seed the pipeline doesn't recognise.",
        )

    data = llm.call_json(
        channel.style_prompt, user_msg, schema,
        operation="script", max_tokens=2500,
    )

    generated = [_to_segment(s) for s in data["segments"]]
    _check_count(generated, count)
    if not generated:
        raise PipelineError(
            "the script came back empty",
            user_message=("The AI returned an empty script. Retrying usually works; "
                          "if it keeps happening, check this channel's style prompt."),
        )

    titles = [_clean(t) for t in (data.get("title_options") or []) if t and t.strip()]
    description_body = (data.get("description_body") or "").strip()

    if seed.type == "quote":
        # Segment 0 is the source text verbatim — never regenerated,
        # never cleaned beyond whitespace. It's someone else's words.
        quote_segment = Segment(
            text=_clean(seed.text),
            shot_brief=_clean(data.get("quote_shot_brief", "")),
            keywords=[k.strip().lower() for k in (data.get("quote_keywords") or []) if k.strip()],
        )
        return Script(segments=[quote_segment] + generated, citation=seed.reference,
                      title_options=titles, description_body=description_body)

    return Script(segments=generated, citation=None,
                  title_options=titles, description_body=description_body)


def preview_script(seed: Seed, channel) -> Script:
    """Generate a script and nothing else.

    Exists so a style prompt can be evaluated for about a cent instead of
    a full render. The style prompt is the highest-leverage field in the
    system and, until this, the only way to see what a change did was to
    make an entire video.
    """
    return generate_script(seed, channel)


def run(plan):
    """Pipeline stage: fill in plan.script.

    Reuses a checkpointed script when one exists — a retry of an
    interrupted job shouldn't pay for a Claude call it already made.
    """
    job_context.report_stage(1)

    cached = job_context.load_json_checkpoint("script")
    if cached:
        log.info("[1/5] Reusing the script from the interrupted attempt.")
        plan.script = Script.from_jsonable(cached)
        return plan

    log.info("[1/5] Writing the script...")
    plan.script = generate_script(plan.seed, plan.channel)
    log.info(f"      {len(plan.script.segments)} segment(s).")

    try:
        job_context.save_json_checkpoint("script", plan.script.to_jsonable())
    except Exception:  # noqa: BLE001 - checkpointing is best-effort
        pass
    return plan
