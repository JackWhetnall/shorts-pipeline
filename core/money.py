"""
What running the channels costs a month, how long the money and the voice
allowance last, and what it takes to get the money back (decision 067).

Everything spent on these keys is spent by this app (the owner, 5 Oct), so
the cost log is the whole bill and a balance can be worked out from one
known figure: what was loaded and when. The owner enters that once
(`settings()["balances"]`), and again after each top-up; the log does the
rest. The ElevenLabs allowance is read from ElevenLabs itself, never from
the log, which overcounts its characters about fourfold.

Revenue is an estimate from the audience numbers already read back
(core.audience) and an RPM the owner can change. It's zero until a
channel is in the Partner Programme, and the page says so. From 1 Feb 2027
YouTube doubles what joining takes, and Shorts only earn above 10M views
in 90 days: long-form is what pays back.
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import date, datetime

from core import gallery
from core.logging_setup import get_logger
from core.paths import CACHE_DIR, PROJECT_ROOT

log = get_logger(__name__)

SETTINGS_PATH = PROJECT_ROOT / "config" / "money.json"
DAY = 86400
MONTH_DAYS = 30.4

# Which cost-log services each bill covers.
PROVIDERS = {
    "anthropic": {"label": "Claude", "services": ("claude",)},
    "openai": {"label": "OpenAI", "services": ("openai-image", "openai")},
    "fal": {"label": "fal", "services": ("fal",)},
}
VOICE_SERVICE = "elevenlabs"

DEFAULTS = {
    # {"anthropic": {"usd": 40.0, "at": 0}}: what was loaded and when; spend
    # logged since then comes off it. "at" 0 means "since the start".
    "balances": {},
    "elevenlabs_monthly_usd": 5.0,     # Starter
    "long_rpm": 4.0,                   # $ per 1,000 long-form views (trivia and education run $3-6)
    "shorts_rpm": 0.0,                 # nothing below 10M Shorts views in 90 days, from Feb 2027
    "in_ypp": [],                      # channel keys in the Partner Programme
    "spare_voice": True,               # spend the voice left before a reset on videos made ahead
}

# YouTube Partner Programme, for new applicants.
YPP_SUBSCRIBERS = 1000
YPP_CHANGE = date(2027, 2, 1)
YPP_BEFORE = {"hours": 4000, "shorts_views": 10_000_000}
YPP_AFTER = {"hours": 8000, "shorts_views": 20_000_000}

RECENT_JOBS = 10       # a channel's cost per video is the median of its last this many


# --- settings --------------------------------------------------------------------

def settings() -> dict:
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        saved = {}
    except ValueError:
        log.warning(f"{SETTINGS_PATH.name} is unreadable; using the defaults")
        saved = {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def save_settings(changes: dict) -> dict:
    current = settings()
    current.update({k: v for k, v in changes.items() if k in DEFAULTS})
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(current, indent=1), encoding="utf-8")
    return current


def set_balance(provider: str, usd: float, now: float = None) -> dict:
    """The balance as it stands now (after a top-up): spend from here on
    comes off it."""
    balances = dict(settings()["balances"])
    balances[provider] = {"usd": round(max(0.0, float(usd)), 2), "at": now or time.time()}
    return save_settings({"balances": balances})


# --- spend -----------------------------------------------------------------------

def _provider_of(service: str) -> str:
    return next((p for p, info in PROVIDERS.items() if service in info["services"]), "")


def spend(records: list, now: float) -> dict:
    """{provider: {"7d", "30d", "all"}} in dollars, from the cost log."""
    out = {p: {"7d": 0.0, "30d": 0.0, "all": 0.0} for p in PROVIDERS}
    for r in records:
        provider = _provider_of(r.get("service", ""))
        if not provider:
            continue
        cost, age = float(r.get("cost_usd") or 0), now - float(r.get("ts") or 0)
        out[provider]["all"] += cost
        if age <= 30 * DAY:
            out[provider]["30d"] += cost
        if age <= 7 * DAY:
            out[provider]["7d"] += cost
    return out


def cost_per_video(records: list, channel_key: str) -> float:
    """The median of this channel's last RECENT_JOBS jobs, in API dollars
    (not the voice, which is a subscription)."""
    jobs = {}
    for r in records:
        if r.get("channel_key") == channel_key and r.get("job_id") and _provider_of(r.get("service", "")):
            job = jobs.setdefault(r["job_id"], [0.0, 0.0])
            job[0] += float(r.get("cost_usd") or 0)
            job[1] = max(job[1], float(r.get("ts") or 0))
    recent = sorted(jobs.values(), key=lambda j: j[1])[-RECENT_JOBS:]
    return statistics.median(j[0] for j in recent) if recent else 0.0


def shorts_per_month(channel) -> float:
    plan = channel.publishing
    if channel.archived or not plan.enabled:
        return 0.0
    if not plan.slots:
        return MONTH_DAYS
    return len(plan.slots) * len(plan.weekdays or range(7)) * MONTH_DAYS / 7


def longs_per_month(channel) -> float:
    """Long quizzes a month: one per long-video slot, when it makes them."""
    plan, q = channel.publishing, channel.quiz
    if (channel.archived or not plan.enabled or channel.format != "quiz"
            or not (q.longform_mixed_when_ready or q.longform_category_when_ready)):
        return 0.0
    return len(plan.long_slots) * len(plan.long_weekdays or range(7)) * MONTH_DAYS / 7


def plan_rows(channels: dict, records: list) -> list:
    """Per running channel: what it makes a month and what that costs."""
    rows = []
    for key, channel in channels.items():
        shorts, longs = shorts_per_month(channel), longs_per_month(channel)
        if not shorts and not longs:
            continue
        per_video = cost_per_video(records, key)
        rows.append({"key": key, "name": channel.channel_display_name or key,
                     "shorts": shorts, "longs": longs, "per_video": per_video,
                     "monthly": per_video * (shorts + longs)})
    return rows


# --- runway ----------------------------------------------------------------------

def balance(provider: str, records: list, saved: dict) -> float | None:
    """What's left on a prepaid account, or None if the owner hasn't said
    what was loaded."""
    entry = saved["balances"].get(provider)
    if not entry:
        return None
    since = float(entry.get("at") or 0)
    spent = sum(float(r.get("cost_usd") or 0) for r in records
                if _provider_of(r.get("service", "")) == provider and float(r.get("ts") or 0) >= since)
    return float(entry["usd"]) - spent


def runway(left: float, per_day: float, now: float) -> dict:
    if left is None:
        return None
    if left <= 0:
        return {"left": left, "days": 0, "until": date.fromtimestamp(now)}
    if per_day <= 0:
        return {"left": left, "days": None, "until": None}
    days = left / per_day
    return {"left": left, "days": days, "until": date.fromtimestamp(now + days * DAY)}


VOICE_HISTORY_PATH = CACHE_DIR / "voice_usage.json"
VOICE_PACE_DAYS = 7          # the pace is the counter's rise over about the last week
VOICE_HISTORY_DAYS = 45


def record_voice(quota, now: float, path=None) -> dict:
    """Note today's reading of the ElevenLabs counter ({"YYYY-MM-DD": used})
    and return the history. A cache, not a record: losing it only means
    the pace falls back to the cycle's average for a few days."""
    path = path or VOICE_HISTORY_PATH
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        history = {}
    if quota is not None:
        history[date.fromtimestamp(now).isoformat()] = quota.used
        cutoff = date.fromtimestamp(now - VOICE_HISTORY_DAYS * DAY).isoformat()
        history = {d: n for d, n in history.items() if d >= cutoff}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(history, indent=1, sort_keys=True), encoding="utf-8")
        except OSError:
            log.warning("Couldn't save the voice allowance reading; the pace uses the cycle's average")
    return history


