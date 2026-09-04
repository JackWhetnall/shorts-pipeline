"""
Per-channel brand assets: logos and merch product photos.

These live under channels/<key>/, outside output/ (finished videos) and
outside footage/ (stock video), because they're neither. Both paths are
derived from the channel key at call time, which is what lets a channel
rename move one directory and need no code change.

This module used to import werkzeug for filename sanitising — a web
framework dependency in a module that exists at the project root
specifically so the renderer could use it without web dependencies. The
sanitiser here is a dozen lines and removes that contradiction; the web
layer converts its uploads to bytes and calls in.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.errors import PipelineError
from core.paths import channel_logo_dir, channel_merch_dir

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    """A filename that can't traverse directories or hide itself.

    Path separators, "..", and leading dots all go. Returns "" for
    anything with nothing usable left, which callers treat as a rejection
    rather than inventing a name.
    """
    name = Path(name or "").name              # drops any directory part
    name = _UNSAFE.sub("_", name).strip("._")
    return name


# --- merch photos -----------------------------------------------------

def list_merch_photos(channel_key: str) -> list:
    directory = channel_merch_dir(channel_key)
    if not directory.exists():
        return []
    return sorted(p for p in directory.iterdir()
                  if p.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS)


def save_merch_photo(channel_key: str, filename: str, data: bytes) -> Path:
    """Raises PipelineError with a message naming the file and the
    accepted formats — the previous version swallowed this silently, so
    an unsupported upload just quietly didn't appear."""
    safe = safe_filename(filename)
    extension = Path(safe).suffix.lower()
    if not safe or extension not in ALLOWED_IMAGE_EXTENSIONS:
        accepted = ", ".join(sorted(e.lstrip(".").upper() for e in ALLOWED_IMAGE_EXTENSIONS))
        raise PipelineError(
            f"unsupported merch upload {filename!r}",
            user_message=f'"{filename}" wasn\'t added — product photos need to be {accepted}.',
        )

    directory = channel_merch_dir(channel_key)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / safe
    stem = Path(safe).stem
    i = 2
    while dest.exists():
        dest = directory / f"{stem}_{i}{extension}"
        i += 1
    dest.write_bytes(data)
    return dest


def delete_merch_photo(channel_key: str, filename: str) -> None:
    safe = safe_filename(filename)
    if not safe:
        raise PipelineError("invalid filename", user_message="That file name isn't valid.")
    (channel_merch_dir(channel_key) / safe).unlink(missing_ok=True)


# --- logos ------------------------------------------------------------

def logo_path(channel_key: str) -> Path:
    return channel_logo_dir(channel_key) / "logo.png"


def has_logo(channel_key: str) -> bool:
    return logo_path(channel_key).exists()


def candidates_dir(channel_key: str) -> Path:
    return channel_logo_dir(channel_key) / "candidates"


def list_candidates(channel_key: str) -> list:
    directory = candidates_dir(channel_key)
    return sorted(directory.glob("*.png")) if directory.exists() else []
