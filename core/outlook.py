"""
The outlook for one channel (decision 107): where its audience is going,
whether it reaches the Partner Programme before the bar rises, what it
costs to get there and when it pays its way.

The Money page says what things cost now. This says where they're
heading, from the channel's own day-by-day numbers: YouTube Analytics,
split into Shorts and long videos (`creatorContentType`), read at most
twice a day and kept only as the latest copy (YouTube's policies ask
that stored figures be refreshed, not piled up).

Every projection is the recent pace carried forward in a straight line:
the last four weeks' average a day. It is honest about being a guess.
A channel with no pace yet says "not on the current pace" rather than
inventing a date, and anything past three years out is left unsaid.
"""

from __future__ import annotations

import json
import math
import time
from datetime import date, timedelta

import requests

from core import money, youtube
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR, write_atomically

log = get_logger(__name__)

ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
REFRESH_HOURS = 12
HISTORY_DAYS = 365
PACE_DAYS = 28
HORIZON_DAYS = 3 * 365
LONG, SHORTS = "videoOnDemand", "shorts"


def _cache_path(key: str):
    return CACHE_DIR / "outlook" / f"{key}.json"


def daily(key: str, force: bool = False, today: date = None) -> dict:
    """{"days": [{day, long_views, long_minutes, short_views, subs_net}],
    "fetched_at", "error"} for the last year, from YouTube; the cached copy
    when it's fresh, or when YouTube can't be reached (with the error)."""
    path = _cache_path(key)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {"days": [], "fetched_at": 0}
    if not force and time.time() - cached.get("fetched_at", 0) < REFRESH_HOURS * 3600:
        return cached
    today = today or date.today()
    try:
        headers = {"Authorization": f"Bearer {youtube.access_token(key)}"}
        response = requests.get(ANALYTICS_URL, headers=headers, timeout=30, params={
            "ids": "channel==MINE", "startDate": (today - timedelta(days=HISTORY_DAYS)).isoformat(),
            "endDate": today.isoformat(), "dimensions": "day,creatorContentType", "sort": "day",
            "metrics": "views,estimatedMinutesWatched,subscribersGained,subscribersLost"})
        payload = youtube._json_or_raise(response, "read the channel's day-by-day figures")
    except (PipelineError, requests.RequestException) as exc:
        log.warning(f"{key}: outlook figures unavailable: {exc}")
        message = getattr(exc, "user_message", "") or "YouTube couldn't be reached."
        return {**cached, "error": message}
    days = {}
    names = [h.get("name") for h in payload.get("columnHeaders", [])]
    for row in payload.get("rows") or []:
        r = dict(zip(names, row))
        d = days.setdefault(r["day"], {"day": r["day"], "long_views": 0, "long_minutes": 0.0,
                                       "short_views": 0, "subs_net": 0})
        kind = r.get("creatorContentType")
        if kind == LONG:
            d["long_views"] += int(r.get("views") or 0)
            d["long_minutes"] += float(r.get("estimatedMinutesWatched") or 0)
        elif kind == SHORTS:
            d["short_views"] += int(r.get("views") or 0)
        d["subs_net"] += int(r.get("subscribersGained") or 0) - int(r.get("subscribersLost") or 0)
    out = {"days": sorted(days.values(), key=lambda d: d["day"]), "fetched_at": time.time(), "error": ""}
    write_atomically(path, json.dumps(out))
    return out


# --- projecting -------------------------------------------------------------------------

def _pace(values: list) -> float:
    """The average a day over the last PACE_DAYS days (fewer if that's all there is)."""
    recent = values[-PACE_DAYS:]
    return sum(recent) / len(recent) if recent else 0.0


def reach(current: float, per_day: float, target: float, today: date):
    """The day `current` reaches `target` at `per_day`, today if it has, or
    None when it never would (or not within the horizon)."""
    if current >= target:
        return today
    if per_day <= 0:
        return None
    days = math.ceil((target - current) / per_day)
    return today + timedelta(days=days) if days <= HORIZON_DAYS else None


