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
- TikTok / Instagram: added to "To post", where one click opens the
  channel's logged-in browser profile at the upload page with the video
  ready to drag in and the caption on the clipboard (core.posting).
  Neither platform lets an unreviewed app post for you; see decision 033.

Queue state lives in the video's publish sidecar (core.gallery), so a
video carries its own state and nothing can drift out of step with it.
Only "which slot did we last fill" is kept separately, per channel.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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


def number_of(video_path: Path) -> int:
    """A quiz short's number on screen (#4), or 0 for a video without one."""
    sidecar = Path(video_path).with_name(f"{Path(video_path).stem}_quiz.json")
    try:
        return int(json.loads(sidecar.read_text(encoding="utf-8")).get("number") or 0)
    except (OSError, ValueError):
        return 0


def queued(channel, long: bool = False) -> list:
    """This channel's queued videos, first in line first: its shorts, or
    with `long` its long videos, which go out in their own slots. Numbered
    shorts go in number order (#1, #2, #3), whatever order they were
    approved in; anything without a number in approval order after them."""
    directory = gallery.resolve_output_dir(channel.output_dir)
    if not directory.exists():
        return []
    items = []
    for path in gallery.videos_in(directory, long=long):
        info = gallery.load_publish_info(path)
        if gallery.is_queued(info):
            number = number_of(path)
            items.append(((0, number) if number else (1, 0), info["queued_at"], path))
    return [path for _, _, path in sorted(items, key=lambda row: (row[0], row[1]))]


def waiting_for(channel, video_path: Path) -> int:
    """The lowest-numbered short of this channel still waiting for review
    below this one's number, or 0. A numbered short waits for it, so the
    numbers go out in order; discarding or publishing it releases the wait."""
    number = number_of(video_path)
    if not number:
        return 0
    directory = gallery.resolve_output_dir(channel.output_dir)
    lower = []
    for path in gallery.videos_in(directory):
        other = number_of(path)
        if other and other < number:
            info = gallery.load_publish_info(path)
            if not info["discarded"] and not gallery.is_out(info) and not gallery.is_queued(info):
                lower.append(other)
    return min(lower) if lower else 0


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
    """[(video_path, when)] for everything queued, shorts then long videos,
    each in its lane's order. `when` is a local datetime, or None for "on
    the next check" (no plan or no slots)."""
    now = now or _now()
    out = []
    for long in (False, True):
        videos = queued(channel, long=long)
        if not videos:
            continue
        if not _slots_active(channel, long):
            out += [(path, None) for path in videos]
            continue
        plan = _lane(channel, long)
        last = _parse(_load_state().get(_lane_key(channel.key, long), {}).get("last_slot"))
        due = latest_slot(plan, now)
        slots = []
        if due and (last is None or due > last) and now - due <= MISSED_SLOT_GRACE:
            slots.append(due)  # a slot that's due now and still unfilled
        slots += upcoming_slots(plan, now, len(videos))
        out += list(zip(videos, slots))
    return out


def _lane(channel, long: bool):
    """The slots a lane publishes in: the plan's own, or for long videos
    their own days and times."""
    plan = channel.publishing
    if not long:
        return plan
    return SimpleNamespace(enabled=plan.enabled, slots=plan.long_slots, weekdays=plan.long_weekdays)


def _lane_key(channel_key: str, long: bool) -> str:
    return f"{channel_key}:long" if long else channel_key


def can_publish(channel) -> bool:
    """Whether the channel has anywhere to send a video: YouTube connected,
    or TikTok or Instagram hand-offs on."""
    return (youtube.connection(channel.key)["connected"]
            or any(getattr(channel.publishing, f"post_{p}") for p in HANDOFF_PLATFORMS))


def _slots_active(channel, long: bool = False) -> bool:
    plan = _lane(channel, long)
    return bool(plan.enabled and plan.slots and plan.weekdays)


# --- going out -------------------------------------------------------

