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

The allowance is counted in credits, not characters, and a character of
the voiceover model costs less than one credit: on 5 Oct, 7,629 characters
of `eleven_turbo_v2_5` took 1,527 credits, 0.2 each. Everything here used
to compare characters with credits, so the app thought the allowance five
times smaller than it was (decision 069). The rate is measured from
ElevenLabs' own history of recent requests, at most daily, and every
estimate and check converts characters to credits with it.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import threading
import time
from dataclasses import dataclass

import requests

from core import costs
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR

log = get_logger(__name__)

SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"
HISTORY_URL = "https://api.elevenlabs.io/v1/history"

# Credits per character of the voiceover model, measured from the account's
# own recent requests (each history item says what it moved the counter by).
RATIO_PATH = CACHE_DIR / "voice_credit_ratio.json"
RATIO_MAX_AGE = 86400          # measured again daily
RATIO_SAMPLE = 100             # recent requests looked at
RATIO_MIN_CHARACTERS = 500     # fewer than this measured says nothing

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
_ratio = None           # (measured_at, credits per character)


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


def _read_ratio():
    """Credits per character of the voiceover model, from ElevenLabs' history
    of this account's recent requests: what each moved the counter by, over
    its text's length. None if it can't be read or there's too little."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        return None
    from pipeline.tts import ELEVENLABS_MODEL
    try:
        response = requests.get(HISTORY_URL, headers={"xi-api-key": key},
                                params={"page_size": RATIO_SAMPLE}, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        log.info(f"ElevenLabs history unavailable: {exc}")
        return None
    if not response.ok:
        log.info(f"ElevenLabs history unavailable (HTTP {response.status_code}); "
                 "counting a character as a credit")
        return None
    try:
        characters = used = 0
        for item in response.json().get("history") or []:
            change = (int(item.get("character_count_change_to") or 0)
                      - int(item.get("character_count_change_from") or 0))
            if item.get("model_id") == ELEVENLABS_MODEL and item.get("text") and change >= 0:
                characters += len(item["text"])
                used += change
    except (ValueError, TypeError, AttributeError) as exc:
        log.warning(f"ElevenLabs history not understood: {exc}")
        return None
    return used / characters if characters >= RATIO_MIN_CHARACTERS else None


def credits_per_character() -> float:
    """What a character of narration costs in credits: measured (at most
    daily, kept between restarts), the last measurement if a new one can't
    be made, and 1.0 (the cautious answer) if there has never been one."""
    global _ratio
    with _lock:
        if _ratio and time.time() - _ratio[0] < RATIO_MAX_AGE:
            return _ratio[1]
    saved = None
    try:
        saved = json.loads(RATIO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if saved and time.time() - float(saved.get("at") or 0) < RATIO_MAX_AGE:
        measured = (float(saved["at"]), float(saved["ratio"]))
    else:
        ratio = _read_ratio()
        if ratio is not None:
            measured = (time.time(), ratio)
            try:
                RATIO_PATH.parent.mkdir(parents=True, exist_ok=True)
                RATIO_PATH.write_text(json.dumps({"at": measured[0], "ratio": ratio}), encoding="utf-8")
            except OSError:
                # A cache: if it's lost, the rate is measured again tomorrow.
                log.warning("Couldn't save the ElevenLabs credit rate")
        elif saved and saved.get("ratio"):
            measured = (time.time(), float(saved["ratio"]))   # stale beats none; tried again tomorrow
        else:
            measured = (time.time(), 1.0)
    with _lock:
        _ratio = measured
    return measured[1]


def credits_for(characters: int) -> int:
    """The credits narrating this many characters takes."""
    return math.ceil(characters * credits_per_character())


def typical_video_credits(channel_key: str) -> int:
    """Credits one video on this channel typically takes."""
    return credits_for(typical_video_characters(channel_key))


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


def has_room_for(characters: int, force: bool = False, channel_key: str = "") -> bool:
    """Whether narrating this many characters fits what's left. False only
    when the quota is known and too small. With `channel_key`, what the
    channels ahead of it in the voice priority still need before the reset
    is kept back first (decision 131)."""
    quota = current(force=force)
    if quota is None:
        return True
    kept = reserve_for(channel_key, quota) if channel_key else 0
    return quota.remaining - kept >= credits_for(characters)


RESERVE_SECONDS = 300
TIE_SECONDS = 12 * 3600         # videos due within half a day of each other: the priority decides
_reserved = {}          # channel key -> (worked out at, credits)


def _rank(channel) -> float:
    priority = int(getattr(channel.publishing, "voice_priority", 0) or 0)
    return priority if priority > 0 else float("inf")


def needs(channel, quota: Quota) -> list:
    """[(when it goes out, credits)] for the videos that fill `channel`'s
    slots before the quota resets, as the Voice page counts them
    (core.voice_budget). Teasers owed for films already made count as due
    now. Films or shorts made further ahead, with no slot before the reset,
    aren't needs."""
    from core import costs, voice_budget
    now = time.time()
    until = float(quota.resets_at or (now + 31 * 86400))
    blocks, _ = voice_budget.to_come({channel.key: channel}, costs.read_records(), credits_per_character(),
                                     now, until)
    out = []
    for b in blocks:
        if b.get("spent"):
            continue
        if b.get("release"):
            out.append((float(b["release"]), int(b["credits"])))
        elif b.get("state") == "teasers to make":
            out.append((now, int(b["credits"])))
    return sorted(out)


