"""
The publishing queue: approved videos wait here for their slot.

Making a video and publishing it used to be one event, so a slow step
(a render) was tied to a timed one (going out at a good hour), and one
video held for review stopped a channel. Now:

    made -> waiting (review) -> approved -> queued -> out at its slot

A video is approved by you in the review queue, or by the publish gate
under autopilot. It then waits for the channel's next publishing slot
(`channel.publishing`). With no slots, or with the plan off, it goes out
on the next scheduler tick instead. See docs/specs/launch-pipeline-and-
publishing.md.

"Going out" means, per channel:
- YouTube: uploaded through the channel's connection, if it has one.
- TikTok / Instagram: copied, with its caption, to the hand-off folder
  (a synced folder, OneDrive by default) for posting by hand from a
  phone. Neither platform gives an ordinary account an upload API it can
  use without an app review; see the spec, section 4.

Queue state lives in the video's publish sidecar (core.gallery), so a
video carries its own state and nothing can drift out of step with it.
Only "which slot did we last fill" is kept separately, per channel.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import gallery, youtube
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import PROJECT_ROOT

log = get_logger(__name__)

STATE_PATH = PROJECT_ROOT / "config" / "publishing_state.json"

HANDOFF_PLATFORMS = ("tiktok", "instagram")
PLATFORM_LABELS = {"tiktok": "TikTok", "instagram": "Instagram"}

# How far back a missed slot still counts. If the PC was off at 18:00,
# the 18:00 video goes out when it comes back on, but one missed slot is
# made up, not a week's worth in a burst.
MISSED_SLOT_GRACE = timedelta(hours=20)


def handoff_dir() -> Path:
    """Where videos for TikTok and Instagram are put for posting by hand.

    SHORTS_HANDOFF_DIR if set; otherwise "Shorts to post" in OneDrive, so
    the files are on the phone's OneDrive app a minute later with nothing
    exposed to the network; otherwise a folder in the project."""
    explicit = os.environ.get("SHORTS_HANDOFF_DIR", "").strip()
    if explicit:
        return Path(explicit)
    onedrive = os.environ.get("OneDrive", "").strip()
    base = Path(onedrive) if onedrive and Path(onedrive).exists() else PROJECT_ROOT
    return base / "Shorts to post"


# --- queue state -----------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(video_path: Path, approved_by: str) -> dict:
    """Approve a video to go out at its channel's next slot. `approved_by`
    is "you" or "checks". Approving twice keeps the first place in line."""
    info = gallery.load_publish_info(video_path)
    if info["discarded"] or gallery.is_out(info):
        raise PipelineError(f"{video_path} can't be queued",
                            user_message="That video is already published or discarded.")
    return gallery.save_queue_state(video_path,
                                    queued_at=info["queued_at"] or _now().isoformat(),
                                    approved_by=approved_by)


def unqueue(video_path: Path) -> dict:
    """Take a video out of the queue and back to review."""
    return gallery.save_queue_state(video_path, queued_at=None, approved_by=None)


def queued(channel) -> list:
    """This channel's queued videos, first in line first."""
    directory = gallery.resolve_output_dir(channel.output_dir)
    if not directory.exists():
        return []
    items = []
    for path in directory.rglob("*.mp4"):
        info = gallery.load_publish_info(path)
        if gallery.is_queued(info):
            items.append((info["queued_at"], path))
    return [path for _, path in sorted(items)]


# --- slots -----------------------------------------------------------

def _slot_times(publishing) -> list:
    return sorted({tuple(int(p) for p in s.split(":")) for s in publishing.slots})


def upcoming_slots(publishing, after: datetime, count: int) -> list:
    """The next `count` slot times after `after`, local time."""
    after = after.astimezone()
    times = _slot_times(publishing)
    if not times or not publishing.weekdays:
        return []
    out = []
    day = after.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(0, 400):
        if day.weekday() in publishing.weekdays:
            for hour, minute in times:
                slot = day.replace(hour=hour, minute=minute)
                if slot > after:
                    out.append(slot)
                    if len(out) >= count:
                        return out
        day += timedelta(days=1)
    return out


