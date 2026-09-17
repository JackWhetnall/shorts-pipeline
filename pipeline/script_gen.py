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

import re

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


SPOKEN_TEXT_GUIDANCE = """
Every "text" is spoken aloud word for word by a voice and burned into the
captions exactly as written. It is the finished line, not a note about
what the line should be.

So: write the sentence someone will hear. Never write a description of a
line, a template, a placeholder, or an instruction to yourself. A segment
reading `A catchy opening line with a "quoted phrase" in the middle of
it` is a broken video — those are the words that get read out.

Never use square brackets, curly braces or angle brackets. Nothing later
fills them in; they are read aloud too.
""".strip()

# --- catching it when the guidance above doesn't hold -----------------
#
# A heuristic, and deliberately a narrow one. Spoken narration is
# unconstrained prose, so anything clever enough to recognise "this
# describes a line rather than being one" in general would misfire on real
# writing more often than it caught anything. These three patterns are the
# shapes an actual failure has taken, each rare enough in genuine
# narration to be worth acting on:

# Any bracketed slot. Nothing downstream substitutes these, so they are
# wrong in spoken text however they got there.
_BRACKETED = re.compile(r"[\[\{<][^\]\}>\n]{1,80}[\]\}>]")

# A structural label the writer left attached: "Hook:", "Segment 2:".
_LABELLED = re.compile(
    r"^\s*(?:segment|section|part|step|hook|intro|introduction|opening|"
    r"outro|closing|line|script|caption)\s*\d*\s*[:—-]\s",
    re.I)

# A noun phrase naming a piece of text, qualified the way an instruction
# qualifies it — "A catchy line…", "An engaging hook…". The intervening
# adjective is what keeps this off ordinary prose: "The line between two
# things" has none and doesn't match.
_DESCRIBES_A_LINE = re.compile(
    r"^\s*(?:a|an|the|your|some)\s+(?:\w+[,\s]+){1,3}"
    r"(?:line|lines|hook|opener|tagline|one-liner|phrase|sentence|segment|"
    r"paragraph|caption|voiceover|placeholder|blurb|snippet)\b",
    re.I)


def placeholder_text(segments: list) -> str:
    """The first segment that reads like a note about a line rather than
    the line itself, or "" when nothing looks wrong.

    The real defence is `SPOKEN_TEXT_GUIDANCE` in the prompt; this is the
    net under it. A false positive costs one regenerated script and a
    review flag, so it is tuned to be quiet rather than exhaustive — it
    will miss subtler failures, and that is the right trade against
    flagging honest writing.
    """
    for segment in segments:
        text = getattr(segment, "text", None)
        if text is None:
            text = (segment or {}).get("text", "") if isinstance(segment, dict) else ""
        if not text:
            continue
        if (_BRACKETED.search(text) or _LABELLED.match(text)
                or _DESCRIBES_A_LINE.match(text)):
            return text
    return ""


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
        f"{SPOKEN_TEXT_GUIDANCE}\n\n{SHOT_BRIEF_GUIDANCE}\n\n{PACKAGING_GUIDANCE}"
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
        f"{SPOKEN_TEXT_GUIDANCE}\n\n{SHOT_BRIEF_GUIDANCE}\n\n{PACKAGING_GUIDANCE}"
    )


# How many earlier videos to name. Enough to place this one in its topic;
# not so many that the prompt grows without bound as a topic fills up, or
# that the model tries to reference all of them.
CONTINUITY_LIMIT = 8