def need_before_reset(channel, quota: Quota) -> int:
    return sum(c for _, c in needs(channel, quota))


def reserve_for(channel_key: str, quota: Quota = None) -> int:
    """Credits kept back from `channel_key`'s next video for other
    channels' videos that go out first (decision 131). The owner, 23 Oct:
    "prioritise why though films when credits are short. then the quiz
    channel. then minute pastor"; and 25 Oct: "i dont want one channel to
    miss a video just so Why Though gets one made 3 weeks in advance." So
    what goes out sooner is voiced first, whichever channel it's for; the
    priority decides only between videos due within half a day of each other;
    and a video made ahead of any slot comes after every other channel's
    dated ones."""
    with _lock:
        cached = _reserved.get(channel_key)
        if cached and time.time() - cached[0] < RESERVE_SECONDS:
            return cached[1]
    from core.channels import load_channels
    quota = quota or current()
    if quota is None:
        return 0
    channels = load_channels(validate=False)
    me = channels.get(channel_key)
    if me is None:
        return 0
    try:
        mine = needs(me, quota)
    except Exception as exc:  # noqa: BLE001 - a need that can't be worked out keeps nothing back
        log.warning(f"voice priority: couldn't work out what {channel_key} needs: {exc}")
        mine = []
    when = mine[0][0] if mine else float("inf")         # its next video; none due: made ahead
    kept = 0
    for key, other in channels.items():
        if key == channel_key or other.archived or not other.publishing.enabled:
            continue
        ahead = _rank(other) < _rank(me)
        try:
            theirs = needs(other, quota)
        except Exception as exc:  # noqa: BLE001 - as above
            log.warning(f"voice priority: couldn't work out what {key} needs: {exc}")
            continue
        for due, credits in theirs:
            # A channel ahead in the priority wins a near-tie (within half a
            # day); one behind gets what it needs sooner than that.
            first = due <= when + TIE_SECONDS if ahead else due < when - TIE_SECONDS
            if first:
                kept += credits
    with _lock:
        _reserved[channel_key] = (time.time(), kept)
    return kept


def require_room(characters: int) -> None:
    """Raise before spending anything if narrating this many characters
    can't fit."""
    quota = current(force=True)
    if quota is None:
        return
    needed = credits_for(characters)
    if quota.remaining >= needed:
        return
    raise VoiceQuotaExhausted(
        f"needs {needed} credits, {quota.remaining} of {quota.limit} left",
        user_message=(
            f"This voiceover needs about {needed:,} ElevenLabs credits and the "
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
    sizes = [typical_video_credits(k) for k in channel_keys] or [credits_for(DEFAULT_VIDEO_CHARACTERS)]
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
