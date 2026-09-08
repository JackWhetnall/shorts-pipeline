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
