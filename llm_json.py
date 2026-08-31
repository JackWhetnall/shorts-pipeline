"""
Shared Anthropic client plus a helper for calling the model and parsing
its reply as JSON. Used by script_gen.py (script generation) and
footage_library.py (footage matching) — both need the same "ask for JSON,
parse it, retry once on failure" pattern.

Some models reject assistant-turn prefill (the conversation must end on a
user message — confirmed with claude-sonnet-4-6), so instead of forcing
JSON that way, the reply's {...} block is extracted with a regex —
tolerates stray prose or markdown fences around it.
"""

import json
import os
import re
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def call_for_json(system: str, user_msg: str, model: str, max_tokens: int = 500, retries: int = 1) -> dict:
    last_error = None
    for _ in range(retries + 1):
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            return json.loads(match.group(0) if match else raw)
        except json.JSONDecodeError as e:
            last_error = e
    raise ValueError(f"Model didn't return valid JSON after {retries + 1} attempts: {last_error}")
