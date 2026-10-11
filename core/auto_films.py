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


def _busy(channel_key: str) -> bool:
    return any(j.get("channel_key") == channel_key and (j.get("seed") or {}).get("type") == "production"
               for j in jobs.active_in_order())


def _waiting(channel) -> int:
    """Films made and waiting for the owner's look."""
    return sum(1 for d in production.all_for(channel.key) if production.state(d, "video") == "ready")


def _next_film(channel):
    """(plan entry, production, whether it's a new film) to work on: a
    film whose teasers are due, else one part-way through (past its
    angle; not one made and waiting for a look), else the next one up.
    The scheduler pitches the next few films' angles ahead of time
    (storyboard.outline_ahead); a film with only an angle is still new."""
    from core import storyboard
    films = production.all_for(channel.key)
    for data in films:
        row = curriculum.find(channel.key, data["subtopic_id"])
        if row and production.state(data, "video") == "approved" and production.current(data) == "teasers"                 and int(channel.documentary.teasers) > 0 and not (data.get("teasers") or {}).get("videos"):
            return row, data, False
    for data in films:
        row = curriculum.find(channel.key, data["subtopic_id"])
        stage = production.current(data)
        if row is None or stage in (None, "teasers") or production.state(data, "video") == "ready":
            continue
        if production.state(data, "outline") != "todo":
            return row, data, False
    upcoming = storyboard.upcoming(channel, count=1)
    if not upcoming:
        return None, None, False
    row = upcoming[0]
    return row, production.load(channel.key, row["id"], row["title"]), True


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
    row, data, new = _next_film(channel)
    if row is None:
        return ""
    if new and _waiting(channel) >= max(1, int(getattr(doc, "ahead", 1))):
        return ""                       # enough made and waiting for a look
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
    if state == "ready" and stage in AUTO_APPROVED:
        production.approve(channel.key, row["id"], stage, by="autopilot")
        if stage == "outline":
            from pipeline.documentary import cast
            cast.merge(channel.key, row["id"], production.load(channel.key, row["id"])["outline"].get("cast") or [])
        return f"approved the {production.LABELS[stage].lower()} of {row['title']}"
    if stage == "teasers" and state == "ready":
        start(channel, row, "teasers")
        return f"making the teasers of {row['title']}"
    if state == "failed":
        entry = data["stages"][stage]
        if entry.get("autopilot_retried"):
            return ""
        production.update(channel.key, row["id"], lambda d: d["stages"][stage].update(autopilot_retried=True))
    if state in ("todo", "stale", "failed"):
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
