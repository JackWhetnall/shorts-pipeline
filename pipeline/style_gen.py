"""
Generation that helps set up how a channel looks and sounds, as opposed
to `script_gen`'s job of writing one video.

## Suggesting a look

`suggest_palette` picks a palette **key** and a font **key** from
`core.palettes` — never raw colours. The model is never given the option
to invent a hex value, so however wrong the guess is thematically, it
cannot produce something illegible or ugly; every entry in the curated
list has already been checked for that by `core.palettes` itself.

This is deliberately a separate, tiny call rather than folded into
anything else: it can be re-run at any time from Settings' Look section,
not only during initial setup, and its failure mode should be "nothing
changed" rather than blocking whatever else was happening.
"""

from __future__ import annotations

from core import palettes
from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

PALETTE_MAX_TOKENS = 1500
PALETTE_EFFORT = "low"


def _palette_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "palette_key": {
                "type": "string",
                "enum": [p.key for p in palettes.PALETTES],
            },
            "font_key": {
                "type": "string",
                "description": "Must be one of the palette's own listed faces.",
            },
            "reason": {
                "type": "string",
                "description": "One sentence on why this fits the channel.",
            },
        },
        "required": ["palette_key", "font_key", "reason"],
        "additionalProperties": False,
    }


def suggest_palette(channel) -> dict:
    """One palette + face, picked for this channel's subject.

    Falls back to a uniform random pick from the same curated list if the
    call fails for any reason — a suggestion is a convenience, and a
    channel's look must never be blocked on an API call succeeding.
    """
    listing = "\n".join(
        f"- {p.key}: {p.mood} (faces: {', '.join(p.font_faces)})" for p in palettes.PALETTES)

    system = [
        SystemBlock(
            "You pick a caption colour palette and font for a short-form video "
            "channel, from a fixed list. You are matching a mood to a subject, "
            "not designing anything — every option is already visually sound, "
            "so pick the one whose feel fits this channel best.\n\n"
            f"Available palettes:\n{listing}",
            cacheable=True),
    ]
    user = (
        f"Channel name: {channel.channel_display_name or channel.key}\n"
        f"What it makes: {channel.style_prompt or '(not written yet)'}\n\n"
        f"Pick one palette_key from the list above, and one font_key from "
        f"that specific palette's own faces (not any other palette's)."
    )

    try:
        data = call_json(system, user, _palette_schema(),
                         operation="palette_suggestion",
                         max_tokens=PALETTE_MAX_TOKENS, effort=PALETTE_EFFORT)
        palette = palettes.get(data.get("palette_key", ""))
        font_key = data.get("font_key", "")
        if font_key not in palette.font_faces:
            # The model naming a face outside the chosen palette is a
            # prompt-following slip, not a reason to fail the whole
            # suggestion — falling back to the palette's own default face
            # keeps the pairing (and therefore the legibility guarantee)
            # intact regardless.
            font_key = palette.font_faces[0]
        return {"palette_key": palette.key, "font_key": font_key,
                "reason": data.get("reason", ""), "source": "ai"}
    except PipelineError as exc:
        log.info(f"Palette suggestion fell back to random: {exc}")
        palette, face = palettes.random_choice()
        return {"palette_key": palette.key, "font_key": face,
                "reason": "Picked at random.", "source": "random"}


# --- drafting candidate style prompts ---------------------------------

DRAFT_MAX_TOKENS = 8000
DRAFT_EFFORT = "medium"        # genuine writing judgement, not a listing task

SAMPLE_SEGMENT_COUNT = 2
SAMPLE_TARGET_SECONDS = 20.0   # short: enough to show cadence, not a full video


