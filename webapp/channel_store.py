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


def slugify(text: str) -> str:
    """Lowercase, non-alphanumeric runs collapsed to a single underscore,
    leading/trailing underscores stripped — e.g. "Minute Pastor!" ->
    "minute_pastor". Matches KEY_RE by construction, so anything this
    returns (if non-empty) is already a valid channel key."""
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def rename_channel(old_key: str, new_display_name: str) -> dict:
    """Renames a channel by its new DISPLAY NAME, not a raw key — the key
    (and therefore every on-disk directory keyed off it) is derived by
    slugifying that name, so "Minute Pastor" becomes the key
    "minute_pastor" automatically instead of asking the user to separately
    type both a human name and a URL-safe key. Updates
    channel_display_name AND re-keys the config entry, then moves
    everything on disk that's keyed directly off the channel key string:
    channels/<key>/ (logo + merch assets, per webapp/logo_gen.py and
    merch_assets.py, both of which build that path from the key at call
    time — moving the directory is the ONLY change they need) and
    output/<key>/, but only when output_dir still follows the default
    "output/<key>" convention (it's a plain editable string field, not
    derived at runtime — see webapp/app.py's _parse_channel_form — so a
    channel with a customized output_dir is left untouched rather than
    guessing a new path for it).

    If the derived key is unchanged (e.g. only capitalization/punctuation
    changed in the display name), this is just a display-name update — no
    re-keying or directory moves, and no collision check against the
    channel's own current key.

    Raises ValueError on any validation failure; nothing is written or
    moved unless every check passes first. Returns
    {"new_key", "output_dir_migrated"}."""
    new_display_name = (new_display_name or "").strip()
    if not new_display_name:
        raise ValueError("Enter a channel name.")

    raw = get_raw_entries()
    if old_key not in raw:
        raise ValueError(f'Channel "{old_key}" does not exist.')

    new_key = slugify(new_display_name)
    if not new_key:
        raise ValueError("That name needs at least one letter or number.")

    entry = raw[old_key]

    if new_key == old_key:
        entry["channel_display_name"] = new_display_name
        _write_raw(raw)
        return {"new_key": old_key, "output_dir_migrated": False}

    if new_key in raw:
        raise ValueError(f'A channel already exists with the key "{new_key}" '
                          f'(derived from this name) — try a more distinct name.')

    new_channels_dir = PROJECT_ROOT / "channels" / new_key
    if new_channels_dir.exists():
        raise ValueError(f'"channels/{new_key}/" already exists on disk.')

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
    entry["channel_display_name"] = new_display_name
    if output_dir_migrated:
        entry["output_dir"] = new_output_dir
    # A plain raw[new_key] = raw.pop(old_key) would always re-append at the
    # end of the dict (Python dicts append on re-insertion after a pop),
    # which silently moved a renamed channel to the end of the home page's
    # list — channels.json's key order IS the display order (see
    # reorder_channels below), so rebuilding the dict in place instead of
    # popping+reinserting is what keeps a renamed channel exactly where it
    # was.
    raw = {(new_key if k == old_key else k): v for k, v in raw.items()}
    _write_raw(raw)

    old_channels_dir = PROJECT_ROOT / "channels" / old_key
    if old_channels_dir.exists():
        shutil.move(str(old_channels_dir), str(new_channels_dir))

    if output_dir_migrated:
        old_output_path = PROJECT_ROOT / old_output_dir
        if old_output_path.exists():
            shutil.move(str(old_output_path), str(PROJECT_ROOT / new_output_dir))

    return {"new_key": new_key, "output_dir_migrated": output_dir_migrated}


def reorder_channels(ordered_keys: list):
    """Rewrites channels.json so `ordered_keys` appear first, in the exact
    order given, followed by any remaining existing keys in their current
    relative order. Unknown keys in `ordered_keys` (already deleted, typo'd,
    etc.) are silently ignored rather than erroring — this is only ever
    called with keys read back from the page's own DOM a moment earlier, so
    a mismatch means the page was already stale, not a real error to
    surface. Since display always groups channels by `status` before
    rendering (see webapp/app.py's index()), the interleaving between
    differently-statused keys in the raw file is never visible — only
    relative order WITHIN one status group is — so reordering just the
    keys from one on-screen section is sufficient; there's no need to also
    know or preserve where OTHER sections' keys sit relative to these."""
    raw = get_raw_entries()
    remaining_keys = [k for k in raw if k not in ordered_keys]
    new_raw = {k: raw[k] for k in ordered_keys if k in raw}
    new_raw.update({k: raw[k] for k in remaining_keys})
    _write_raw(new_raw)
