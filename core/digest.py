"""
What went out, and what's going out (decision 139).

The owner, 28 Oct: "a page ... that shows what went out yesterday (or since
this page's updates were "cleared" by me), and what is expected to go out
today". Read from the videos' own publish records and the publishing
queue; the only thing kept is when the owner last cleared it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import gallery
from core.logging_setup import get_logger
from core.paths import CACHE_DIR, write_atomically

log = get_logger(__name__)

SEEN_PATH = CACHE_DIR / "today_seen.json"
PLACES = (("youtube", "YouTube"), ("tiktok", "TikTok"), ("instagram", "Instagram"))


def _stamp(value):
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def since(now: datetime = None) -> datetime:
    """When the owner last cleared the list; the start of yesterday until then."""
    now = now or datetime.now().astimezone()
    try:
        cleared = _stamp(json.loads(SEEN_PATH.read_text(encoding="utf-8")).get("cleared_at"))
    except (OSError, ValueError, AttributeError):
        cleared = None
    if cleared:
        return cleared
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start


def clear(now: datetime = None) -> None:
    now = now or datetime.now(timezone.utc)
    write_atomically(SEEN_PATH, json.dumps({"cleared_at": now.isoformat()}))


def kind_of(channel, path: Path) -> str:
    if gallery.is_long(path):
        return "long"
    return "teaser" if channel.format == "documentary" else "short"


def went_out(channels: dict, after: datetime) -> list:
    """[{channel, name, title, kind, when, places: [(label, url)], path}]
    newest first: every video put on a platform since `after`."""
    rows = []
    for key, channel in channels.items():
        directory = gallery.resolve_output_dir(channel.output_dir)
        if not directory.exists():
            continue
        for path in gallery.videos_in(directory):
            info = gallery.load_publish_info(path)
            if info["discarded"]:
                continue
            handoff = info.get("handoff") or {}
            events = []
            yt = _stamp(info.get("published_at"))
            if yt and info.get("youtube_url"):
                events.append((yt, "YouTube", info.get("youtube_url")))
            for platform, label in PLACES[1:]:
                at = _stamp((handoff.get(platform) or {}).get("posted_at"))
                if at:
                    events.append((at, label, info.get(f"{platform}_url") or ""))
            recent = [e for e in events if e[0] >= after]
            if not recent:
                continue
            rows.append({"channel": key, "name": channel.channel_display_name or key,
                         "title": info.get("title") or gallery.video_title(path.name),
                         "kind": kind_of(channel, path), "when": max(e[0] for e in recent),
                         "places": [(label, url) for _, label, url in sorted(recent)],
                         "relpath": str(path.relative_to(gallery.OUTPUT_DIR)).replace("\\", "/")})
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows


def going_out(channels: dict, now: datetime = None, days: int = 2) -> list:
    """[{channel, name, title, kind, when, day}] in time order: what the
    publishing queue sends from now to the end of tomorrow."""
    from core import publish_queue
    now = now or datetime.now().astimezone()
    until = (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for key, channel in channels.items():
        try:
            schedule = publish_queue.in_order(channel)
        except Exception as exc:  # noqa: BLE001 - one channel's queue mustn't hide the rest
            log.warning(f"{key}: couldn't read its publishing queue: {exc}")
            continue
        for path, when in schedule:
            if not when:
                continue
            when = when if when.tzinfo else when.astimezone()
            if when >= until:
                continue
            info = gallery.load_publish_info(path)
            rows.append({"channel": key, "name": channel.channel_display_name or key,
                         "title": info.get("title") or gallery.video_title(Path(path).name),
                         "kind": kind_of(channel, Path(path)), "when": when,
                         "day": "Today" if when.date() <= now.date() else "Tomorrow"})
    rows.sort(key=lambda r: r["when"])
    return rows