def latest_slot(publishing, now: datetime):
    """The most recent slot at or before `now`, or None."""
    now = now.astimezone()
    times = _slot_times(publishing)
    if not times or not publishing.weekdays:
        return None
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(8):
        if day.weekday() in publishing.weekdays:
            for hour, minute in reversed(times):
                slot = day.replace(hour=hour, minute=minute)
                if slot <= now:
                    return slot
        day -= timedelta(days=1)
    return None


def schedule_for(channel, now: datetime = None) -> list:
    """[(video_path, when)] for everything queued, in order. `when` is a
    local datetime, or None for "on the next check" (no plan or no slots)."""
    now = now or _now()
    videos = queued(channel)
    if not _slots_active(channel):
        return [(path, None) for path in videos]
    state = _load_state().get(channel.key, {})
    last = _parse(state.get("last_slot"))
    due = latest_slot(channel.publishing, now)
    slots = []
    if due and (last is None or due > last) and now - due <= MISSED_SLOT_GRACE:
        slots.append(due)  # a slot that's due now and still unfilled
    slots += upcoming_slots(channel.publishing, now, len(videos))
    return list(zip(videos, slots))


def _slots_active(channel) -> bool:
    return bool(channel.publishing.enabled and channel.publishing.slots
                and channel.publishing.weekdays)


# --- going out -------------------------------------------------------

def publish_due(channels: dict, now: datetime = None) -> list:
    """Send out whatever is due, at most one video per channel per slot.
    Returns a message per video sent or failed. Called by the scheduler."""
    now = now or _now()
    results = []
    state = _load_state()
    for key, channel in channels.items():
        if channel.archived:
            continue
        videos = queued(channel)
        if not videos:
            continue
        if _slots_active(channel):
            due = latest_slot(channel.publishing, now)
            last = _parse(state.get(key, {}).get("last_slot"))
            if due is None or (last is not None and due <= last) or now - due > MISSED_SLOT_GRACE:
                continue
            state.setdefault(key, {})["last_slot"] = due.isoformat()
            _save_state(state)
        results.append(send(channel, videos[0]))
    return results


def send(channel, video_path: Path) -> str:
    """Put one video out on every platform this channel uses.

    YouTube failing is not the end of the video: it goes back to review
    with the reason, the same as anything else a person needs to look at.
    """
    info = gallery.load_publish_info(video_path)
    title = info["title"] or video_path.stem.replace("_", " ")
    description = info["description"]
    messages = []
    platforms = [p for p in HANDOFF_PLATFORMS if getattr(channel.publishing, f"handoff_{p}")]

    # YouTube first: if the upload fails the video goes back to review, and
    # it mustn't already be sitting in the phone folder for TikTok.
    if youtube.connection(channel.key)["connected"]:
        try:
            result = youtube.upload(channel.key, video_path, title, description,
                                    privacy="public")
        except PipelineError as exc:
            log.warning(f"{channel.key}: queued upload failed: {exc}")
            unqueue(video_path)
            _note_on_report(video_path, f"The scheduled upload failed: {exc.user_message} "
                                        f"It's back in review.")
            return f"{channel.channel_display_name}: upload failed ({exc.user_message})"
        links = {f: info[f] for f in gallery.PUBLISH_LINK_FIELDS}
        links["youtube_url"] = result["url"]
        gallery.save_publish_info(video_path, links)
        note = f"on YouTube: {result['url']}"
        if result.get("locked_private"):
            note += " (private until the Google audit; make it public in Studio)"
        messages.append(note)
    elif not platforms:
        unqueue(video_path)
        _note_on_report(video_path, "It was due to go out, but this channel has nowhere to "
                                    "publish: connect YouTube or turn on a hand-off.")
        return f"{channel.channel_display_name}: nowhere to publish"

    handoff = dict(info["handoff"])
    for platform in platforms:
        if platform not in handoff:
            _copy_to_handoff(channel, video_path, title, description, platform)
            handoff[platform] = {"at": _now().isoformat(), "posted_at": None}
    if handoff != info["handoff"]:
        gallery.save_queue_state(video_path, handoff=handoff)
        messages.append("ready to post on " + " and ".join(
            PLATFORM_LABELS[p] for p in handoff if not handoff[p].get("posted_at")))

    summary = f"{channel.channel_display_name}: \"{title}\" " + "; ".join(messages)
    log.info(summary)
    return summary


