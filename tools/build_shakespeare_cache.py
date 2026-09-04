"""
Build the local Shakespeare quote cache. Run once.

    python tools/build_shakespeare_cache.py

Downloads a few Project Gutenberg texts and reduces them to quotable
single sentences, so generation itself needs no network call.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logging_setup import configure          # noqa: E402
from pipeline.quote_source import build_shakespeare_cache   # noqa: E402

if __name__ == "__main__":
    configure()
    count = build_shakespeare_cache()
    print(f"Done — {count} lines cached.")