def _continuity(channel, seed) -> str:
    """What earlier videos already covered, per the channel's own
    `context_scope` — this topic only, a few topics back, or everything.

    Off by default (`build_on_previous`). Right for a channel teaching
    something in order, where video 7 should not re-explain what videos
    1-6 established; wrong for one whose videos are meant to stand alone
    and be found individually, which most short-form is.

    Titles only: enough to say "this ground is taken", not enough to
    invite a recap.
    """
    if not getattr(channel, "build_on_previous", False) or not seed.topic_id:
        return ""
    try:
        from core import curriculum

        entry = curriculum.find(channel.key, seed.topic_id)
        if not entry:
            return ""
        earlier = [row["title"] for row in
                   curriculum.covered_titles(channel.key, entry["topic"],
                                             channel.context_scope, channel.context_topics)
                   if row["id"] != seed.topic_id]
    except Exception:  # noqa: BLE001 - context is a bonus, never a blocker
        log.debug("Could not read earlier subtopics for continuity", exc_info=True)
        return ""

    if not earlier:
        return ""
    listed = "\n".join(f"- {title}" for title in earlier[-CONTINUITY_LIMIT:])
    return (
        f"This channel's videos build on each other. Earlier videos have "
        f"already covered:\n{listed}\n\n"
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

    # One retry, and only one, when a segment reads like a note about a
    # line rather than the line itself. A second script call is about a
    # penny; a video whose opening line is `A catchy line with a "quoted
    # phrase" in it` is unpublishable, so the trade is not close. Retrying
    # further would be chasing a prompt problem with money.
    offender = placeholder_text(generated)
    if offender:
        log.warning(f"  [script] a segment described a line instead of writing one "
                    f"({offender[:80]!r}). Rewriting it once.")
        data = llm.call_json(
            channel.style_prompt,
            f"{user_msg}\n\nA previous attempt returned {offender!r} as a segment's "
            f"spoken text. That is a description of a line, not a line. Write the "
            f"actual words this time.",
            schema, operation="script", max_tokens=2500,
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


def _stored_script(plan) -> Script:
    """A script already sitting on this seed's subtopic, if it has one.

    Only topic-mode channels with a curriculum have anywhere for a script
    to be stored ahead of time — everything else (quotes, a flat topic
    list with no syllabus) returns None and generates as it always has.
    """
    if plan.channel.content_mode != "topic" or not plan.seed.topic_id:
        return None
    from core import curriculum
    if not curriculum.exists(plan.channel.key):
        return None
    row = curriculum.find(plan.channel.key, plan.seed.topic_id)
    if not row or not row.get("script"):
        return None
    return Script.from_jsonable(row["script"])


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

    stored = _stored_script(plan)
    if stored is not None:
        log.info("[1/5] Using the pre-written script for this subtopic.")
        plan.script = stored
    else:
        log.info("[1/5] Writing the script...")
        plan.script = generate_script(plan.seed, plan.channel)
    log.info(f"      {len(plan.script.segments)} segment(s).")

    # Checked here rather than only in `generate_script`, because this is
    # the one place every script passes through however it got here —
    # freshly written, pre-written on the syllabus, or reloaded from an
    # interrupted attempt's checkpoint. Flagged, not failed: the words are
    # already paid for and are right there on the review screen to judge.
    plan.script_suspect = placeholder_text(plan.script.segments)
    if plan.script_suspect:
        log.warning("  [script] a segment reads like a note about a line rather "
                    "than the line itself. Read this one before publishing.")

    try:
        job_context.save_json_checkpoint("script", plan.script.to_jsonable())
    except Exception:  # noqa: BLE001 - checkpointing is best-effort
        pass
    return plan


# --- batch script generation: a topic's videos, written together ------
#
# The rest of this module writes one script for one video with no view of
# anything else. That is wrong for a channel whose videos are meant to
# build on each other — see docs/decisions/023-script-studio.md. These
# functions write real, full-length scripts for several subtopics of one
# topic in a single call, so they share one context window and are
# genuinely consistent, then store them on the syllabus ahead of any
# render. `pipeline.run.generate` never has to know this happened —
# `_stored_script` above picks it up transparently.

# Scripts are much bigger than the title+angle pairs
# `curriculum_gen.write_subtopics` batches, so a single call's blast
# radius is kept smaller: `curriculum_gen.MAX_SUBTOPICS_PER_CALL` is 30,
# this is 6.
MAX_SCRIPTS_PER_CALL = 6
SCRIPT_BATCH_EFFORT = "medium"

# Per script, plus one shared allowance for the reasoning a "medium"
# effort call spends before writing anything (billed out of max_tokens
# same as everywhere else — see docs/decisions/013-failing-safely.md).
# Scaled to the actual number of subtopics in THIS call rather than a
# flat worst-case, and `llm.call_json` clamps the result (and any
# truncation retry) under the SDK's non-streaming ceiling regardless.
SCRIPT_BATCH_TOKENS_PER_SCRIPT = 2_800
SCRIPT_BATCH_TOKENS_OVERHEAD = 1_500


def _batch_max_tokens(count: int) -> int:
    return SCRIPT_BATCH_TOKENS_OVERHEAD + SCRIPT_BATCH_TOKENS_PER_SCRIPT * count


def _batch_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "scripts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Which numbered subtopic this "
                                           "answers, matching the list you "
                                           "were given.",
                        },
                        "segments": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": _segment_properties(),
                                "required": ["text", "shot_brief", "keywords"],
                                "additionalProperties": False,
                            },
                        },
                        **PACKAGING_SCHEMA,
                    },
                    "required": ["index", "segments", "title_options",
                                "description_body"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["scripts"],
        "additionalProperties": False,
    }


