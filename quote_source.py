"""
Pulls a random quote for a given source ("bible" or "shakespeare").

Bible: uses bible-api.com's random-verse endpoint (free, no key, KJV by
default = public domain).

Shakespeare: works off a local cache of plain-text plays/sonnets (Project
Gutenberg, public domain). Run build_shakespeare_cache() once to populate
cache/shakespeare_lines.txt, then quotes are pulled from that file with no
network call needed at generation time.
"""

import random
import re
import requests
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
SHAKESPEARE_CACHE = CACHE_DIR / "shakespeare_lines.txt"

# A handful of Gutenberg plain-text works. Add more IDs as you like —
# full catalog at https://www.gutenberg.org
GUTENBERG_SHAKESPEARE_URLS = [
    "https://www.gutenberg.org/files/1524/1524-0.txt",   # Hamlet
    "https://www.gutenberg.org/files/1533/1533-0.txt",   # Macbeth
    "https://www.gutenberg.org/files/1112/1112-0.txt",   # Romeo and Juliet
    "https://www.gutenberg.org/files/1041/1041-0.txt",   # Sonnets
]


def get_bible_quote() -> dict:
    """Fetch one random KJV verse. Returns {text, reference}."""
    resp = requests.get("https://bible-api.com/data/kjv/random", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    verse = data["random_verse"]
    reference = f"{verse['book']} {verse['chapter']}:{verse['verse']}"
    text = " ".join(verse["text"].split())
    return {"text": text, "reference": reference}


def build_shakespeare_cache(min_words=8, max_words=30):
    """
    One-time (or occasional) job: downloads a few Gutenberg texts, strips
    them down to quotable single lines/sentences, and writes them to a
    local cache file. Run this offline — don't call it per-video.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    lines_out = []

    for url in GUTENBERG_SHAKESPEARE_URLS:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        raw = resp.text

        # crude cleanup: drop Gutenberg header/footer boilerplate
        start = raw.find("*** START")
        end = raw.find("*** END")
        body = raw[start:end] if start != -1 and end != -1 else raw

        # split into candidate sentences, keep ones of sensible length,
        # skip stage directions / ALL CAPS speaker names
        for sentence in re.split(r'(?<=[.!?])\s+', body):
            clean = " ".join(sentence.split())
            word_count = len(clean.split())
            if (
                min_words <= word_count <= max_words
                and not clean.isupper()
                and not clean.startswith("[")
            ):
                lines_out.append(clean)

    with open(SHAKESPEARE_CACHE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_out))

    print(f"Cached {len(lines_out)} Shakespeare lines to {SHAKESPEARE_CACHE}")


def get_shakespeare_quote() -> dict:
    """Pull one random line from the local cache (build it first, see above)."""
    if not SHAKESPEARE_CACHE.exists():
        raise FileNotFoundError(
            "Shakespeare cache not found. Run build_shakespeare_cache() once first."
        )
    lines = SHAKESPEARE_CACHE.read_text(encoding="utf-8").splitlines()
    text = " ".join(random.choice(lines).split())
    return {"text": text, "reference": "Shakespeare"}


SOURCES = {
    "bible": get_bible_quote,
    "shakespeare": get_shakespeare_quote,
}


def get_quote(source_name: str) -> dict:
    return SOURCES[source_name]()


if __name__ == "__main__":
    # quick manual test
    print(get_quote("bible"))