def mark_posted(video_path: Path, platform: str, url: str = "") -> dict:
    """You've posted a handed-off video. The link is optional; with one,
    the video also counts as published on that platform."""
    if platform not in HANDOFF_PLATFORMS:
        raise PipelineError(f"unknown platform {platform}", user_message="Unknown platform.")
    info = gallery.load_publish_info(video_path)
    handoff = dict(info["handoff"])
    entry = dict(handoff.get(platform) or {"at": None})
    entry["posted_at"] = _now().isoformat()
    handoff[platform] = entry
    gallery.save_queue_state(video_path, handoff=handoff)
    if url.strip():
        links = {f: info[f] for f in gallery.PUBLISH_LINK_FIELDS}
        links[f"{platform}_url"] = url.strip()
        gallery.save_publish_info(video_path, links)
    if all(h.get("posted_at") for h in handoff.values()):
        _remove_handoff_copies(video_path)
    return gallery.load_publish_info(video_path)


def awaiting_posts(channels: dict) -> list:
    """Handed-off videos not yet marked posted, oldest first:
    [{"channel", "video_path", "title", "platforms": [...], "file"}]."""
    rows = []
    for key, channel in channels.items():
        directory = gallery.resolve_output_dir(channel.output_dir)
        if not directory.exists():
            continue
        for path in directory.rglob("*.mp4"):
            info = gallery.load_publish_info(path)
            pending = [p for p, h in info["handoff"].items() if not h.get("posted_at")]
            if pending and not info["discarded"]:
                rows.append({
                    "channel_key": key, "channel": channel.channel_display_name,
                    "video_path": path, "title": info["title"] or path.stem,
                    "description": info["description"],
                    "platforms": pending, "since": min(info["handoff"][p]["at"] or "" for p in pending),
                    "file": _handoff_file(channel, path),
                })
    return sorted(rows, key=lambda r: r["since"])


# --- hand-off files --------------------------------------------------

def _handoff_file(channel, video_path: Path) -> Path:
    folder = handoff_dir() / channel.channel_display_name
    return folder / f"{video_path.parent.name} {video_path.stem}.mp4"


def _copy_to_handoff(channel, video_path: Path, title: str, description: str,
                     platform: str) -> None:
    """One copy per video, shared by both platforms, plus its caption.
    Caption first line is the title, then the description, which is what
    both apps want pasted."""
    target = _handoff_file(channel, video_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(video_path, target)
    target.with_suffix(".txt").write_text(f"{title}\n\n{description}".strip() + "\n",
                                          encoding="utf-8")


def _remove_handoff_copies(video_path: Path) -> None:
    """Once posted everywhere, the phone copy has done its job."""
    from core.channels import load_channels
    key = gallery._channel_key_for(video_path)
    channel = load_channels(validate=False).get(key) if key else None
    if channel is None:
        return
    target = _handoff_file(channel, video_path)
    for path in (target, target.with_suffix(".txt")):
        path.unlink(missing_ok=True)


def _note_on_report(video_path: Path, message: str) -> None:
    report = gallery.load_report(video_path) or {}
    report["autopilot"] = {"action": "held", "message": message, "spot_check": False}
    gallery.save_report(video_path, report)


# --- state -----------------------------------------------------------

def _parse(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
