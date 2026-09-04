"""
Every filesystem location and path-derivation rule in the project, in one
place.

Before this module existed, PROJECT_ROOT was independently recomputed in
six modules (each with its own number of .parent hops), the 1080x1920
frame size was declared in two, and four different slugify()
implementations existed with subtly different semantics — main.py's
appended a "video" fallback, channel_store's stripped whitespace first,
footage's fell back to "clip", bulk_download's had no fallback at all.
Those are the kind of duplications that stay harmless right up until two
of them disagree.

safe_join() also lives here because path-traversal checking was written
four slightly different ways across the web routes ("is root in
target.parents" misses the direct-child case; one route special-cased it,
three didn't). One implementation, used everywhere, is both shorter and
correct.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Generated / downloaded content. All gitignored — see .gitignore.
OUTPUT_DIR = PROJECT_ROOT / "output"
FOOTAGE_DIR = PROJECT_ROOT / "footage"
CHANNELS_DIR = PROJECT_ROOT / "channels"
CACHE_DIR = PROJECT_ROOT / "cache"
JOB_STATE_DIR = PROJECT_ROOT / "job_state"
DELETED_CHANNELS_DIR = PROJECT_ROOT / "deleted_channels"

# footage/ is a DATA directory now — the CLI tools that maintain it live
# in tools/, and the library logic in pipeline/footage/. A directory
# holding 4 GB of video shouldn't also be a Python package.
LIBRARY_DIR = FOOTAGE_DIR / "library"
LIBRARY_DB_PATH = FOOTAGE_DIR / "library.db"
MANIFEST_PATH = FOOTAGE_DIR / "manifest.json"          # legacy; import source only
NEW_DOWNLOADS_DIR = FOOTAGE_DIR / "new_downloads"
NORMALIZED_DIR = FOOTAGE_DIR / "normalized"
OLD_DOWNLOADS_DIR = FOOTAGE_DIR / "old_downloads"

CHANNELS_JSON_PATH = PROJECT_ROOT / "config" / "channels.json"
SCRIPT_HISTORY_PATH = PROJECT_ROOT / "config" / "script_history.json"
COST_LOG_PATH = PROJECT_ROOT / "config" / "cost_log.jsonl"
SCHEDULE_PATH = PROJECT_ROOT / "config" / "schedule.json"
# Tombstones for discarded videos whose files have been deleted. The
# statistics have to outlive the mp4 — see core.gallery.purge.
DISCARD_HISTORY_PATH = PROJECT_ROOT / "config" / "discard_history.jsonl"

# The one place the output frame size is defined. Both the renderer and
# the footage normalizer have to agree on this or clips arrive at the
# wrong aspect ratio.
FRAME_WIDTH = 1080
FRAME_HEIGHT = 1920


def channel_logo_dir(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "logo"


def channel_merch_dir(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "merch"


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, fallback: str = "") -> str:
    """Lowercase; every run of non-alphanumerics collapses to a single
    underscore; leading/trailing underscores stripped.

    "Minute Pastor!" -> "minute_pastor", "John 3:16" -> "john_3_16".

    Returns `fallback` when the input has no alphanumerics at all. The
    result always matches ^[a-z0-9_]+$ (or is the fallback), so anything
    non-empty this returns is a valid channel key and a valid filename
    stem by construction.
    """
    return _SLUG_RE.sub("_", (text or "").strip().lower()).strip("_") or fallback


class PathTraversalError(ValueError):
    """A user-supplied path resolved outside the directory it must stay in."""


def safe_join(root: Path, *parts: str) -> Path:
    """Resolve `parts` beneath `root`, refusing anything that escapes it.

    Unlike the "root not in target.parents" idiom this replaces, a path
    that IS root (rather than a descendant of it) is handled explicitly
    rather than by accident: joining nothing returns root, which callers
    serving a directory listing legitimately want, while "../secrets"
    raises whether it lands one level up or ten.
    """
    root = Path(root).resolve()
    target = root.joinpath(*parts).resolve()
    if target != root and root not in target.parents:
        raise PathTraversalError(f"{target} is outside {root}")
    return target


def unique_stem(directory: Path, base: str) -> str:
    """`base`, or base_2 / base_3 / ... if files with that stem already
    exist in `directory` — so a repeated verse or topic on the same day
    lands beside its predecessor instead of overwriting it."""
    if not any(directory.glob(f"{base}.*")):
        return base
    i = 2
    while any(directory.glob(f"{base}_{i}.*")):
        i += 1
    return f"{base}_{i}"


def relative_to_output(path: Path) -> str:
    """The forward-slash relative path the web routes use to address one
    video (`minute_pastor/2026-09-03/john_3_16.mp4`). Always forward
    slashes — these end up in URLs, and this project runs on Windows."""
    return str(Path(path).resolve().relative_to(OUTPUT_DIR)).replace("\\", "/")
