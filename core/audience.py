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

A documentary also gets its retention curve (decision 086): the share
still watching at each hundredth of the film, which core.retention puts
against the scene that was playing, and from which a week-old film
teaches the channel a lesson or two (core.lessons).

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
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
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
            updated, partial_error, subscribers = _refresh_channel(key, due)
            results[key] = {"updated": updated, "error": partial_error}
            if subscribers is not None:
                results[key]["subscribers"] = subscribers
        except PipelineError as exc:
            log.warning(f"{key}: couldn't refresh video statistics: {exc}")
            results[key] = {"updated": 0, "error": exc.user_message}
            continue
        if getattr(channel, "format", "") == "documentary":
            _learn(channel, due)
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
    for path in gallery.videos_in(directory):
        info = gallery.load_publish_info(path)
        vid = video_id(info.get("youtube_url", ""))
        if not vid or info.get("discarded"):
            continue
        stats = gallery.load_stats(path) or {}
        if force or time.time() - stats.get("fetched_at", 0) > REFRESH_HOURS * 3600:
            due[vid] = path
    return due


def _refresh_channel(key: str, due: dict) -> tuple:
    """(videos updated, "" or why retention couldn't be read, the channel's
    subscriber count or None)."""
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

    curves = {}
    if not retention_error:
        for vid, path in due.items():
            if vid in counts and _is_documentary(path):
                try:
                    curves[vid] = _curve(headers, vid, path)
                except PipelineError as exc:
                    log.warning(f"{key}: no retention curve for {path.stem}: {exc}")

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
            **({"curve": curves[vid]} if curves.get(vid) else {}),
            "retention_error": retention_error,
        })
    subscribers = _subscribers(headers, key)
    if retention_error:
        return len(counts), f"Views updated, but retention couldn't be read: {retention_error}", subscribers
    return len(counts), "", subscribers


def _subscribers(headers: dict, key: str):
    """The channel's subscriber count (one quota unit), for the Partner
    Programme's 1,000 (core.money). None if YouTube hides it or won't say."""
    try:
        response = requests.get(CHANNELS_URL, headers=headers, timeout=30,
                                params={"part": "statistics", "mine": "true"})
        items = youtube._json_or_raise(response, "read the channel's subscribers").get("items") or []
    except (PipelineError, requests.RequestException) as exc:
        log.warning(f"{key}: subscriber count unavailable: {exc}")
        return None
    stats = (items[0] if items else {}).get("statistics") or {}
    if stats.get("hiddenSubscriberCount"):
        return None
    return _int(stats.get("subscriberCount")) if "subscriberCount" in stats else None


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


def _is_documentary(path) -> bool:
    from pipeline.documentary import thumbs
    return thumbs.is_documentary(path)


def _curve(headers: dict, vid: str, path) -> list:
    """[[elapsed ratio, share still watching, relative to similar videos]]
    for one video: one Analytics call."""
    published = (gallery.load_publish_info(path).get("published_at") or "")[:10] or "2020-01-01"
    response = requests.get(ANALYTICS_URL, headers=headers, timeout=30, params={
        "ids": "channel==MINE", "startDate": published, "endDate": date.today().isoformat(),
        "metrics": "audienceWatchRatio,relativeRetentionPerformance",
        "dimensions": "elapsedVideoTimeRatio", "filters": f"video=={vid}"})
    payload = youtube._json_or_raise(response, "read a retention curve")
    return [[float(r[0]), float(r[1]), float(r[2]) if len(r) > 2 and r[2] is not None else None]
            for r in payload.get("rows") or []]


def _learn(channel, due: dict) -> None:
    """Lessons from documentaries old enough to have taught something.
    Best-effort: the figures are saved whatever happens here."""
    from core import retention
    for path in due.values():
        try:
            new = retention.learn(channel, path)
            if new:
                log.info(f"{channel.key}: learnt from {path.stem}: {' / '.join(new)}")
        except Exception as exc:  # noqa: BLE001 - a lesson missed is tried again next refresh
            log.warning(f"{channel.key}: couldn't learn from {path.stem}: {exc}")


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _save_status(results: dict) -> None:
    current = status()
    stamp = time.time()
    for key, outcome in results.items():
        # The last subscriber count stays until a refresh brings a new one.
        current[key] = {**current.get(key, {}), **outcome, "at": stamp}
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        # Status is a courtesy for the page; the numbers themselves are
        # already saved beside each video.
        log.warning("Couldn't write the audience refresh status.")
