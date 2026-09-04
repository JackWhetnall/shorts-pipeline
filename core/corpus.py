"""
A channel's own list of source text.

## Why this exists

`quote_source.SOURCES` was a hardcoded dict of two Python functions,
`bible` and `shakespeare`. Every other answer to "I want a channel that
reads quotes about X" required writing code, which meant the answer in
practice was no.

The two built-ins are there because each needs real work — the Bible one
calls an API per video, the Shakespeare one reduces Gutenberg texts to
quotable sentences offline. Neither generalises. What generalises is
letting you supply the text.

## The format

One entry per line, in a plain text file you can edit in anything:

    The unexamined life is not worth living. — Socrates
    Nothing is at last sacred but the integrity of your own mind. | Emerson
    A quote with no attribution at all

Split on an em dash, an en dash, ` - ` or ` | `, last occurrence wins so
a dash inside the quote itself is safe. Attribution is optional; without
one the reference falls back to the channel name, because the reference
is what the video's filename is built from and "untitled" filenames
defeat the point of readable ones.

Blank lines and lines starting `#` are ignored, so the file can carry
comments and be organised in blocks.

## Licensing is yours

This mode reads the text **verbatim** in the video. The two built-in
sources are public domain, which is why they are the built-ins. Anything
pasted here is the channel owner's responsibility, the same way a footage
clip added by hand is — see `manage_library.py set-license`. The UI says
so at the point of pasting rather than in documentation nobody reads.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from core.errors import ConfigError
from core.logging_setup import get_logger
from core.paths import PROJECT_ROOT, safe_join

log = get_logger(__name__)

CORPORA_DIR = PROJECT_ROOT / "config" / "corpora"

# Last match wins, so "Well-being — Aristotle" splits at the em dash and
# not at the hyphen inside the quote.
_SPLIT = re.compile(r"\s+[—–]\s+|\s+\|\s+|\s+-\s+")

# Long enough to be worth a video, short enough to read in one.
MIN_WORDS = 3
MAX_WORDS = 60


def path_for(channel_key: str) -> Path:
    return safe_join(CORPORA_DIR, f"{channel_key}.txt")


def exists(channel_key: str) -> bool:
    try:
        return path_for(channel_key).exists()
    except Exception:  # noqa: BLE001 - a bad key is simply "no corpus"
        return False


def raw_text(channel_key: str) -> str:
    """The file as typed, for putting back in the edit box."""
    path = path_for(channel_key)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def parse(text: str) -> list:
    """Lines to {text, reference}. Never raises; bad lines are skipped."""
    entries = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = _SPLIT.split(line)
        if len(parts) > 1:
            # Cut at the LAST separator so a dash inside the quote itself
            # ("Well-being is the goal - Aristotle") stays in the quote.
            reference = parts[-1].strip()
            quote = line[:line.rfind(parts[-1])].rstrip(" —–|-").strip()
        else:
            quote, reference = line, ""
        if len(quote.split()) < MIN_WORDS:
            continue
        entries.append({"text": quote, "reference": reference})
    return entries


def load(channel_key: str) -> list:
    return parse(raw_text(channel_key))


def save(channel_key: str, text: str) -> dict:
    """Write the list and report what was understood.

    Returns counts rather than raising on unusable lines: someone pasting
    two hundred quotes wants to be told "eleven lines were too short to
    use", not to have the whole paste rejected.
    """
    entries = parse(text)
    total_lines = sum(1 for line in (text or "").splitlines()
                      if line.strip() and not line.strip().startswith("#"))
    path = path_for(channel_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")
    return {
        "kept": len(entries),
        "skipped": total_lines - len(entries),
        "without_attribution": sum(1 for e in entries if not e["reference"]),
        "long": sum(1 for e in entries if len(e["text"].split()) > MAX_WORDS),
    }


def count(channel_key: str) -> int:
    return len(load(channel_key))


def pick(channel_key: str, channel_name: str = "") -> dict:
    """One entry at random, in the shape `quote_source` returns.

    Random rather than sequential to match the built-in sources. Repeats
    are already surfaced: filenames are built from the reference, and the
    create page says how many times a passage has come up before.
    """
    entries = load(channel_key)
    if not entries:
        raise ConfigError(
            f"{channel_key} has an empty quote list",
            user_message=("This channel reads from your own quote list, but the "
                          "list is empty. Add some in its settings."),
        )
    chosen = random.choice(entries)
    return {
        "text": chosen["text"],
        # The filename is built from this, and readable filenames are how
        # a repeat stays visible when browsing the output folder.
        "reference": chosen["reference"] or channel_name or channel_key,
    }


def delete(channel_key: str) -> None:
    path_for(channel_key).unlink(missing_ok=True)