def _candidates_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "blurb": {
                            "type": "string",
                            "description": "One short phrase distinguishing "
                                           "this draft from the others at a "
                                           "glance, e.g. \"opens each video "
                                           "with a small ritual moment\".",
                        },
                        "style_prompt": {
                            "type": "string",
                            "description": "The complete instructions a "
                                           "script writer would follow. "
                                           "Written as real prose, the way "
                                           "a person would write it, not a "
                                           "restatement of the choices as a "
                                           "list.",
                        },
                    },
                    "required": ["blurb", "style_prompt"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


def draft_candidates(channel, choices: dict, count: int = 5) -> list:
    """`count` distinct style prompts, all consistent with the same
    picker choices but genuinely different in phrasing, structure or
    emphasis — so comparing them is comparing real interpretations, not
    noise from resampling one prompt.

    Takes only the picker's choices, never freehand prose from the person
    setting the channel up — the entire point of the picker is that you
    select rather than write, and a required example field would quietly
    reintroduce the "invent the right words yourself" problem it exists
    to remove.
    """
    from core import style_choices

    system = [
        SystemBlock(
            "You write style-prompt instructions for a short-form video "
            "script generator, from a fixed set of choices about format, "
            "tone and register. Each style prompt you write is a complete, "
            "standalone set of instructions a different writer could follow "
            "with no other context.\n\n"
            "Write real instructive prose, the way an experienced showrunner "
            "would brief a writer — not a restatement of the choices as a "
            "list, and not generic advice that could apply to any channel. "
            "Describe the shape and habits of the writing: how it tends to "
            "open, how it moves between ideas, the vocabulary register, what "
            "it avoids.\n\n"
            "Never give a quotable example line or an exact sentence to "
            "follow. A script generator hands this prompt to a model that "
            "writes every episode, and a model given one sample sentence "
            "reuses it, or a thin paraphrase of it, almost verbatim in "
            "nearly every video — that is exactly the failure this system "
            "exists to avoid. Say what a good opening DOES ('drops straight "
            "into the specific thing being tried, no throat-clearing') "
            "rather than what one SAYS ('something like \"Okay, today's "
            "experiment is...\"'). If a sentence you're about to write could "
            "be copied into quotation marks and read aloud as-is, rewrite it "
            "as a description of the technique instead.",
            cacheable=True),
    ]
    user = (
        f"Channel: {channel.channel_display_name or channel.key}\n\n"
        f"Choices:\n{style_choices.describe(choices)}\n\n"
        f"Write exactly {count} candidate style prompts. Each must be "
        f"consistent with every choice above, but genuinely distinct from "
        f"the others — vary the concrete phrasing habits, the shape of a "
        f"typical opening line, and what the channel tends to come back to, "
        f"not the underlying choices themselves. Return exactly {count} "
        f"entries in \"candidates\"."
    )

    data = call_json(system, user, _candidates_schema(),
                     operation="style_candidates",
                     max_tokens=DRAFT_MAX_TOKENS, effort=DRAFT_EFFORT)
    candidates = data.get("candidates") or []
    if not candidates:
        raise PipelineError(
            "No style candidates came back.",
            user_message="Couldn't draft any style options just now. Try again.",
        )
    if len(candidates) != count:
        log.info(f"Asked for {count} style candidates, got {len(candidates)}")
    return candidates


def sample_for_candidate(channel, seed, style_prompt: str):
    """A short, real script written under one candidate prompt.

    Reuses `script_gen.generate_script` directly rather than a parallel
    implementation — a comparison sample has to be produced by the exact
    same code path a real video would use, or a candidate could look good
    here and behave differently once actually in use. `dataclasses.replace`
    swaps in the candidate prompt and a short sample length on copies of
    the channel and its pacing; the real channel on disk is never touched
    by this, only by the caller saving the one the user picks.
    """
    import dataclasses

    from pipeline.script_gen import generate_script

    sample_pacing = dataclasses.replace(
        channel.pacing, segment_count=SAMPLE_SEGMENT_COUNT,
        target_seconds=SAMPLE_TARGET_SECONDS)
    sample_channel = dataclasses.replace(
        channel, style_prompt=style_prompt, pacing=sample_pacing,
        build_on_previous=False)
    return generate_script(seed, sample_channel)


# --- hearing a candidate read aloud -------------------------------------

SNIPPET_MAX_CHARS = 400   # a sample is already short; this is just a guard


def listen_snippet(voice_id: str, text: str, speed: float = 1.0):
    """A cached short audio clip of `text` read by `voice_id`.

    Mirrors `core.voice_lab.get_or_create_snippet`: generated once through
    the real TTS path (so it behaves like a real video's narration would,
    not a separate lighter-weight call), then reused for the same text and
    voice. Comparison samples are short and few, so the cache stays small.
    """
    import hashlib

    from core.channels import Pacing
    from core.paths import CACHE_DIR
    from pipeline import tts
    from pipeline.plan import Segment

    samples_dir = CACHE_DIR / "style_setup_samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    text = text.strip()[:SNIPPET_MAX_CHARS]
    digest = hashlib.sha1(f"{voice_id}|{speed}|{text}".encode("utf-8")).hexdigest()[:16]
    safe_voice = "".join(c for c in voice_id if c.isalnum() or c in "-_")
    target = samples_dir / f"{safe_voice}_{digest}.mp3"
    if target.exists():
        return target

    pacing = Pacing(segment_count=1)
    tts.generate_voiceover([Segment(text)], None, voice_id, str(target),
                           pacing, speed=speed)
    return target
