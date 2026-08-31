"""
Thin persistence wrapper around config/channels.json for the web app.
config.channels.load_channels() re-reads and re-merges the JSON on every
call (no caching), which is exactly what a GET-right-after-POST flow
needs — see config/channels.py's own docstring.

Settings saves and channel creation both write the COMPLETE field set for
an entry (pacing, style, avoid_imagery included, not just overrides) —
a deliberate simplification over sparse-diff writes. Since
config.channels._channel() merges defaults with whatever's provided,
writing every field explicitly is a no-op through that merge (identical
resulting CHANNELS values), it just means channels.json stops being
minimal for entries edited through the GUI. That's an acceptable
trade-off for a settings editor that doesn't need to reconstruct "what
did the user actually override" from a merged dict.
"""

import json

import config.channels as channels_module

VALID_CONTENT_MODES = ("static_corpus", "topic")


def get_channels() -> dict:
    """Fresh CHANNELS dict, reflecting any save made earlier in this
    process (or by hand-editing channels.json) — never the possibly-stale
    module-level config.channels.CHANNELS."""
    return channels_module.load_channels()


def get_raw_entries() -> dict:
    """The raw channels.json content, before DEFAULT_* merging — used only
    to check whether a channel key already exists without needing the
    fully-merged form."""
    with open(channels_module.CHANNELS_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_channel(key: str, entry: dict):
    """Writes (creates or overwrites) one channel's complete entry."""
    raw = get_raw_entries()
    raw[key] = entry
    _write_raw(raw)


def _write_raw(raw: dict):
    with open(channels_module.CHANNELS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