def publish_due(channels: dict, now: datetime = None) -> list:
    """Send out whatever is due, at most one video per channel per slot.
    Returns a message per video sent or failed. Called by the scheduler."""
    now = now or _now()
    results = []
    state = _load_state()
    for key, channel in channels.items():
        # Approved videos wait, ready, until the channel's publishing plan
        # is on. With it off, "no slots" used to mean "publish at once": an
        # approved video was sent within minutes, found nowhere to go, and
        # was put back in review.
        if channel.archived or not channel.publishing.enabled or not can_publish(channel):
            continue
        for long in (False, True):
            videos = queued(channel, long=long)
            if not videos:
                continue
            if _slots_active(channel, long):
                lane = _lane_key(key, long)
                due = latest_slot(_lane(channel, long), now)
                last = _parse(state.get(lane, {}).get("last_slot"))
                if due is None or (last is not None and due <= last) or now - due > MISSED_SLOT_GRACE:
                    continue
                if waiting_for(channel, videos[0]):
                    continue        # an earlier number is still in review; this slot waits for it
                state.setdefault(lane, {})["last_slot"] = due.isoformat()
                _save_state(state)
            elif waiting_for(channel, videos[0]):
                continue
            results.append(send(channel, videos[0]))
    return results


class NowhereToPublish(PipelineError):
    """No YouTube connection and no hand-off to anywhere else."""


def hand_off_platforms(channel, video_path: Path, manual: bool = False) -> list:
    """The platforms a video is handed off to after YouTube: the ones the
    channel's plan posts to. A video published by hand also goes to both
    when the channel has a browser profile for posting but no plan, since
    it's the owner asking. TikTok and Instagram are for shorts; a long
    video is YouTube only."""
    if gallery.is_long(video_path):
        return []
    chosen = [p for p in HANDOFF_PLATFORMS if getattr(channel.publishing, f"post_{p}")]
    if not chosen and manual and channel.publishing.posting_profile:
        chosen = list(HANDOFF_PLATFORMS)
    return chosen


def put_out(channel, video_path: Path, privacy: str = "public", platforms: list = None) -> dict:  # noqa: C901
    """Put one video out: uploaded to YouTube through the channel's
    connection (unless it already has a YouTube link), then handed off to
    each of `platforms` (default: the plan's) in To post. Raises
    PipelineError if the YouTube upload fails, before anything is handed
    off, and NowhereToPublish with nowhere to send it. Returns
    {"messages", "youtube_url", "locked_private", "pending"} (`pending`:
    platforms handed off and not yet posted)."""
    info = gallery.load_publish_info(video_path)
    title = info["title"] or video_path.stem.replace("_", " ")
    description = info["description"]
    messages = []
    long = gallery.is_long(video_path)
    platforms = hand_off_platforms(channel, video_path) if platforms is None else \
        ([] if long else list(platforms))
    youtube_url, locked_private = info["youtube_url"], False

    # YouTube first: if the upload fails the video goes back to review, and
    # it mustn't already be sitting in the phone folder for TikTok.
    if info["youtube_url"]:
        messages.append(f"already on YouTube: {info['youtube_url']}")
    elif youtube.connection(channel.key)["connected"]:
        from core import posting
        result = youtube.upload(channel.key, video_path, title,
                                posting.with_youtube_hashtags(channel, video_path, description), privacy=privacy)
        thumb = video_path.with_name(f"{video_path.stem}_thumb.jpg")
        if long and thumb.exists() and result.get("id"):
            try:
                youtube.set_thumbnail(channel.key, result["id"], thumb)
            except PipelineError as exc:
                # The video is out; only its thumbnail is YouTube's own pick.
                log.warning(f"{channel.key}: thumbnail not set: {exc}")
                messages.append(f"thumbnail not set ({exc.user_message})")
        links = {f: info[f] for f in gallery.PUBLISH_LINK_FIELDS}
        links["youtube_url"] = youtube_url = result["url"]
        gallery.save_publish_info(video_path, links)
        locked_private = bool(result.get("locked_private"))
        note = f"on YouTube: {result['url']}"
        if locked_private:
            note += " (private until the Google audit; make it public in Studio)"
        messages.append(note)
    elif not platforms:
        raise NowhereToPublish("nowhere to publish", user_message=(
            "This channel has nowhere to publish yet: connect YouTube, or turn on TikTok or "
            "Instagram hand-off."))

    handoff = dict(info["handoff"])
    for platform in platforms:
        if platform not in handoff:
            handoff[platform] = {"at": _now().isoformat(), "posted_at": None}
    if handoff != info["handoff"]:
        gallery.save_queue_state(video_path, handoff=handoff)
    pending = [p for p in handoff if not handoff[p].get("posted_at")]
    if pending:
        try:
            from core import posting
            posting.stage(channel, video_path)
        except OSError as exc:  # it's made again when its posting steps are shown
            log.warning(f"{channel.key}: couldn't put the video in the ready-to-post folder: {exc}")
    if handoff != info["handoff"]:
        messages.append("waiting in To post for " + " and ".join(PLATFORM_LABELS[p] for p in pending))
    return {"messages": messages, "youtube_url": youtube_url, "locked_private": locked_private,
            "pending": pending, "title": title}


