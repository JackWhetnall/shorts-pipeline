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
from pipeline import llm, similarity
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


HOOK_AND_LANDING_GUIDANCE = """
THE HOOK. People decide in about a second and a half whether to keep
watching. The first line has to stop someone mid-scroll: a jolt of
surprise, stakes or intrigue so specific that they need the rest.

A hook that works:
- Leads with the most surprising, concrete thing in the video, or its
  sharpest consequence. Start at the interesting part, never at the setup.
- Says something the viewer didn't expect about something they
  recognise. A statement usually beats a question; a question only works
  when the viewer is suddenly desperate for its answer.
- Is concrete: a real object, number, person, place or moment. Abstract
  intrigue slides straight past.
- Is short: under 12 words, ideally under 9, readable as a caption at a
  glance.
- Promises a payoff the video genuinely delivers, and bigger than the hook
  suggests. Honest, never bait.
- Sounds like this channel (its hook style, below). A reverent channel is
  quietly arresting, but still arresting.

Never open with: a scene or a hypothetical ("picture...", "imagine...",
"say you...", "you're standing..."), a textbook question ("how do you
find..."), "have you ever", "did you know", "ever wondered", "let's talk
about", "in this video", "today", a greeting, vague mystery with nothing
concrete in it ("this changes everything"), or the answer itself.

Method: write five different hooks in "hook_candidates" first, each by a
different route: the counter-intuitive claim; the surprising real-world
consequence (the everyday thing that only works because of this); one
startling specific number or detail; the stakes (what not knowing this
costs someone); the belief most people hold that is wrong; the real
mystery with a real answer; the vivid mid-action line. Then choose the one
that would stop the most people: a stranger understands it instantly, on
first hearing, and wants it explained. Usually the most specific and
surprising, not the cleverest; if a line needs a second read to make
sense, it's not the one. Open the video with it word for word.

THE MIDDLE keeps the promise open and moving: each segment earns the next.
Don't resolve the hook early.

THE LANDING. The last segment delivers the payoff concretely: the answer,
the number, the moment it clicks, or what the viewer can now see or do,
ideally calling back to the hook. Then it stops, on the natural last
thing a person would say. Never a summary, a moral, or a slogan-shaped
closing line; no "thanks for watching" or "follow for more" (the outro
card does that). A channel that closes on a reflective question still
delivers it as a last line, not a lead-in.

"hook_promise" names what the hook makes the viewer want (in a phrase) and
"payoff" says how the ending delivers it. Plan both before the lines.
""".strip()

HUMAN_VOICE_GUIDANCE = """
SOUND LIKE A PERSON. This is read aloud as a short-form video, so it has
to sound like someone talking to camera, not like writing. Talk the way
a sharp friend explains something: contractions, "you", plain verbs,
specific examples, sentences of uneven length; a fragment now and then is
fine.

These phrases mark a script as AI-written, and viewers scroll past them.
Never use them or anything shaped like them: "that's the (whole) trick",
"here's the thing", "here's the kicker/catch/twist", "it's not X, it's
Y", "not just X, but Y", "let that sink in", "the magic/beauty of",
"simply put", "in short", "the key takeaway", "turns out", "picture
this", "ever wondered", "delve", "unlock", "game-changer", "journey",
"tapestry", "a testament to", rhetorical triplets ("three sides, one
rule, zero guesswork"), and any neat, symmetrical closing line.
""".strip()

# The same tells, caught after the fact (one rewrite, like placeholder
# text). Narrow on purpose: each is a phrase real narration almost never
# needs, so a hit is worth a penny to rewrite.
_AI_TELLS = re.compile(
    r"\bthat'?s (?:the (?:whole|real|entire) \w+|all (?:it is|there is to it)|the (?:trick|secret|magic|point))\b"
    r"|\bhere'?s the (?:thing|kicker|catch|twist|deal)\b"
    r"|\blet that sink in\b|\bthe (?:magic|beauty) of\b|\bsimply put\b|\bkey takeaway\b"
    r"|\bpicture this\b|\bever wondered\b|\bdelv(?:e|es|ing)\b|\bgame[- ]changer\b"
    r"|\ba testament to\b|\btapestry\b"
    # "It's not X, it's Y" and its cousins ("that's not a trick, it's...",
    # "he isn't describing X, he's describing Y").
    r"|\b\w+(?:'s|'re| is| are)? ?(?:not|isn't|aren't|wasn't) "
    r"[^.?!]{1,50}?[,;—–-] ?(?:it|that|this|he|she|they|you)(?:'s|'re| is| are)\b",
    re.I)
