"""
Fetching source text for static-corpus channels.

Each source is a callable returning {"text", "reference"}. Adding one is
a function plus a SOURCES entry — no other module knows what a source is
beyond that shape, which is what lets a new corpus channel be added
without touching the pipeline.
"""

from __future__ import annotations

import random
import re

import requests

from core.errors import ConfigError, ExternalServiceError, PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR

log = get_logger(__name__)

SHAKESPEARE_CACHE = CACHE_DIR / "shakespeare_lines.txt"

BIBLE_RANDOM_URL = "https://bible-api.com/data/kjv/random"

# Plain-text works from Project Gutenberg (public domain).
GUTENBERG_SHAKESPEARE_URLS = [
    "https://www.gutenberg.org/files/1524/1524-0.txt",   # Hamlet
    "https://www.gutenberg.org/files/1533/1533-0.txt",   # Macbeth
    "https://www.gutenberg.org/files/1112/1112-0.txt",   # Romeo and Juliet
    "https://www.gutenberg.org/files/1041/1041-0.txt",   # Sonnets
]


def get_bible_quote() -> dict:
    """One random KJV verse. KJV is public domain, which is why it's the
    default translation rather than a licensing decision to revisit."""
    try:
        response = requests.get(BIBLE_RANDOM_URL, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ExternalServiceError(
            "The Bible verse service (bible-api.com)", str(exc),
            user_message=("Couldn't fetch a verse — bible-api.com didn't respond. "
                          "It's a free public service; trying again usually works."),
        ) from exc

    verse = response.json()["random_verse"]
    return {
        "text": " ".join(verse["text"].split()),
        "reference": f"{verse['book']} {verse['chapter']}:{verse['verse']}",
    }


def build_shakespeare_cache(min_words: int = 8, max_words: int = 30) -> int:
    """Download a few Gutenberg texts and reduce them to quotable single
    sentences. Run once, offline — never per video."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    lines = []

    for url in GUTENBERG_SHAKESPEARE_URLS:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        raw = response.text

        start = raw.find("*** START")
        end = raw.find("*** END")
        body = raw[start:end] if start != -1 and end != -1 else raw

        for sentence in re.split(r"(?<=[.!?])\s+", body):
            clean = " ".join(sentence.split())
            if (min_words <= len(clean.split()) <= max_words
                    and not clean.isupper()          # speaker names
                    and not clean.startswith("[")):  # stage directions
                lines.append(clean)

    SHAKESPEARE_CACHE.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Cached {len(lines)} Shakespeare lines to {SHAKESPEARE_CACHE}")
    return len(lines)


def get_shakespeare_quote() -> dict:
    if not SHAKESPEARE_CACHE.exists():
        raise PipelineError(
            "Shakespeare cache missing",
            user_message=("The Shakespeare quote cache hasn't been built yet. Run "
                          "`python tools/build_shakespeare_cache.py` once to create it."),
        )
    lines = SHAKESPEARE_CACHE.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise PipelineError(
            "Shakespeare cache empty",
            user_message="The Shakespeare quote cache is empty. Rebuild it.",
        )
    return {"text": " ".join(random.choice(lines).split()), "reference": "Shakespeare"}


SOURCES = {
    "bible": get_bible_quote,
    "shakespeare": get_shakespeare_quote,
}


def get_quote(source_name: str) -> dict:
    if source_name not in SOURCES:
        raise ConfigError(
            f"unknown source {source_name!r}",
            user_message=(f'"{source_name}" isn\'t a source this pipeline knows. '
                          f'Available: {", ".join(sorted(SOURCES))}.'),
        )
    return SOURCES[source_name]()
