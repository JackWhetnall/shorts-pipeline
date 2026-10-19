"""
A documentary channel that makes its own films (decision 086).

A documentary is made in stages, each waiting for the owner's approval
(decision 074). That's right while a channel is finding its voice, and
wrong for one meant to run itself. With `documentary.auto_make` on, the
scheduler moves the channel's next film on one stage at a time: it
starts a stage, and when the stage is ready it approves it (the angle
the pitch scored best, the outline, the script, the storyboard) and
starts the next. The finished video still waits in review like every
long video, so nothing goes out unseen; once the owner approves it, the
autopilot writes and makes its teasers too.

One film at a time, never more than `documentary.ahead` films made and
waiting for a look, never a stage the month's voice allowance can't
cover, and a stage that fails is tried once more and then left for the
owner (each retry costs money). Every approval it gives is marked in the
production's history as the autopilot's. (Not core.autopilot, which
decides whether a finished short is published without a look.)
"""

from __future__ import annotations

from core import curriculum, jobs, production
from core.logging_setup import get_logger

log = get_logger(__name__)

AUTO_APPROVED = ("pitch", "outline", "script", "stills")
# What an overseen channel leaves for the overseer to approve (decision 094).
REVIEWED = ("script", "stills")


def _busy(channel_key: str) -> bool:
    """A stage of this channel is being worked on (not just waiting on a
    batch: then another film can move on, decision 103)."""
    return any(j.get("channel_key") == channel_key and (j.get("seed") or {}).get("type") == "production"
               and not j.get("waiting") for j in jobs.active_in_order())


def _being_made(channel_key: str) -> set:
    """Films with a stage in a job now, waiting or not."""
    return {(j.get("seed") or {}).get("subtopic_id") for j in jobs.active_in_order()
            if j.get("channel_key") == channel_key and (j.get("seed") or {}).get("type") == "production"}


def _waiting(channel) -> int:
    """Films made and waiting for the owner's look."""
    return sum(1 for d in production.all_for(channel.key) if production.state(d, "video") == "ready")


def _in_hand(channel) -> tuple:
    """(films being made, films banked) (decisions 105, 111). Being made:
    past its angle, its video not yet made. Banked: made and not yet out,
    whether waiting for a look or approved and queued."""
    from core import gallery
    making = banked = 0
    for data in production.all_for(channel.key):
        video = production.state(data, "video")
        if video in ("approved", "ready"):
            made = production.video_file(channel, data)
            info = gallery.load_publish_info(made) if made is not None and made.exists() else None
            # A film discarded while it waited for a look holds no place (decision 120).
            if info is None and video == "ready":
                banked += 1
            elif info and not info["discarded"] and not gallery.is_out(info):
                banked += 1
        elif production.state(data, "outline") != "todo":
            making += 1
    return making, banked


def _room_for_a_new_film(channel) -> bool:
    """Up to `parallel` films being made at once, and up to `ahead` more
    banked on top of them (decision 111)."""
    doc = channel.documentary
    parallel = max(1, int(getattr(doc, "parallel", 1)))
    bank = max(1, int(getattr(doc, "ahead", 1)))
    making, banked = _in_hand(channel)
    return making < parallel and making + banked < parallel + bank


def _candidates(channel):
    """(plan entry, production, whether it's a new film) in the order to
    try them: films whose teasers are due, then films part-way through
    (past their angle; not one made and waiting for a look), then the
    next ones up. One waiting on the overseer or the owner no longer holds
    the rest (decision 105). Films with a stage in a job are left out.
    The scheduler pitches the next few films' angles ahead of time
    (storyboard.outline_ahead); a film with only an angle is still new."""
    from core import storyboard
    busy = _being_made(channel.key)
    films = [d for d in production.all_for(channel.key) if d["subtopic_id"] not in busy]
    out = []
    for data in films:
        row = curriculum.find(channel.key, data["subtopic_id"])
        if row and production.state(data, "video") == "approved" and production.current(data) == "teasers"                 and int(channel.documentary.teasers) > 0 and not (data.get("teasers") or {}).get("videos"):
            out.append((row, data, False))
    for data in films:
        row = curriculum.find(channel.key, data["subtopic_id"])
        stage = production.current(data)
        if row is None or stage in (None, "teasers") or production.state(data, "video") == "ready":
            continue
        if production.state(data, "outline") != "todo":
            out.append((row, data, False))
    ahead = max(1, int(getattr(channel.documentary, "parallel", 1)))
    for row in storyboard.upcoming(channel, count=ahead):
        if row["id"] not in busy:
            out.append((row, production.load(channel.key, row["id"], row["title"]), True))
    return out


