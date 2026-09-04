"""
Channel lifecycle: create, rename, reorder, archive, delete.

Ordinary field edits go through `core.channels.save_channel`. This module
is for the operations that move things on disk or destroy them, which
need care that a settings save doesn't.

Every one of them validates completely before writing anything, so a
rejected operation never leaves half-moved directories behind.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from core.channels import (
    ChannelConfig, channel_to_sparse_dict, load_channels, read_raw, write_raw,
)
from core.errors import ConfigError
from core.logging_setup import get_logger
from core.paths import (
    CHANNELS_DIR, DELETED_CHANNELS_DIR, PROJECT_ROOT, slugify,
)

log = get_logger(__name__)


def create_channel(channel: ChannelConfig) -> ChannelConfig:
    entries = read_raw()
    if channel.key in entries:
        raise ConfigError(
            f"duplicate key {channel.key}",
            user_message=f'A channel called "{channel.key}" already exists.',
        )
    channel.validate()
    entries[channel.key] = channel_to_sparse_dict(channel)
    write_raw(entries)
    (PROJECT_ROOT / channel.output_dir).mkdir(parents=True, exist_ok=True)
    return channel


def set_archived(key: str, archived: bool) -> None:
    channels = load_channels(validate=False)
    if key not in channels:
        raise ConfigError(f"no channel {key}", user_message="That channel doesn't exist.")
    channel = channels[key]
    channel.archived = archived
    entries = read_raw()
    entries[key] = channel_to_sparse_dict(channel)
    write_raw(entries)


def toggle_checklist_override(key: str, item_id: str) -> None:
    channels = load_channels(validate=False)
    if key not in channels:
        raise ConfigError(f"no channel {key}", user_message="That channel doesn't exist.")
    channel = channels[key]
    overrides = set(channel.manual_checklist_overrides)
    overrides.symmetric_difference_update({item_id})
    channel.manual_checklist_overrides = sorted(overrides)
    entries = read_raw()
    entries[key] = channel_to_sparse_dict(channel)
    write_raw(entries)


def reorder_channels(ordered_keys: list) -> None:
    """Put `ordered_keys` first, in that order, leaving every other key's
    relative position alone.

    Key order in the file is display order in the UI. Unknown keys are
    ignored rather than raising: this is only ever called with keys read
    from the page's own DOM, so a mismatch means the page was stale, not
    that something is wrong.
    """
    entries = read_raw()
    rest = [k for k in entries if k not in ordered_keys]
    reordered = {k: entries[k] for k in ordered_keys if k in entries}
    reordered.update({k: entries[k] for k in rest})
    write_raw(reordered)


def rename_channel(old_key: str, new_display_name: str) -> dict:
    """Rename by DISPLAY NAME; the key is derived from it.

    The first version of this re-keyed the config and moved directories
    but left `channel_display_name` untouched — a real channel was
    renamed and kept showing its old name everywhere despite the URL
    changing. Making the display name the input and deriving the key from
    it, never the reverse, is what fixed that.

    A purely cosmetic edit that derives the same key (fixing
    capitalisation, say) is treated as a display-name change only: no
    re-keying, no directory moves, no collision check against itself.
    """
    new_display_name = (new_display_name or "").strip()
    if not new_display_name:
        raise ConfigError("empty name", user_message="Enter a channel name.")

    entries = read_raw()
    if old_key not in entries:
        raise ConfigError(f"no channel {old_key}",
                          user_message=f'Channel "{old_key}" doesn\'t exist.')

    new_key = slugify(new_display_name)
    if not new_key:
        raise ConfigError("unusable name",
                          user_message="That name needs at least one letter or number.")

    entry = entries[old_key]

    if new_key == old_key:
        entry["channel_display_name"] = new_display_name
        write_raw(entries)
        return {"new_key": old_key, "output_dir_migrated": False}

    if new_key in entries:
        raise ConfigError(
            f"key collision {new_key}",
            user_message=(f'A channel already exists with the key "{new_key}" '
                          f"(derived from that name). Try a more distinct name."),
        )

    new_assets_dir = CHANNELS_DIR / new_key
    if new_assets_dir.exists():
        raise ConfigError("assets dir exists",
                          user_message=f'"channels/{new_key}/" already exists on disk.')

    old_output_dir = entry.get("output_dir") or f"output/{old_key}"
    migrate_output = old_output_dir == f"output/{old_key}"
    new_output_dir = f"output/{new_key}" if migrate_output else old_output_dir
    if migrate_output and (PROJECT_ROOT / new_output_dir).exists():
        raise ConfigError("output dir exists",
                          user_message=f'"{new_output_dir}/" already exists on disk.')

    # Everything above is validation. Nothing has been written yet.
    entry["channel_display_name"] = new_display_name
    if migrate_output:
        entry["output_dir"] = new_output_dir
    elif "output_dir" not in entry:
        # A customised output_dir is left exactly where it is rather than
        # guessing a new home for it.
        entry["output_dir"] = old_output_dir

    # Rebuilt in place, not popped and reinserted: a pop-then-insert
    # always re-appends at the END of a Python dict, and key order here
    # IS the home page's display order — which silently sent every
    # renamed channel to the bottom of the list.
    write_raw({(new_key if k == old_key else k): v for k, v in entries.items()})

    old_assets_dir = CHANNELS_DIR / old_key
    if old_assets_dir.exists():
        # One move covers logo/ and merch/ together: both paths are
        # derived from the key at call time, so no code changes.
        shutil.move(str(old_assets_dir), str(new_assets_dir))

    if migrate_output:
        old_output = PROJECT_ROOT / old_output_dir
        if old_output.exists():
            shutil.move(str(old_output), str(PROJECT_ROOT / new_output_dir))

    log.info(f"Renamed channel {old_key} -> {new_key}")
    return {"new_key": new_key, "output_dir_migrated": migrate_output}


def delete_channel(key: str) -> Path:
    """Delete a channel and everything it owns, after zipping it all up.

    Real API money went into those videos and that logo, so a misclick
    must not be able to destroy them with no way back. The backup is
    written and closed BEFORE anything is removed.
    """
    entries = read_raw()
    if key not in entries:
        raise ConfigError(f"no channel {key}", user_message="That channel doesn't exist.")
    entry = entries[key]

    output_dir = PROJECT_ROOT / (entry.get("output_dir") or f"output/{key}")
    assets_dir = CHANNELS_DIR / key

    DELETED_CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zip_path = DELETED_CHANNELS_DIR / f"{key}_{stamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("channel.json", json.dumps(entry, indent=2))
        for base, prefix in ((output_dir, "output"), (assets_dir, "channels")):
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if path.is_file():
                    archive.write(path, arcname=f"{prefix}/{path.relative_to(base)}")

    del entries[key]
    write_raw(entries)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    if assets_dir.exists():
        shutil.rmtree(assets_dir)

    log.info(f"Deleted channel {key}; backup at {zip_path}")
    return zip_path
