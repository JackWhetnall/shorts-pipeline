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
import re
import shutil
from pathlib import Path

import config.channels as channels_module

VALID_CONTENT_MODES = ("static_corpus", "topic")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEY_RE = re.compile(r"^[a-z0-9_]+$")


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


def rename_channel(old_key: str, new_key: str) -> dict:
    """Re-keys a channel's config entry and moves everything on disk that's
    keyed directly off the channel key string: channels/<key>/ (logo +
    merch assets, per webapp/logo_gen.py and merch_assets.py, both of which
    build that path from the key at call time — moving the directory is
    the ONLY change they need) and output/<key>/, but only when output_dir
    still follows the default "output/<key>" convention (it's a plain
    editable string field, not derived at runtime — see
    webapp/app.py's _parse_channel_form — so a channel with a customized
    output_dir is left untouched rather than guessing a new path for it).
    Raises ValueError on any validation failure; nothing is written or
    moved unless every check passes first. Returns
    {"new_key", "output_dir_migrated"}."""
    raw = get_raw_entries()
    if old_key not in raw:
        raise ValueError(f'Channel "{old_key}" does not exist.')
    if not new_key or not KEY_RE.match(new_key):
        raise ValueError("New channel key must be lowercase letters, numbers, and underscores only.")
    if new_key == old_key:
        raise ValueError("New key is the same as the current key.")
    if new_key in raw:
        raise ValueError(f'Channel "{new_key}" already exists.')

    new_channels_dir = PROJECT_ROOT / "channels" / new_key
    if new_channels_dir.exists():
        raise ValueError(f'"channels/{new_key}/" already exists on disk.')

    entry = raw[old_key]
    old_output_dir = entry.get("output_dir", "")
    output_dir_migrated = False
    new_output_dir = old_output_dir
    if old_output_dir == f"output/{old_key}":
        new_output_dir = f"output/{new_key}"
        if (PROJECT_ROOT / new_output_dir).exists():
            raise ValueError(f'"{new_output_dir}/" already exists on disk.')
        output_dir_migrated = True

    # Everything validated - now actually move things. Re-key the config
    # first so a failure partway through a disk move still leaves the JSON
    # pointing at whichever directory state is currently real.
    raw[new_key] = raw.pop(old_key)
    if output_dir_migrated:
        raw[new_key]["output_dir"] = new_output_dir
    _write_raw(raw)

    old_channels_dir = PROJECT_ROOT / "channels" / old_key
    if old_channels_dir.exists():
        shutil.move(str(old_channels_dir), str(new_channels_dir))

    if output_dir_migrated:
        old_output_path = PROJECT_ROOT / old_output_dir
        if old_output_path.exists():
            shutil.move(str(old_output_path), str(PROJECT_ROOT / new_output_dir))

    return {"new_key": new_key, "output_dir_migrated": output_dir_migrated}