def _next_film(channel):
    """The first film to try (kept for callers that want just one)."""
    found = _candidates(channel)
    return found[0] if found else (None, None, False)


def start(channel, row: dict, stage: str) -> str:
    """Queue a stage, at batch prices. Returns the job's id."""
    seed = {"type": "production", "subtopic_id": row["id"], "stage": stage,
            "topic": f"{row['title']}: {production.LABELS[stage].lower()}", "by": "autopilot"}
    return jobs.start_job(channel.key, seed, ahead=True, behind=True)


def step(channel) -> str:
    """Move the channel's next film on by one step. Returns what was done,
    or "" when there was nothing to do (or it isn't on)."""
    doc = channel.documentary
    if (channel.format != "documentary" or not getattr(doc, "auto_make", False) or channel.archived
            or not channel.publishing.enabled or not channel.animation.style):
        return ""
    if _busy(channel.key):
        return ""
    from datetime import datetime
    from core.channels import within_hours
    after_hours = not within_hours(getattr(doc, "hours", ""), datetime.now().hour)
    for row, data, new in _candidates(channel):
        if new and not _room_for_a_new_film(channel):
            break                       # enough being made and banked (decision 111)
        done = _act(channel, row, data, after_hours)
        if done:
            return done
    return ""


def _act(channel, row: dict, data: dict, after_hours: bool) -> str:
    """Move one film on by one step, or "" when it's waiting on someone."""
    doc = channel.documentary
    stage = production.current(data)
    if stage is None:
        return ""
    state = production.state(data, stage)
    if stage == "video" and state == "ready":
        return ""                       # the owner's look comes first
    if stage == "video" and state in ("todo", "stale"):
        from core import voice_quota
        chars = production.narration_still_to_voice(data)
        if chars and not voice_quota.has_room_for(chars):
            return ""
    if state == "ready" and stage in REVIEWED and getattr(doc, "overseen", False):
        return ""                       # the overseer reads it first (decision 094)
    if state == "ready" and stage in AUTO_APPROVED:
        production.approve(channel.key, row["id"], stage, by="autopilot")
        if stage == "outline":
            from pipeline.documentary import cast
            cast.merge(channel.key, row["id"], production.load(channel.key, row["id"])["outline"].get("cast") or [])
        return f"approved the {production.LABELS[stage].lower()} of {row['title']}"
    if stage == "teasers" and state == "ready":
        if getattr(doc, "overseen", False) and not (data.get("teasers") or {}).get("reviewed"):
            return ""                   # the overseer reads the teasers' scripts first (decision 111)
        start(channel, row, "teasers")
        return f"making the teasers of {row['title']}"
    if state == "failed":
        entry = data["stages"][stage]
        if entry.get("interrupted"):
            # Cut short by a restart (decision 097): not its fault, so not its retry.
            if after_hours:
                return ""
            production.update(channel.key, row["id"], lambda d: d["stages"][stage].pop("interrupted", None))
        elif entry.get("autopilot_retried"):
            return ""
        else:
            production.update(channel.key, row["id"], lambda d: d["stages"][stage].update(autopilot_retried=True))
    if state in ("todo", "stale", "failed"):
        if after_hours:
            return ""                       # stages start in the channel's hours only
        if stage == "teasers" and int(doc.teasers) < 1:
            return ""
        start(channel, row, stage)
        return f"started the {production.LABELS[stage].lower()} of {row['title']}"
    return ""


def tick(channels: dict) -> list:
    """One step for every documentary channel that makes its own films."""
    done = []
    for key, channel in channels.items():
        try:
            what = step(channel)
        except Exception as exc:  # noqa: BLE001 - one channel mustn't stop the rest
            log.warning(f"{key}: autopilot step failed: {exc}")
            continue
        if what:
            log.info(f"{key}: autopilot {what}")
            done.append(key)
    return done
