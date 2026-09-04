"""
Stock-footage search and download, against Pexels' and Pixabay's official
free APIs (not scraping — both publish documented search endpoints and
issue free keys).

Search results carry their source through to the clip record, which is
what lets the store record a real licence instead of the placeholder
every clip used to share. Both sites publish unambiguous commercial-use
terms, so a clip fetched here has a known licence — the honest unknowns
are the hand-added ones.
"""

from __future__ import annotations

import os

import requests

from core.errors import ExternalServiceError
from core.logging_setup import get_logger

log = get_logger(__name__)

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"

DOWNLOAD_TIMEOUT = 60
SEARCH_TIMEOUT = 30


class Result:
    """One search hit. `source` names the site so the licence can be
    recorded correctly downstream."""

    __slots__ = ("url", "source", "query")

    def __init__(self, url: str, source: str, query: str):
        self.url = url
        self.source = source
        self.query = query


def pexels_key() -> str:
    return os.environ.get("PEXELS_API_KEY")


def pixabay_key() -> str:
    return os.environ.get("PIXABAY_API_KEY")


def any_key_configured() -> bool:
    return bool(pexels_key() or pixabay_key())


def search_pexels(query: str, count: int) -> list:
    key = pexels_key()
    if not key:
        return []
    response = requests.get(
        PEXELS_SEARCH_URL,
        headers={"Authorization": key},
        params={"query": query, "per_page": count, "orientation": "portrait"},
        timeout=SEARCH_TIMEOUT,
    )
    response.raise_for_status()
    results = []
    for video in response.json().get("videos", []):
        files = [f for f in video.get("video_files", []) if f.get("link")]
        if not files:
            continue
        best = max(files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
        results.append(Result(best["link"], "pexels", query))
    return results


def search_pixabay(query: str, count: int) -> list:
    key = pixabay_key()
    if not key:
        return []
    response = requests.get(
        PIXABAY_SEARCH_URL,
        params={"key": key, "q": query, "per_page": max(count, 3)},
        timeout=SEARCH_TIMEOUT,
    )
    response.raise_for_status()
    results = []
    for hit in response.json().get("hits", [])[:count]:
        videos = hit.get("videos", {})
        best = videos.get("large") or videos.get("medium") or videos.get("small")
        if best and best.get("url"):
            results.append(Result(best["url"], "pixabay", query))
    return results


SEARCHERS = {"pexels": search_pexels, "pixabay": search_pixabay}


def search_all(query: str, per_site: int) -> list:
    """Both sites, deduplicated by URL. A search failure on one site is
    logged and skipped rather than raised — the other site's results are
    still worth having, and a footage shortfall is recoverable while a
    failed render isn't."""
    results = []
    seen = set()
    for name, searcher in SEARCHERS.items():
        try:
            hits = searcher(query, per_site)
        except requests.RequestException as exc:
            log.warning(f'  [footage] {name} search failed for "{query}": {exc}')
            continue
        for hit in hits:
            if hit.url not in seen:
                seen.add(hit.url)
                results.append(hit)
    return results


def download(url: str, dest) -> None:
    """Stream to disk. Streaming rather than loading into memory because
    a single stock clip is routinely tens of megabytes and up to sixteen
    of these run concurrently."""
    try:
        response = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    except requests.RequestException as exc:
        raise ExternalServiceError(
            "The stock footage service", str(exc),
            user_message="A stock footage download failed. The clip was skipped.",
        ) from exc
