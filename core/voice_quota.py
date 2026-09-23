"""
How many ElevenLabs characters this month's subscription has left.

This is the one provider balance that *is* readable with an ordinary key:
ElevenLabs is a character allowance per billing period, not prepaid
money, and `GET /v1/user/subscription` reports how much of it is used.
On a Starter plan that allowance, not the Claude budget, is what limits
how many videos a month can be made. So it's shown where you look daily,
and a video that can't fit in what's left is stopped before the
voiceover, not halfway through one. See decision 025.

Unknown is always an allowed answer. A key restricted without the
`user_read` permission, a network blip or no key at all return None, and
nothing is blocked on a number that couldn't be read: ElevenLabs' own
`quota_exceeded` response is still the backstop (decision 021).
"""

from __future__ import annotations

import os
import statistics
import threading
import time
from dataclasses import dataclass

import requests

from core import costs
from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"

# The home page reads this on every load, so a short cache keeps it from
# adding a network round trip each time. A render always forces a fresh
# read, since that is the moment the number has to be right.
CACHE_SECONDS = 300
REQUEST_TIMEOUT = 5

# Used for scheduling decisions when a channel has no voiceover history
# yet. This project's jobs have averaged ~850 characters including
# retries; rounded up so a first scheduled run isn't started on a guess
# that's too small.
DEFAULT_VIDEO_CHARACTERS = 1000

# Below this many typical videos' worth, the home page warns.
LOW_QUOTA_VIDEOS = 5


class VoiceQuotaExhausted(PipelineError):
    """This video's narration won't fit in what the subscription has left."""


@dataclass
class Quota:
    used: int
    limit: int
    resets_at: float = None     # unix time, when ElevenLabs gives one
    tier: str = ""

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


_lock = threading.Lock()
_cached = None          # (fetched_at, Quota or None)
_warned = False


def _read() -> Quota | None:
    global _warned
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        return None
    try:
        response = requests.get(SUBSCRIPTION_URL, headers={"xi-api-key": key},
                                timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        log.info(f"ElevenLabs quota unavailable: {exc}")
        return None
    if not response.ok:
        # Most likely a key without the user_read permission. Said once,
        # not on every home page load.
        if not _warned:
            log.warning(f"ElevenLabs quota unavailable (HTTP {response.status_code}). "
                        f"The API key needs the user_read permission to report it.")
            _warned = True
        return None
    try:
        data = response.json()
        return Quota(used=int(data["character_count"]), limit=int(data["character_limit"]),
                     resets_at=data.get("next_character_count_reset_unix"),
                     tier=data.get("tier") or "")
    except (ValueError, KeyError, TypeError) as exc:
        log.warning(f"ElevenLabs quota response not understood: {exc}")
        return None


def current(force: bool = False) -> Quota | None:
    """The subscription's quota, or None if it can't be read right now."""
    global _cached
    with _lock:
        if not force and _cached and time.time() - _cached[0] < CACHE_SECONDS:
            return _cached[1]
    quota = _read()
    with _lock:
        _cached = (time.time(), quota)
    return quota


def typical_video_characters(channel_key: str) -> int:
    """Median characters one video on this channel has actually used,
    retries included, from the cost log. The default until it has one."""
    per_job = {}
    for r in costs.read_records():
        if (r.get("service") == "elevenlabs" and r.get("operation") == "voiceover"
                and r.get("channel_key") == channel_key and r.get("job_id")):
            per_job[r["job_id"]] = per_job.get(r["job_id"], 0) + (r.get("characters") or 0)
    totals = [n for n in per_job.values() if n > 0]
    return int(statistics.median(totals)) if totals else DEFAULT_VIDEO_CHARACTERS


def has_room_for(characters: int, force: bool = False) -> bool:
    """False only when the quota is known and too small."""
    quota = current(force=force)
    return quota is None or quota.remaining >= characters


def require_room(characters: int) -> None:
    """Raise before spending anything if this narration can't fit."""
    quota = current(force=True)
    if quota is None or quota.remaining >= characters:
        return
    raise VoiceQuotaExhausted(
        f"needs {characters} characters, {quota.remaining} of {quota.limit} left",
        user_message=(
            f"This voiceover needs about {characters:,} ElevenLabs characters and the "
            f"subscription has {quota.remaining:,} of {quota.limit:,} left"
            f"{_resets_phrase(quota)}. The script is saved; retry this job once the "
            f"quota resets, or upgrade the plan."),
    )


def summary(channel_keys=()) -> dict | None:
    """What the UI shows: remaining, limit, reset date, and roughly how
    many videos that is at this installation's typical length."""
    quota = current()
    if quota is None:
        return None
    sizes = [typical_video_characters(k) for k in channel_keys] or [DEFAULT_VIDEO_CHARACTERS]
    per_video = max(1, int(statistics.median(sizes)))
    videos_left = quota.remaining // per_video
    return {
        "used": quota.used,
        "limit": quota.limit,
        "remaining": quota.remaining,
        "tier": quota.tier,
        "resets_at": quota.resets_at,
        "resets_label": _reset_date(quota),
        "per_video": per_video,
        "videos_left": videos_left,
        "low": videos_left < LOW_QUOTA_VIDEOS,
    }


def _reset_date(quota: Quota) -> str:
    if not quota.resets_at:
        return ""
    return time.strftime("%d %b", time.localtime(quota.resets_at)).lstrip("0")


def _resets_phrase(quota: Quota) -> str:
    label = _reset_date(quota)
    return f" (it resets on {label})" if label else ""