def partner(hours: float, subs: float, hours_pace: float, subs_pace: float, today: date) -> dict:
    """When the long-form route to the Partner Programme is reached: 1,000
    subscribers and 4,000 watch hours before 1 Feb 2027, 8,000 after."""
    subs_on = reach(subs, subs_pace, 1000, today)
    before = reach(hours, hours_pace, money.YPP_BEFORE["hours"], today)
    if subs_on and before and max(subs_on, before) < money.YPP_CHANGE:
        when, rule = max(subs_on, before), money.YPP_BEFORE
    else:
        after = reach(hours, hours_pace, money.YPP_AFTER["hours"], today)
        when = max(subs_on, after) if subs_on and after else None
        rule = money.YPP_AFTER if today >= money.YPP_CHANGE or when is None or when >= money.YPP_CHANGE \
            else money.YPP_BEFORE
    days_left = (money.YPP_CHANGE - today).days
    return {"date": when, "before_change": bool(when and when < money.YPP_CHANGE), "rule": rule,
            "subs_date": subs_on, "hours_date": before if when and when < money.YPP_CHANGE else
            reach(hours, hours_pace, money.YPP_AFTER["hours"], today),
            "hours_a_day_needed": max(0.0, money.YPP_BEFORE["hours"] - hours) / days_left
            if days_left > 0 else None,
            "subs_a_day_needed": max(0.0, 1000 - subs) / days_left if days_left > 0 else None}


def payback(spent: float, monthly: float, views_a_day: float, growth: float, rpm: float,
            from_day: date, today: date) -> dict:
    """When earnings cover the running cost a day ("pays its way"), and when
    they've covered everything spent ("all back"), with earnings starting
    on `from_day` (the Partner Programme) at `rpm` a thousand long views,
    views a day growing by `growth` a day. None for either beyond the horizon."""
    cost_a_day = monthly / money.MONTH_DAYS
    if from_day is None or rpm <= 0:
        return {"pays_its_way": None, "all_back": None, "cost_a_day": cost_a_day}
    cost, earned, pays, back = spent, 0.0, None, None
    for n in range(HORIZON_DAYS + 1):
        day = today + timedelta(days=n)
        views = views_a_day + growth * n
        cost += cost_a_day
        if day >= from_day:
            per_day = views * rpm / 1000
            earned += per_day
            if pays is None and per_day >= cost_a_day > 0:
                pays = day
            if back is None and earned >= cost:
                back = day
        if pays and back:
            break
    return {"pays_its_way": pays, "all_back": back, "cost_a_day": cost_a_day}


def _growth(values: list) -> float:
    """The straight-line change a day in daily values over the last eight
    weeks (least squares), never negative: a projection of decline would
    only say "never", which the flat case already says."""
    recent = values[-2 * PACE_DAYS:]
    n = len(recent)
    if n < 14:
        return 0.0
    mean_x, mean_y = (n - 1) / 2, sum(recent) / n
    top = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(recent))
    bottom = sum((x - mean_x) ** 2 for x in range(n))
    return max(0.0, top / bottom) if bottom else 0.0


def _spend_by_day(key: str) -> list:
    from core import costs
    by_day = {}
    for r in costs.read_records():
        if r.get("channel_key") == key and r.get("cost_usd"):
            day = date.fromtimestamp(r["ts"]).isoformat()
            by_day[day] = by_day.get(day, 0.0) + float(r["cost_usd"])
    total, out = 0.0, []
    for day in sorted(by_day):
        total += by_day[day]
        out.append((day, round(total, 2)))
    return out


