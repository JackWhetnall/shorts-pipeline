"""
How published videos are doing with the people watching them.

Everything else this project measures is about itself: discard rate,
render flags, spend. None of it says whether anyone watches. This reads
it back from YouTube for every video published through a connected
channel, so the insights page can put an audience number beside the
choices that produced it.

Two sources, because neither has everything:

- The Data API (`youtube.readonly`) for views, likes and comments. Close
  to live.
- The Analytics API (`yt-analytics.readonly`) for average view duration,
  average percentage viewed and subscribers gained. That percentage is
  the number that matters most for short-form. It lags by a day or two,
  so a new video shows views before it shows retention.

Only the latest snapshot per video is kept, in a `_stats.json` sidecar,
overwritten on each refresh. That is all the insights page needs, and
YouTube's developer policies ask that stored statistics be refreshed or
deleted within 30 days rather than accumulated.

A refresh never raises for one channel's problem. It returns what
happened per channel and records the last error for the page to show.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date

import requests

from core import gallery, youtube
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR

log = get_logger(__name__)

DATA_URL = "https://www.googleapis.com/youtube/v3/videos"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"

# Statistics move slowly and the Analytics API lags anyway. Twice a day is
# plenty, and keeps well inside the Data API's daily quota (a videos.list
# call costs 1 unit of 10,000).
REFRESH_HOURS = 12
DATA_BATCH = 50          # videos.list accepts at most 50 ids
ANALYTICS_METRICS = ("views", "averageViewDuration", "averageViewPercentage",
                     "subscribersGained")
STATUS_PATH = CACHE_DIR / "audience_status.json"

_VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def video_id(url: str) -> str:
    """The 11-character id from any of the URL shapes YouTube hands out:
    watch?v=, youtu.be/, /shorts/. "" if there isn't one."""
    match = _VIDEO_ID.search(url or "")
    return match.group(1) if match else ""


def refresh(channels: dict, force: bool = False) -> dict:
    """Fetch fresh numbers for every published video that is due.

    `channels` is {key: ChannelConfig}. Returns {key: {"updated": n,
    "error": str}} for the channels that were tried.
    """
    results = {}
    for key, channel in channels.items():
        if not youtube.connection(key)["stats"]:
            continue
        due = _due_videos(channel, force)
        if not due:
            continue
        try:
            updated, partial_error = _refresh_channel(key, due)
            results[key] = {"updated": updated, "error": partial_error}
        except PipelineError as exc:
            log.warning(f"{key}: couldn't refresh video statistics: {exc}")
            results[key] = {"updated": 0, "error": exc.user_message}
    if results:
        _save_status(results)
    return results


def status() -> dict:
    """The last refresh's outcome per channel, for the insights page."""
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _due_videos(channel, force: bool) -> dict:
    """{youtube_id: video_path} for published videos whose snapshot is
    missing or older than REFRESH_HOURS."""
    directory = gallery.resolve_output_dir(channel.output_dir)
    if not directory.exists():
        return {}
    due = {}
    for path in directory.rglob("*.mp4"):
        info = gallery.load_publish_info(path)
        vid = video_id(info.get("youtube_url", ""))
        if not vid or info.get("discarded"):
            continue
        stats = gallery.load_stats(path) or {}
        if force or time.time() - stats.get("fetched_at", 0) > REFRESH_HOURS * 3600:
            due[vid] = path
    return due


def _refresh_channel(key: str, due: dict) -> tuple:
    """(videos updated, "" or why retention couldn't be read)."""
    token = youtube.access_token(key)
    headers = {"Authorization": f"Bearer {token}"}
    ids = list(due)

    counts = {}
    for start in range(0, len(ids), DATA_BATCH):
        batch = ids[start:start + DATA_BATCH]
        response = requests.get(DATA_URL, headers=headers, timeout=30,
                                params={"part": "statistics", "id": ",".join(batch)})
        payload = youtube._json_or_raise(response, "read video statistics")
        for item in payload.get("items", []):
            s = item.get("statistics", {})
            counts[item.get("id")] = {
                "views": _int(s.get("viewCount")),
                "likes": _int(s.get("likeCount")),
                "comments": _int(s.get("commentCount")),
            }

    # Retention is best-effort on top of the counts: the Analytics API is
    # a separate switch in the Cloud project, and a project that hasn't
    # enabled it should still get views rather than nothing.
    retention, retention_error = {}, ""
    try:
        retention = _analytics(headers, ids, due)
    except PipelineError as exc:
        retention_error = exc.user_message
        log.warning(f"{key}: retention unavailable: {exc}")

    now = time.time()
    for vid, path in due.items():
        if vid not in counts:
            # Deleted on YouTube, or made private by someone else. Leave
            # the last snapshot; don't overwrite it with zeros.
            continue
        gallery.save_stats(path, {
            "video_id": vid,
            "fetched_at": now,
            **counts[vid],
            **retention.get(vid, {}),
            "retention_error": retention_error,
        })
    if retention_error:
        return len(counts), f"Views updated, but retention couldn't be read: {retention_error}"
    return len(counts), ""


def _analytics(headers: dict, ids: list, due: dict) -> dict:
    earliest = min((gallery.load_publish_info(p).get("published_at") or "")[:10]
                   for p in due.values()) or "2020-01-01"
    response = requests.get(ANALYTICS_URL, headers=headers, timeout=30, params={
        "ids": "channel==MINE",
        "startDate": earliest,
        "endDate": date.today().isoformat(),
        "metrics": ",".join(ANALYTICS_METRICS),
        "dimensions": "video",
        "filters": "video==" + ",".join(ids),
        "sort": "-views",
        "maxResults": 200,
    })
    payload = youtube._json_or_raise(response, "read retention figures")
    names = [h.get("name") for h in payload.get("columnHeaders", [])]
    out = {}
    for row in payload.get("rows") or []:
        record = dict(zip(names, row))
        vid = record.pop("video", None)
        if vid:
            out[vid] = {
                "avg_view_seconds": record.get("averageViewDuration"),
                "avg_view_percent": record.get("averageViewPercentage"),
                "subscribers_gained": record.get("subscribersGained"),
            }
    return out


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _save_status(results: dict) -> None:
    current = status()
    stamp = time.time()
    for key, outcome in results.items():
        current[key] = {**outcome, "at": stamp}
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        # Status is a courtesy for the page; the numbers themselves are
        # already saved beside each video.
        log.warning("Couldn't write the audience refresh status.")
