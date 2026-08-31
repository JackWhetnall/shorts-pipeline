"""
Turns a seed (a fetched quote, or a topic with no source text) into a
structured script: a list of segments, each independently tagged with
footage keywords (theme/concept, not literal source words — see
CLAUDE.md's footage library section) so Stage 2 can cut to different,
matching footage per segment instead of looping one background for the
whole video.

Two seed types, one output shape — this is what lets Stage 2 (TTS,
captions, footage matching, video assembly) stay completely generic
regardless of content format:
- {"type": "quote", "text": ..., "reference": ...}: the quote text is
  fixed; Claude only supplies its keywords plus the analysis segments.
- {"type": "topic", "topic": ...}: no fixed text; Claude generates every
  segment from scratch. What kind of content that is (jokes, a science
  explainer, anything else) lives entirely in the channel's style_prompt
  — this module has no format-specific logic.

Uses the Anthropic API. Requires ANTHROPIC_API_KEY in your environment.
"""

import json

from llm_json import call_for_json

QUOTE_SCHEMA_INSTRUCTIONS = """
Respond with ONLY a JSON object (no prose, no markdown fences) shaped like:
{{
  "quote_keywords": ["theme", "theme", "theme"],
  "segments": [
    {{"text": "...", "keywords": ["theme", "theme", "theme"]}},
    ... exactly {segment_count} entries total ...
  ]
}}

"segments" must have exactly {segment_count} entries: your original
analysis, broken into {segment_count} segments (2-3 sentences each,
~30-35 words each, ~{total_words} words total). This needs to be real,
substantive analysis, not a quick one-liner — the finished video (quote +
reference + this analysis) needs to run at least 30-40 seconds, so thin
content isn't an option. Each segment's "text" is spoken on its own, so
it must read naturally as a standalone chunk, not a fragment.

"quote_keywords" and each segment's "keywords" are 3-5 short, lowercase,
general visual/emotional themes or concepts (e.g. "heaven", "betrayal",
"dawn", "coffee", "SpaceX") used to match stock footage — favor themes
that could apply beyond this one specific passage, not literal words
pulled from the text.
"""

TOPIC_SCHEMA_INSTRUCTIONS = """
Respond with ONLY a JSON object (no prose, no markdown fences) shaped like:
{{
  "segments": [
    {{"text": "...", "keywords": ["theme", "theme", "theme"]}},
    ... exactly {segment_count} entries total ...
  ]
}}

"segments" must have exactly {segment_count} entries, each one spoken on
its own so it must read naturally as a standalone chunk, not a fragment.

Each segment's "keywords" are 3-5 short, lowercase, general visual themes
or concepts (e.g. "coffee", "monday morning", "gym", "SpaceX") used to
match stock footage — favor concepts a stock clip could actually show,
not abstract punchline logic.
"""


def generate_script(seed: dict, style_prompt: str, pacing: dict, model="claude-sonnet-4-6") -> dict:
    """
    seed: {"type": "quote", "text":, "reference":} or {"type": "topic", "topic":}
    pacing: the channel's pacing config (config/channels.py) — only
    "segment_count" is used here.
    Returns: {"citation": str | None, "segments": [{"text":, "keywords":}, ...]}
    "citation" is spoken right after segment 0 if present (e.g. a Bible
    reference) — generic optional metadata, not a quote-specific concept.
    """
    segment_count = pacing["segment_count"]

    if seed["type"] == "quote":
        instructions = QUOTE_SCHEMA_INSTRUCTIONS.format(
            segment_count=segment_count,
            total_words=segment_count * 33,
        )
        user_msg = (
            f'Quote: "{seed["text"]}"\n'
            f'Reference: {seed["reference"]}\n\n'
            f"{instructions}"
        )
        data = call_for_json(system=style_prompt, user_msg=user_msg, model=model, max_tokens=700)

        segments = [{"text": seed["text"], "keywords": data["quote_keywords"]}]
        for seg in data["segments"]:
            segments.append({"text": " ".join(seg["text"].split()), "keywords": seg["keywords"]})

        return {"citation": seed["reference"], "segments": segments}

    elif seed["type"] == "topic":
        instructions = TOPIC_SCHEMA_INSTRUCTIONS.format(segment_count=segment_count)
        user_msg = f'Topic: "{seed["topic"]}"\n\n{instructions}'
        data = call_for_json(system=style_prompt, user_msg=user_msg, model=model, max_tokens=700)

        segments = [
            {"text": " ".join(seg["text"].split()), "keywords": seg["keywords"]}
            for seg in data["segments"]
        ]
        return {"citation": None, "segments": segments}

    else:
        raise ValueError(f"Unknown seed type: {seed['type']!r}")


if __name__ == "__main__":
    from quote_source import get_quote
    from config.channels import CHANNELS

    cfg = CHANNELS["bible_daily"]
    q = get_quote("bible")
    seed = {"type": "quote", "text": q["text"], "reference": q["reference"]}
    s = generate_script(seed, cfg["style_prompt"], cfg["pacing"])
    print(json.dumps(s, indent=2))