def voice_pace(history: dict, now: float) -> float | None:
    """Characters a day over about the last week of readings, counting only
    since the counter last went down (it resets monthly). None with less
    than a day between readings."""
    readings = sorted((date.fromisoformat(d), n) for d, n in history.items())
    since_reset = []
    for day, used in readings:
        if since_reset and used < since_reset[-1][1]:
            since_reset = []            # the allowance reset in between
        since_reset.append((day, used))
    today = date.fromtimestamp(now)
    recent = [(d, n) for d, n in since_reset if (today - d).days <= VOICE_PACE_DAYS] or since_reset
    if len(recent) < 2:
        return None
    (first_day, first), (last_day, last) = recent[0], recent[-1]
    days = (last_day - first_day).days
    return (last - first) / days if days >= 1 else None


def voice(quota, now: float, history: dict = None) -> dict:
    """The ElevenLabs allowance at its own counter's recent pace: does it
    last until it resets, and would a month at this pace fit?"""
    if quota is None:
        return None
    resets = float(quota.resets_at or 0)
    started = resets - MONTH_DAYS * DAY if resets else 0
    elapsed = (now - started) / DAY if started else 0
    per_day = voice_pace(history or {}, now)
    if per_day is None:
        per_day = quota.used / elapsed if elapsed >= 1 else None
    out = {"used": quota.used, "limit": quota.limit, "remaining": quota.remaining, "per_day": per_day,
           "resets": date.fromtimestamp(resets) if resets else None, "runs_out": None, "dry_days": 0}
    if per_day and resets:
        out_on = now + quota.remaining / per_day * DAY
        if out_on < resets:
            out["runs_out"] = date.fromtimestamp(out_on)
            out["dry_days"] = int((resets - out_on) / DAY)
        # A full month at this pace against the allowance.
        out["month_need"] = per_day * MONTH_DAYS
    return out