_WEAK_OPENING = re.compile(
    r"^(?:picture|imagine|say you|have you ever|did you know|ever wondered|let'?s talk"
    r"|in this video|today|hey|hi)\b", re.I)


def ai_tells(segments: list) -> list:
    """Lines that read as AI-written, and a weak opening, as fix notes."""
    notes = []
    for segment in segments:
        match = _AI_TELLS.search(segment.text)
        if match:
            notes.append(f'"{match.group(0)}" in: {segment.text}')
    if segments and _WEAK_OPENING.match(segments[0].text):
        notes.append(f"The opening is a setup, not a hook: {segments[0].text}")
    return notes


def _channel_hook(channel) -> str:
    """The channel's own way of hooking, when it has one."""
    style = (getattr(channel, "hook_style", "") or "").strip()
    return f"How this channel opens, in its own voice: {style}\n\n" if style else ""


QUOTE_HOOK_GUIDANCE = """
On this channel the video begins with "hook", one spoken line said BEFORE
the passage is read. It is the opening described above: it makes the
listener want to hear the passage, and hear it differently, without
explaining it or giving away what the analysis will find. The passage
follows it, then the segments. The last segment is the landing.
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

# First in the schema, so the loop is planned before any line is written.
PLAN_SCHEMA = {
    "hook_candidates": {"type": "array", "items": {"type": "string"},
                        "description": "Five different hooks, each by a different route."},
    "hook_promise": {"type": "string",
                     "description": "The question or tension the opening line opens, in a phrase."},
    "payoff": {"type": "string",
               "description": "How and where the ending closes that loop."},
}


def _segments_schema(extra: dict = None, lead: dict = None) -> dict:
    """The response schema.

    No array length bounds: the API rejects `minItems`/`maxItems` values
    other than 0 or 1, so asking for "exactly 3 segments" that way returns
    a 400. The count is stated in the prompt and checked after the fact
    by `_check_count`.
    """
    schema = {
        "type": "object",
        "properties": {
            **PLAN_SCHEMA,
            **(lead or {}),
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

# The hook line spoken before the passage, with its own footage.
QUOTE_SCHEMA_LEAD = {
    "hook": {"type": "string", "description": "The chosen hook, word for word, said before the "
                                              "passage: one full sentence with its capital and "
                                              "its final punctuation."},
    "hook_shot_brief": {"type": "string"},
    "hook_keywords": {"type": "array", "items": {"type": "string"}},
}
HOOK_WORDS = 10          # what the hook takes out of a quote video's budget
# Thinking is billed from this too: room to reason, draft five hooks and
# write the script.
SCRIPT_MAX_TOKENS = 4000


# Measured across this project's own finished videos: 158 words in 63.8s,
# 106 in 44.6s, 59 in 22.8s — 2.5 words per second of finished video,
# including the pauses between segments and the outro. Steady enough to
# turn a target duration into a word budget.
WORDS_PER_SECOND = 2.5


def word_budget(pacing, count: int, spoken_words: int = 0, speed: float = 1.0) -> dict:
    """How many words this video's segments should come to.

    `spoken_words` is text that will be read but is not ours to write —
    the quote in a static-corpus video. It comes out of the budget first,
    because a 60-word verse and a 12-word one leave very different room
    for the analysis around them.

    Floors at 12 words a segment: below that the model writes captions
    rather than sentences, and the result is not worth rendering.

    `speed` is the channel's voice speed. The 2.5 words a second was
    measured at normal speed, so a channel read at 0.85 fits proportionally
    fewer words in the same time. Ignoring it is how a 60-second target
    produced a 74-second video.
    """
    total = max(0, int(pacing.target_seconds * WORDS_PER_SECOND * speed) - spoken_words)
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
        "itself, \"hook_shot_brief\" and \"hook_keywords\" the footage for the hook; "
        "each segment's own fields describe the footage for that segment.\n\n"
        f"{HOOK_AND_LANDING_GUIDANCE}\n\n{HUMAN_VOICE_GUIDANCE}\n\n{QUOTE_HOOK_GUIDANCE}\n\n"
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
        "chunk rather than as a fragment of a longer sentence. The first segment opens "
        "with the hook; the last is the landing.\n\n"
        f"{HOOK_AND_LANDING_GUIDANCE}\n\n{HUMAN_VOICE_GUIDANCE}\n\n"
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


_QUESTION_START = re.compile(
    r"^(what|why|how|when|who|whom|whose|where|which|is|are|was|were|do|does|did|can|"
    r"could|would|should|will|have|has|had)\b", re.I)


def _sentence(text: str) -> str:
    """A spoken line as a finished sentence: it is burned into the
    captions too. Hooks came back as caption fragments ("why does he keep
    answering her") with no capital and no question mark."""
    text = _clean(text)
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?…\"'”’":
        text += "?" if _QUESTION_START.match(text) else "."
    return text


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


def generate_script(seed: Seed, channel, avoid: str = "") -> Script:
    """Seed plus channel config in, Script out.

    Takes the whole channel rather than an unpacked style prompt and
    pacing dict, so adding a channel-level knob that affects script
    generation doesn't change this signature. `avoid`, when given, is
    appended to the request: the originality gate uses it to say what an
    earlier script already said.
    """
    count = channel.pacing.segment_count

    if seed.type == "quote":
        # The quote is spoken too, and its length is not ours to choose —
        # they are someone else's words. Its share comes out of the budget
        # first, so a 60-word verse and a 12-word one leave the analysis
        # the right amount of room rather than the same amount.
        budget = word_budget(channel.pacing, count,
                             spoken_words=len(seed.text.split()) + HOOK_WORDS,
                             speed=channel.speed)
        schema = _segments_schema(extra=QUOTE_SCHEMA_EXTRA, lead=QUOTE_SCHEMA_LEAD)
        user_msg = (f'Quote: "{seed.text}"\n'
                    f"Reference: {seed.reference}\n\n"
                    f"{_channel_hook(channel)}"
                    f"{_quote_instructions(count, budget)}")
    elif seed.type == "topic":
        budget = word_budget(channel.pacing, count, speed=channel.speed)
        schema = _segments_schema()
        user_msg = (f'Topic: "{seed.topic}"\n\n'
                    f"{_continuity(channel, seed)}"
                    f"{_channel_hook(channel)}"
                    f"{_topic_instructions(count, budget)}")
    else:
        raise PipelineError(
            f"unknown seed type {seed.type!r}",
            user_message="This channel produced a seed the pipeline doesn't recognise.",
        )
    if avoid:
        user_msg = f"{user_msg}\n\n{avoid}"

    data = llm.call_json(
        channel.style_prompt, user_msg, schema,
        operation="script", max_tokens=SCRIPT_MAX_TOKENS,
    )
    generated = [_to_segment(s) for s in data["segments"]]

    # One retry, and only one, when a segment reads like a note about a
    # line rather than the line itself, or when the script has AI tells or
    # opens on a setup instead of a hook. A second script call is about a
    # penny; a video whose opening line is `A catchy line with a "quoted
    # phrase" in it` is unpublishable, and one that sounds machine-written
    # gets scrolled past, so the trade is not close. Retrying further would
    # be chasing a prompt problem with money.
    notes = []
    offender = placeholder_text(generated)
    if offender:
        notes.append(f"{offender!r} is a description of a line, not a line. Write the actual words.")
    spoken = ([Segment(text=_clean(data.get("hook") or ""))] if seed.type == "quote" else []) + generated
    notes += [f"Rewrite this, it reads as AI-written or weak: {n}" for n in ai_tells(spoken)]
    if notes:
        log.warning(f"  [script] rewriting once: {'; '.join(notes)[:200]}")
        data = llm.call_json(
            channel.style_prompt,
            f"{user_msg}\n\nA previous attempt had these problems. Fix them and keep "
            f"what works:\n- " + "\n- ".join(notes),
            schema, operation="script", max_tokens=SCRIPT_MAX_TOKENS,
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
    loop = {"hook_promise": (data.get("hook_promise") or "").strip(),
            "payoff": (data.get("payoff") or "").strip()}

    if seed.type == "quote":
        # Segment 0 is the source text verbatim — never regenerated,
        # never cleaned beyond whitespace. It's someone else's words.
        quote_segment = Segment(
            text=_clean(seed.text),
            shot_brief=_clean(data.get("quote_shot_brief", "")),
            keywords=[k.strip().lower() for k in (data.get("quote_keywords") or []) if k.strip()],
        )
        hook_text = _sentence(data.get("hook") or "")
        if not hook_text:
            return Script(segments=[quote_segment] + generated, citation=seed.reference,
                          title_options=titles, description_body=description_body,
                          source_index=0, **loop)
        hook_segment = Segment(
            text=hook_text, shot_brief=_clean(data.get("hook_shot_brief", "")),
            keywords=[k.strip().lower() for k in (data.get("hook_keywords") or []) if k.strip()],
        )
        return Script(segments=[hook_segment, quote_segment] + generated,
                      citation=seed.reference, title_options=titles,
                      description_body=description_body, source_index=1, **loop)

    return Script(segments=generated, citation=None,
                  title_options=titles, description_body=description_body, **loop)


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
    _originality_gate(plan, rewritable=stored is None)
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


# How much of the earlier script a rewrite is shown. Enough to recognise
# its phrasing and structure; not so much that the request doubles.
AVOID_EXCERPT_CHARS = 1200


def _avoid_note(report) -> str:
    excerpt = (report.closest_text or "")[:AVOID_EXCERPT_CHARS]
    return (f'This channel has already published a script that reads very much like '
            f'your first attempt ("{report.closest_title}"). It said:\n\n'
            f'"""{excerpt}"""\n\n'
            f"Write something genuinely different from it: a different opening, a "
            f"different angle or example, different phrasing throughout. Do not reuse "
            f"its sentences or its structure.")


def _originality_gate(plan, rewritable: bool) -> None:
    """Check the script against this channel's history before anything
    is spent on voicing it, and rewrite it once if it's a retread.

    This used to run after the render, which meant a flagged script had
    already paid for its voiceover, its footage and its encode, and the
    flag only reached the review screen. Here it costs one more script
    call, about a cent, and the voice quota is spent on the better of the
    two. The better one is kept, not the second one regardless: a rewrite
    can land closer to some other earlier script.

    A pre-written studio script is only checked, never rewritten, because
    it may carry hand edits. See decision 026.
    """
    report = similarity.check(plan.channel.key, plan.script)
    if report.flagged and rewritable:
        log.warning(f"  [similarity] {report.summary} Rewriting it once before "
                    f"it's voiced.")
        rewrite = generate_script(plan.seed, plan.channel, avoid=_avoid_note(report))
        second = similarity.check(plan.channel.key, rewrite)
        if second.exceedance < report.exceedance:
            plan.script, report = rewrite, second
        if report.flagged:
            log.warning(f"  [similarity] still close after one rewrite: {report.summary}")
    elif report.flagged:
        log.warning(f"  [similarity] {report.summary}")
    plan.similarity = report


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
                        **PLAN_SCHEMA,
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
                    "required": ["index", *PLAN_SCHEMA, "segments", "title_options",
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
    budget = word_budget(channel.pacing, count, speed=channel.speed)

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
            f"{HOOK_AND_LANDING_GUIDANCE}\n\n{HUMAN_VOICE_GUIDANCE}\n\n{_channel_hook(channel)}"
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
                "hook_promise": (item.get("hook_promise") or "").strip(),
                "payoff": (item.get("payoff") or "").strip(),
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
    budget = word_budget(channel.pacing, count, speed=channel.speed)

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
