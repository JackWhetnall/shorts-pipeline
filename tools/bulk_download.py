"""
Bulk-download stock clips into footage/new_downloads/ for review.

    python tools/bulk_download.py                       # default theme pack
    python tools/bulk_download.py "heaven, storm, dawn" # your own themes
    python tools/bulk_download.py "prayer" --count 10 --source pexels

Uses Pexels' and Pixabay's official free search APIs. Register a key at
pexels.com/api and/or pixabay.com/api/docs; only the key for the source
you actually use is required.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logging_setup import configure, get_logger      # noqa: E402
from core.paths import NEW_DOWNLOADS_DIR, slugify         # noqa: E402
from pipeline.footage import sources                      # noqa: E402

log = get_logger(__name__)

# A generic starter pack of cinematic themes that pay off across most
# reflective formats. Content-neutral on purpose: the library is shared
# by every channel.
DEFAULT_QUERIES = [
    "sky clouds", "sunrise", "sunset", "candle flame", "rain window",
    "forest path", "ocean waves", "mountains", "fire embers", "snow falling",
    "night stars", "old books", "city lights night", "storm clouds",
    "light rays", "autumn leaves", "road path", "hands together",
    "quiet room", "open window",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queries", nargs="?", default=None,
                        help="Comma-separated search terms. Omit for a default pack.")
    parser.add_argument("--count", type=int, default=5, help="Clips per query per source.")
    parser.add_argument("--source", choices=["pexels", "pixabay", "both"], default="both")
    args = parser.parse_args()
    configure()

    if not sources.any_key_configured():
        print("Set PEXELS_API_KEY and/or PIXABAY_API_KEY first. Free keys at "
              "pexels.com/api and pixabay.com/api/docs.")
        return 1

    NEW_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    queries = ([q.strip() for q in args.queries.split(",") if q.strip()]
               if args.queries else DEFAULT_QUERIES)
    searchers = (sources.SEARCHERS if args.source == "both"
                 else {args.source: sources.SEARCHERS[args.source]})

    total = 0
    for query in queries:
        for name, searcher in searchers.items():
            log.info(f'Searching {name} for "{query}"...')
            try:
                hits = searcher(query, args.count)
            except Exception as exc:                       # noqa: BLE001
                log.warning(f"  {name} search failed: {exc}")
                continue
            for i, hit in enumerate(hits, 1):
                dest = NEW_DOWNLOADS_DIR / f"{slugify(query, 'clip')}_{name}_{i}.mp4"
                if dest.exists():
                    continue
                try:
                    sources.download(hit.url, dest)
                    total += 1
                    log.info(f"  downloaded {dest.name}")
                except Exception as exc:                   # noqa: BLE001
                    log.warning(f"  {dest.name} failed: {exc}")

    print(f"\n{total} clip(s) in footage/new_downloads/.")
    print("Next: python tools/review_downloads.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