def _voice_now(quota, now: float, rows: list = ()) -> dict:
    out = voice(quota, now, record_voice(quota, now))
    if out is not None:
        # What the schedule itself needs a month, in credits: the structural
        # question, where the pace above can be a burst week.
        from core import voice_quota
        out["schedule_need"] = int(sum((r["shorts"] + r["longs"]) * voice_quota.typical_video_credits(r["key"])
                                       for r in rows))
    return out


# --- audience and payback -------------------------------------------------------------

def _published(video_path) -> float:
    info = gallery.load_publish_info(video_path)
    stamp = info.get("published_at") or ""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def audience(channels: dict, now: float) -> dict:
    """Per channel, from the numbers read back from YouTube: long-form watch
    hours in the last year (what the Partner Programme counts), Shorts
    views in the last 90 days, and views of what went out in the last 30."""
    from core import audience as reader
    subscribers = {k: v.get("subscribers") for k, v in reader.status().items()}
    out = {}
    for key, channel in channels.items():
        directory = gallery.resolve_output_dir(channel.output_dir)
        row = {"hours": 0.0, "shorts_views_90d": 0, "long_views_30d": 0, "shorts_views_30d": 0,
               "subscribers": subscribers.get(key)}
        if directory.exists():
            for path in gallery.videos_in(directory):
                stats = gallery.load_stats(path)
                published = _published(path)
                if not stats or not published:
                    continue
                age, views = now - published, int(stats.get("views") or 0)
                if gallery.is_long(path.relative_to(directory)):
                    if age <= 365 * DAY:
                        row["hours"] += views * float(stats.get("avg_view_seconds") or 0) / 3600
                    if age <= 30 * DAY:
                        row["long_views_30d"] += views
                else:
                    if age <= 90 * DAY:
                        row["shorts_views_90d"] += views
                    if age <= 30 * DAY:
                        row["shorts_views_30d"] += views
        out[key] = row
    return out


def ypp(row: dict, today: date) -> dict:
    """Progress toward the Partner Programme, against whichever thresholds
    apply on the day it would be reached, and the pace needed to make the
    old ones."""
    rule = YPP_BEFORE if today < YPP_CHANGE else YPP_AFTER
    days_left = (YPP_CHANGE - today).days
    hours_short = max(0.0, YPP_BEFORE["hours"] - row["hours"])
    return {"rule": rule, "hours": row["hours"], "hours_share": min(1.0, row["hours"] / rule["hours"]),
            "subscribers": row["subscribers"],
            "shorts_views": row["shorts_views_90d"],
            "days_to_change": days_left if days_left > 0 else None,
            "hours_per_day_needed": hours_short / days_left if days_left > 0 else None}


def payback(monthly_cost: float, saved: dict, views: dict) -> dict:
    """What the channels would earn a month at their current views, and the
    long-form views a month that would cover the costs."""
    long_rpm, shorts_rpm = float(saved["long_rpm"]), float(saved["shorts_rpm"])
    earning = sum(v["long_views_30d"] * long_rpm / 1000 + v["shorts_views_30d"] * shorts_rpm / 1000
                  for key, v in views.items() if key in saved["in_ypp"])
    would = sum(v["long_views_30d"] * long_rpm / 1000 + v["shorts_views_30d"] * shorts_rpm / 1000
                for v in views.values())
    return {"earning": earning, "would_earn": would,
            "views_needed": monthly_cost / long_rpm * 1000 if long_rpm > 0 else None,
            "long_views_30d": sum(v["long_views_30d"] for v in views.values()),
            "covered": earning >= monthly_cost > 0}


# --- the whole picture ---------------------------------------------------------------

def forecast(channels: dict = None, now: float = None) -> dict:
    """Everything the Money page and Today show."""
    from core import costs, voice_quota
    from core.channels import load_channels
    from pipeline.facts import budget
    now = now or time.time()
    channels = channels if channels is not None else load_channels(validate=False)
    records = costs.read_records()
    saved = settings()
    rows = plan_rows(channels, records)
    videos_monthly = sum(r["monthly"] for r in rows)
    bank_left = budget.remaining()
    monthly = videos_monthly + float(saved["elevenlabs_monthly_usd"])
    claude_per_day = videos_monthly / MONTH_DAYS     # what the schedule spends; nearly all of it Claude
    claude_left = balance("anthropic", records, saved)
    views = audience(channels, now)
    today = date.fromtimestamp(now)
    return {
        "spend": spend(records, now),
        "rows": rows,
        "videos_monthly": videos_monthly,
        "monthly": monthly,
        "weekly": monthly * 7 / MONTH_DAYS,
        "daily": monthly / MONTH_DAYS,
        "bank_left": bank_left,
        "claude": runway(None if claude_left is None else claude_left - bank_left, claude_per_day, now),
        "claude_balance": claude_left,
        "openai_balance": balance("openai", records, saved),
        "voice": _voice_now(voice_quota.current(), now, rows),
        "views": views,
        "ypp": {key: ypp(row, today) for key, row in views.items()
                if key in {r["key"] for r in rows}},
        "payback": payback(monthly, saved, views),
        "settings": saved,
    }