def picture(channel, forecast: dict, today: date = None, figures: dict = None) -> dict:
    """Everything the Outlook page shows for `channel`."""
    from core import audience
    today = today or date.today()
    figures = figures if figures is not None else daily(channel.key)
    days = figures.get("days") or []
    subs_now = (audience.status().get(channel.key) or {}).get("subscribers")
    net = [d["subs_net"] for d in days]
    if subs_now is None:
        subs_now = sum(net)
    # Subscribers a day back from today's count; watch hours as a running year.
    subs_series, running = [], subs_now - sum(net)
    hours_series, hours = [], 0.0
    for d in days:
        running += d["subs_net"]
        hours += d["long_minutes"] / 60
        subs_series.append((d["day"], running))
        hours_series.append((d["day"], round(hours, 1)))
    long_views = [d["long_views"] for d in days]
    short_views = [d["short_views"] for d in days]
    hours_pace = _pace([d["long_minutes"] / 60 for d in days])
    subs_pace = _pace(net)
    ypp = partner(hours, subs_now, hours_pace, subs_pace, today)
    mine = money.for_channel(forecast, channel.key)
    spend = _spend_by_day(channel.key)
    spent = spend[-1][1] if spend else 0.0
    rpm = float(forecast["settings"]["long_rpm"])
    views_a_day, growth = _pace(long_views), _growth(long_views)
    pay = payback(spent, mine["monthly"], views_a_day, growth, rpm,
                  ypp["date"] if channel.key not in forecast["settings"]["in_ypp"] else today, today)

    horizon = max([d for d in (ypp["date"], pay["all_back"], money.YPP_CHANGE + timedelta(days=60)) if d] +
                  [today + timedelta(days=120)])
    span = (horizon - today).days
    subs_ahead = [(today.isoformat(), subs_now), (horizon.isoformat(), round(subs_now + subs_pace * span))]
    hours_ahead = [(today.isoformat(), round(hours, 1)), (horizon.isoformat(), round(hours + hours_pace * span, 1))]
    cost_a_day = pay["cost_a_day"]
    cost_ahead = [(today.isoformat(), spent), (horizon.isoformat(), round(spent + cost_a_day * span, 2))]
    earn_ahead = []
    if (ypp["date"] or channel.key in forecast["settings"]["in_ypp"]) and rpm > 0:
        start = today if channel.key in forecast["settings"]["in_ypp"] else ypp["date"]
        earned, step = 0.0, max(1, span // 60)
        earn_ahead.append((start.isoformat(), 0.0))
        for n in range((start - today).days, span + 1):
            earned += (views_a_day + growth * n) * rpm / 1000
            if n % step == 0:
                earn_ahead.append(((today + timedelta(days=n)).isoformat(), round(earned, 2)))
    return {
        "key": channel.key, "name": channel.channel_display_name or channel.key,
        "error": figures.get("error", ""), "fetched_at": figures.get("fetched_at"), "has_days": bool(days),
        "subs": subs_now, "hours": round(hours, 1), "subs_pace": subs_pace, "hours_pace": hours_pace,
        "long_views_28d": sum(long_views[-PACE_DAYS:]), "short_views_28d": sum(short_views[-PACE_DAYS:]),
        "long_per_1000_shorts": (sum(long_views[-PACE_DAYS:]) * 1000 / sum(short_views[-PACE_DAYS:])
                                 if sum(short_views[-PACE_DAYS:]) else None),
        "ypp": ypp, "pay": pay, "monthly": mine["monthly"], "spent": spent, "rpm": rpm,
        "change": money.YPP_CHANGE, "today": today,
        "charts": {
            "subs": {"series": [{"name": "Subscribers", "slot": 1, "points": subs_series},
                                {"name": "At this pace", "slot": 1, "dashed": True, "points": subs_ahead}],
                     "refs": [{"label": "1,000", "segments": [[subs_series[0][0] if subs_series else today.isoformat(),
                                                                horizon.isoformat(), 1000]]}],
                     "markers": [{"at": money.YPP_CHANGE.isoformat(), "label": "Bar rises"}], "unit": "int"},
            "hours": {"series": [{"name": "Watch hours", "slot": 1, "points": hours_series},
                                 {"name": "At this pace", "slot": 1, "dashed": True, "points": hours_ahead}],
                      "refs": [{"label": "4,000 h", "segments": [[hours_series[0][0] if hours_series else today.isoformat(),
                                                                   money.YPP_CHANGE.isoformat(), 4000]]},
                               {"label": "8,000 h", "segments": [[money.YPP_CHANGE.isoformat(), horizon.isoformat(), 8000]]}],
                      "markers": [{"at": money.YPP_CHANGE.isoformat(), "label": "Bar rises"}], "unit": "hours"},
            "views": {"series": [{"name": "Long-video views a day", "slot": 1,
                                  "points": _weekly_average([(d["day"], d["long_views"]) for d in days])}],
                      "refs": [], "markers": [], "unit": "int"},
            "money": {"series": [{"name": "Spent", "slot": 2, "points": spend},
                                 {"name": "Cost ahead", "slot": 2, "dashed": True, "points": cost_ahead, "label_end": True},
                                 {"name": "Earned (projected)", "slot": 1, "dashed": True, "points": earn_ahead,
                                  "label_end": True}],
                      "refs": [], "markers": [{"at": d.isoformat(), "label": label} for d, label in
                                              ((ypp["date"], "Partner Programme"), (pay["all_back"], "All back"))
                                              if d], "unit": "usd"},
        },
    }


def _weekly_average(points: list) -> list:
    """A seven-day running average, so one busy day doesn't read as a trend."""
    out = []
    for i, (day, _) in enumerate(points):
        window = [v for _, v in points[max(0, i - 6):i + 1]]
        out.append((day, round(sum(window) / len(window), 1)))
    return out
