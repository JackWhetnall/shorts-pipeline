"""
Bulk-downloads stock video clips from Pexels and/or Pixabay's official
search APIs into footage/new_downloads/, ready for review_new_downloads.py
to crop-review and add to the library. Uses their official free APIs
(not scraping) — register your own free key at each site:
    Pexels:  https://www.pexels.com/api/
    Pixabay: https://pixabay.com/api/docs/
then set them as environment variables:
    export PEXELS_API_KEY=your-key-here
    export PIXABAY_API_KEY=your-key-here
(only the key(s) for the source(s) you use are required).

Usage:
    python footage/bulk_download.py                          # default theme pack, both sources
    python footage/bulk_download.py "heaven, storm, dawn"    # your own themes
    python footage/bulk_download.py "prayer" --count 10 --source pexels
"""

import argparse
import os
import re
from pathlib import Path

import requests

FOOTAGE_DIR = Path(__file__).parent
NEW_DOWNLOADS_DIR = FOOTAGE_DIR / "new_downloads"

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY")

# A generic starter pack of cinematic/mood themes that tend to pay off
# across Bible- and Shakespeare-style content — used when you don't pass
# your own query list.
DEFAULT_QUERIES = [
    "sky clouds", "sunrise", "sunset", "candle flame", "rain window",
    "forest path", "ocean waves", "mountains", "fire embers", "snow falling",
    "night stars", "old books", "city lights night", "storm clouds",
    "dove flying", "light rays", "autumn leaves", "road path", "praying hands",
    "castle ruins",
]


def _safe_name(query: str, source: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")
    return f"{slug}_{source}_{index}.mp4"


def _download(url: str, dest: Path):
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)


def search_pexels(query: str, count: int) -> list:
    if not PEXELS_API_KEY:
        print("  [pexels] PEXELS_API_KEY not set, skipping.")
        return []
    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_API_KEY},
        params={"query": query, "per_page": count, "orientation": "portrait"},
        timeout=30,
    )
    resp.raise_for_status()
    urls = []
    for video in resp.json().get("videos", []):
        files = [f for f in video.get("video_files", []) if f.get("link")]
        if not files:
            continue
        best = max(files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
        urls.append(best["link"])
    return urls


def search_pixabay(query: str, count: int) -> list:
    if not PIXABAY_API_KEY:
        print("  [pixabay] PIXABAY_API_KEY not set, skipping.")
        return []
    resp = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": PIXABAY_API_KEY, "q": query, "per_page": max(count, 3)},
        timeout=30,
    )
    resp.raise_for_status()
    urls = []
    for hit in resp.json().get("hits", [])[:count]:
        videos = hit.get("videos", {})
        best = videos.get("large") or videos.get("medium") or videos.get("small")
        if best and best.get("url"):
            urls.append(best["url"])
    return urls


SOURCES = {"pexels": search_pexels, "pixabay": search_pixabay}


def main():
    parser = argparse.ArgumentParser(description="Bulk-download stock footage into footage/new_downloads/")
    parser.add_argument("queries", nargs="?", default=None,
                         help="Comma-separated search terms, e.g. 'heaven, storm, dawn'. "
                              "Omit to use a default theme pack.")
    parser.add_argument("--count", type=int, default=5, help="Clips to fetch per query per source (default 5)")
    parser.add_argument("--source", choices=["pexels", "pixabay", "both"], default="both")
    args = parser.parse_args()

    if not PEXELS_API_KEY and not PIXABAY_API_KEY:
        print("Neither PEXELS_API_KEY nor PIXABAY_API_KEY is set. Register a free key at "
              "pexels.com/api and/or pixabay.com/api/docs and set it as an environment variable.")
        return

    NEW_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    queries = [q.strip() for q in args.queries.split(",")] if args.queries else DEFAULT_QUERIES
    sources = list(SOURCES) if args.source == "both" else [args.source]

    total = 0
    for query in queries:
        for source_name in sources:
            print(f"\nSearching {source_name} for \"{query}\" ...")
            try:
                urls = SOURCES[source_name](query, args.count)
            except requests.HTTPError as e:
                print(f"  [{source_name}] search failed: {e}")
                continue

            if not urls:
                print(f"  [{source_name}] no results.")
                continue

            for i, url in enumerate(urls, 1):
                dest = NEW_DOWNLOADS_DIR / _safe_name(query, source_name, i)
                if dest.exists():
                    continue
                print(f"  Downloading {dest.name} ...")
                try:
                    _download(url, dest)
                    total += 1
                except Exception as e:
                    print(f"    failed: {e}")

    print(f"\nDone. {total} clip(s) downloaded into footage/new_downloads/.")
    print("Next: python footage/review_new_downloads.py")


if __name__ == "__main__":
    main()