def _covered_titles(channel, topic_id: str) -> str:
    """Earlier videos, titles only, per the channel's `context_scope` —
    the same text `_continuity()` builds for a single-video generation,
    reused here so a batch that starts partway through an already-active
    topic (or, with a wider scope, an already-active channel) doesn't
    re-tread what's already published."""
    if not getattr(channel, "build_on_previous", False):
        return ""
    from core import curriculum
    earlier = [row["title"] for row in
              curriculum.covered_titles(channel.key, topic_id,
                                        channel.context_scope, channel.context_topics)]
    if not earlier:
        return ""
    listed = "\n".join(f"- {t}" for t in earlier[-CONTINUITY_LIMIT:])
    return (
        f"This channel's videos build on each other. Earlier videos have "
        f"already covered:\n{listed}\n\n"
        f"Assume the viewer has seen those. Do not re-explain them, and "
        f"do not repeat their examples.\n\n"
    )


def write_scripts(channel, topic: dict, subtopics: list) -> list:
    """Real, full-length scripts for several subtopics of one topic,
    written together in a single call.

    Not a preview sample — these are what a video actually renders from,
    at the channel's real pacing. `subtopics` must already be capped to
    MAX_SCRIPTS_PER_CALL; a topic with more pending than that is the
    caller's loop to chunk, the same shape `curriculum_gen.
    write_subtopics`'s own per-topic cap already uses.

    Returns a list of `{"subtopic_id", "script"}`, one per subtopic that
    came back matched — shorter than `subtopics` if the model returned
    fewer than asked, exactly like every other generator here.
    """
    count = channel.pacing.segment_count
    budget = word_budget(channel.pacing, count)

    system = [
        llm.SystemBlock(channel.style_prompt, cacheable=True),
        llm.SystemBlock(
            f"You are writing scripts for several videos in one topic of "
            f"this channel's syllabus: \"{topic['title']}\" — "
            f"{topic.get('summary', '')}\n\n"
            f"Write them together, the way one writer would across an "
            f"afternoon of episodes on the same topic: genuinely "
            f"consistent with each other — no two opening the same way, "
            f"no repeated examples or phrasing habits — but each one "
            f"complete and correct on its own.\n\n"
            f"{_covered_titles(channel, topic['id'])}"
            f"{SPOKEN_TEXT_GUIDANCE}\n\n{SHOT_BRIEF_GUIDANCE}\n\n{PACKAGING_GUIDANCE}",
            cacheable=True),
    ]

    listed = "\n".join(f"{i + 1}. {s['title']} — {s.get('angle', '')}"
                       for i, s in enumerate(subtopics))
    user = (
        f"Write {len(subtopics)} scripts, one for each of these numbered "
        f"subtopics, each split into EXACTLY {count} segments of roughly "
        f"{budget['per_segment']} words each ({budget['total_words']} "
        f"words in total per script). Each video needs to run about "
        f"{budget['target_seconds']:.0f} seconds — going long is as wrong "
        f"as going short.\n\n"
        f"Each segment is spoken on its own, so it must read naturally as "
        f"a standalone chunk rather than as a fragment of a longer "
        f"sentence.\n\n"
        f"Tag each script with the number of the subtopic it answers. "
        f"Return exactly {len(subtopics)} entries in \"scripts\" — no "
        f"more, no fewer.\n\n{listed}"
    )

    data = llm.call_json(system, user, _batch_schema(),
                         operation="script_batch",
                         max_tokens=_batch_max_tokens(len(subtopics)),
                         effort=SCRIPT_BATCH_EFFORT)

    by_index = {}
    for item in data.get("scripts") or []:
        idx = item.get("index")
        if isinstance(idx, int) and 1 <= idx <= len(subtopics) and idx not in by_index:
            by_index[idx] = item

    written = []
    for i, subtopic in enumerate(subtopics):
        item = by_index.get(i + 1)
        if item is None:
            continue
        segments = [_to_segment(s) for s in item.get("segments") or []]
        _check_count(segments, count)
        if not segments:
            continue
        written.append({
            "subtopic_id": subtopic["id"],
            "script": {
                "citation": None,
                "segments": [s.to_jsonable() for s in segments],
                "title_options": [_clean(t) for t in (item.get("title_options") or [])
                                  if t and t.strip()],
                "description_body": (item.get("description_body") or "").strip(),
            },
        })

    if len(written) < len(subtopics):
        log.warning(f"{topic['id']}: asked for {len(subtopics)} scripts, "
                    f"got {len(written)}")
    return written