def publish_now(channel, video_path: Path, privacy: str = "public") -> dict:
    """Publish a video now, by hand: the same as its slot coming up, for a
    video you've just looked at and are ready to send. Nothing is changed
    if YouTube refuses it. See `put_out`."""
    info = gallery.load_publish_info(video_path)
    if info["discarded"]:
        raise PipelineError(f"{video_path} is discarded", user_message=(
            "That video is discarded. Restore it first if you want to publish it."))
    result = put_out(channel, video_path, privacy=privacy,
                     platforms=hand_off_platforms(channel, video_path, manual=True))
    log.info(f"{channel.channel_display_name}: published \"{result['title']}\" by hand: "
             + "; ".join(result["messages"]))
    return result


def send(channel, video_path: Path) -> str:
    """Put one video out on every platform this channel uses.

    YouTube failing is not the end of the video: it goes back to review
    with the reason, the same as anything else a person needs to look at.
    """
    try:
        result = put_out(channel, video_path)
    except NowhereToPublish:
        # Still approved: it waits for somewhere to go, not for another look.
        _note_on_report(video_path, "Approved and ready, but this channel has nowhere to "
                                    "publish yet: connect YouTube or turn on a hand-off.")
        return f"{channel.channel_display_name}: nowhere to publish yet"
    except PipelineError as exc:
        log.warning(f"{channel.key}: queued upload failed: {exc}")
        unqueue(video_path)
        _note_on_report(video_path, f"The scheduled upload failed: {exc.user_message} "
                                    f"It's back in review.")
        return f"{channel.channel_display_name}: upload failed ({exc.user_message})"

    summary = f"{channel.channel_display_name}: \"{result['title']}\" " + "; ".join(result["messages"])
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
        from core import posting
        posting.unstage(video_path)
    return gallery.load_publish_info(video_path)


def awaiting_posts(channels: dict) -> list:
    """Handed-off videos not yet marked posted, oldest first:
    [{"channel", "video_path", "title", "platforms": [...], "file"}]."""
    rows = []
    for key, channel in channels.items():
        directory = gallery.resolve_output_dir(channel.output_dir)
        if not directory.exists():
            continue
        for path in gallery.videos_in(directory):
            info = gallery.load_publish_info(path)
            pending = [p for p, h in info["handoff"].items() if not h.get("posted_at")]
            if pending and not info["discarded"]:
                rows.append({
                    "channel_key": key, "channel": channel.channel_display_name,
                    "video_path": path, "title": info["title"] or path.stem,
                    "description": info["description"],
                    "platforms": pending, "since": min(info["handoff"][p]["at"] or "" for p in pending),
                })
    return sorted(rows, key=lambda r: r["since"])


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
