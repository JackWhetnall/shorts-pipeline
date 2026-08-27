"""
Turns a raw quote into a short spoken script: the quote itself, read out,
followed by a brief reflection generated per the channel's style prompt.

Uses the Anthropic API. Requires ANTHROPIC_API_KEY in your environment.
"""

import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def generate_script(quote: dict, style_prompt: str, model="claude-sonnet-4-6") -> dict:
    """
    quote: {"text": ..., "reference": ...}
    Returns the script as separate spoken parts — {"quote", "reference",
    "reflection"} — each flattened to a single line, so the TTS step can
    space them out with pauses instead of reading one run-on paragraph.
    """
    user_msg = (
        f'Quote: "{quote["text"]}"\n'
        f'Reference: {quote["reference"]}\n\n'
        "Write only the reflection text itself — no preamble, no labels, "
        "no quotation marks around it."
    )

    response = client.messages.create(
        model=model,
        max_tokens=200,
        system=style_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    reflection = " ".join(response.content[0].text.strip().split())

    return {
        "quote": quote["text"],
        "reference": quote["reference"],
        "reflection": reflection,
    }


if __name__ == "__main__":
    from quote_source import get_quote
    from config.channels import CHANNELS

    q = get_quote("bible")
    s = generate_script(q, CHANNELS["bible_daily"]["style_prompt"])
    print(s)