def _sibling_context(siblings: list) -> str:
    """Other scripts already written for this same topic, so a rewrite
    doesn't reuse an opening line, a specific example, or a phrasing habit
    one of them already has. `siblings` are `{"title", "script"}` dicts —
    the shape `curriculum.subtopics()` rows already carry."""
    if not siblings:
        return ""
    parts = []
    for sib in siblings:
        text = " ".join(seg["text"] for seg in sib["script"]["segments"])
        parts.append(f"- \"{sib['title']}\": {text}")
    listed = "\n".join(parts[-CONTINUITY_LIMIT:])
    return (
        f"Other videos already scripted for this same topic. Do not reuse "
        f"an opening line, a specific example, or a phrasing habit any of "
        f"these already used:\n{listed}\n\n"
    )


def regenerate_script(channel, topic: dict, subtopic: dict,
                      siblings: list, instruction: str = "") -> dict:
    """Rewrite one subtopic's script from scratch.

    `siblings` are this topic's other already-written scripts, included
    so the rewrite doesn't drift from them the way the batch call's own
    scripts stay consistent with each other. `instruction`, when given,
    is folded into the ask ("also mention X") — blank means a plain
    retry, the same request with a fresh roll.
    """
    count = channel.pacing.segment_count
    budget = word_budget(channel.pacing, count)

    system = [
        llm.SystemBlock(channel.style_prompt, cacheable=True),
        llm.SystemBlock(
            f"You are rewriting the script for one video in this "
            f"channel's syllabus, topic \"{topic['title']}\" — "
            f"{topic.get('summary', '')}.\n\n"
            f"{_sibling_context(siblings)}"
            f"{SPOKEN_TEXT_GUIDANCE}\n\n{SHOT_BRIEF_GUIDANCE}\n\n{PACKAGING_GUIDANCE}",
            cacheable=True),
    ]
    ask = f"Also: {instruction.strip()}\n\n" if instruction.strip() else ""
    user = (
        f"Subtopic: \"{subtopic['title']}\" — {subtopic.get('angle', '')}\n\n"
        f"{ask}"
        f"Write EXACTLY {count} segments, roughly {budget['per_segment']} "
        f"words each ({budget['total_words']} in total). The video needs "
        f"to run about {budget['target_seconds']:.0f} seconds.\n\n"
        f"Each segment is spoken on its own, so it must read naturally as "
        f"a standalone chunk rather than as a fragment of a longer "
        f"sentence."
    )

    data = llm.call_json(system, user, _segments_schema(),
                         operation="script_regenerate",
                         max_tokens=2500, effort="medium")

    segments = [_to_segment(s) for s in data.get("segments") or []]
    _check_count(segments, count)
    if not segments:
        raise PipelineError(
            "The rewritten script came back empty.",
            user_message="Couldn't rewrite that script just now. Try again.",
        )
    return {
        "citation": None,
        "segments": [s.to_jsonable() for s in segments],
        "title_options": [_clean(t) for t in (data.get("title_options") or [])
                          if t and t.strip()],
        "description_body": (data.get("description_body") or "").strip(),
    }
