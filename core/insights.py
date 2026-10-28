"""
How is this actually going?

The question the system could never answer. Every existing view is either
current state (this channel has 12 videos) or one video's detail. Nothing
was trend, and nothing aggregated your own judgement back into a signal.

That gap has a concrete cost: footage matching was failing for months,
and the only way anyone could have known was by watching videos and
forming an impression. "Nine of the last twenty discarded, seven of them
for footage" is a number that would have made it obvious, and every input
to it already existed — it just had nowhere to go.

Everything here reads the per-video sidecars the pipeline already writes.
There is no separate database and nothing to keep in sync: delete a video
and it leaves the statistics, which is the correct behaviour.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from core import costs, gallery
from core.channels import load_channels


def _videos_for(channel) -> list:
    return gallery.list_videos(channel.output_dir)


def collect(channel_keys=None) -> dict:
    """One pass over every video, producing everything the page shows."""
    channels = load_channels(validate=False)
    if channel_keys:
        channels = {k: v for k, v in channels.items() if k in channel_keys}

    videos = []
    for key, channel in channels.items():
        for video in _videos_for(channel):
            video["channel_key"] = key
            video["channel_name"] = channel.channel_display_name
            videos.append(video)
    videos.sort(key=lambda v: v["mtime"])

    # Videos that were discarded and then deleted. They still happened, so
    # they still count toward the discard rate and its reasons — a loop of
    # "discard, then reclaim the disk" would otherwise show a keep rate of
    # 100% precisely because everything unkept had been thrown away. They
    # deliberately do NOT reach quality, spend or the recent list: their
    # render report and cost sidecar are gone, and inventing values there
    # would be worse than the gap.
    # Scoped to the channels being reported on, not to `channel_keys`:
    # tombstones outlive the channel they belonged to, and a deleted
    # channel's discards should not keep dragging down a rate computed
    # over the channels that still exist.
    purged = [r for r in gallery.purged_records() if r.get("channel") in channels]

    return {
        "totals": _totals(videos, purged),
        "discard_reasons": _discard_reasons(videos, purged),
        "quality": _quality(videos),
        "spend": _spend(videos, set(channels)),
        "recent": _recent(videos, limit=30),
        "audience": _audience(videos),
        "by_channel": _by_channel(videos, channels),
        "video_count": len(videos),
        "purged_count": len(purged),
    }


def _totals(videos: list, purged: list = ()) -> dict:
    total = len(videos) + len(purged)
    discarded = sum(1 for v in videos if v["discarded"]) + len(purged)
    published = sum(1 for v in videos if v["published"])
    kept = total - discarded
    # Waiting for a look is what the review queue shows: not approved and
    # queued for a slot, not set aside for its pair, not out. "Kept minus
    # published" counted 35 queued videos and 3 set aside as 38 to review
    # with the queue empty (28 Oct).
    live = [v for v in videos if not v["discarded"] and not v["published"] and not v.get("out")
            and not v.get("set_aside")]
    queued = sum(1 for v in live if v.get("queued"))
    return {
        "total": total,
        "published": published,
        "discarded": discarded,
        "awaiting_review": len(live) - queued,
        "queued": queued,
        # The number that matters: how much of what the machine makes is
        # good enough to use.
        "keep_rate": (kept / total) if total else 0.0,
        "discard_rate": (discarded / total) if total else 0.0,
    }


def _discard_reasons(videos: list, purged: list = ()) -> list:
    """Reasons, most common first.

    Videos discarded before reasons were recorded have none, and are
    counted separately rather than lumped into "other" — inventing a
    reason for them would make the trend look worse or better than it is.
    """
    counts = Counter()
    unrecorded = 0
    reasons = [v["links"].get("discard_reason") for v in videos if v["discarded"]]
    reasons += [r.get("discard_reason") for r in purged]
    for reason in reasons:
        if reason:
            counts[reason] += 1
        else:
            unrecorded += 1

    total = sum(counts.values())
    rows = [{
        "id": reason,
        "label": gallery.DISCARD_REASON_LABELS.get(reason, reason),
        "count": count,
        "share": count / total if total else 0.0,
    } for reason, count in counts.most_common()]
    return {"rows": rows, "recorded": total, "unrecorded": unrecorded}


def _quality(videos: list) -> dict:
    """Signals the renderer produced. Only counts videos that actually
    have a report — older ones predate it and would drag every rate
    toward zero if treated as clean."""
    reported = [v for v in videos if v.get("report")]
    if not reported:
        return {"reported": 0, "footage_repeated": 0, "footage_repeat_rate": 0.0,
                "similarity_flagged": 0, "similarity_flag_rate": 0.0,
                "footage_degraded": 0, "footage_degraded_rate": 0.0}

    repeated = sum(1 for v in reported if v["report"].get("footage_repeated"))
    degraded = sum(1 for v in reported if v["report"].get("footage_degraded"))
    flagged = sum(1 for v in reported
                  if (v["report"].get("similarity") or {}).get("flagged"))
    return {
        "reported": len(reported),
        "footage_repeated": repeated,
        "footage_repeat_rate": repeated / len(reported),
        # Videos whose footage was never scored because the matching call
        # failed. A rising number here means the matcher is unreliable,
        # which is invisible from the videos themselves.
        "footage_degraded": degraded,
        "footage_degraded_rate": degraded / len(reported),
        "similarity_flagged": flagged,
        "similarity_flag_rate": flagged / len(reported),
    }


def _film_costs(records: list) -> dict:
    """{(channel, film id): dollars} from the cost log: everything a film
    cost, its teasers included (decision 112). A film's cost isn't written
    beside its video the way a short's is, so it read as $0.00."""
    out = {}
    for r in records:
        if r.get("production") and r.get("channel_key"):
            key = (r["channel_key"], r["production"])
            out[key] = out.get(key, 0.0) + float(r.get("cost_usd") or 0)
    return out


def _outputs(videos: list, film_costs: dict) -> list:
    """What was made, as outputs: a short on its own, or a film with its
    teasers (one output, costed as one, decision 112). [{video, cost, published}]"""
    from core import production
    out = []
    for v in videos:
        report = v.get("report") or {}
        if report.get("teaser"):
            continue                      # counted with its film
        if gallery.is_long(v["relpath"]):
            found = production.film_of(gallery.OUTPUT_DIR / v["relpath"])
            if found and found in film_costs:
                out.append({"video": v, "cost": film_costs[found], "published": v["published"]})
                continue
        if v.get("cost") and v["cost"].get("calls"):
            out.append({"video": v, "cost": v["cost"]["total_usd"], "published": v["published"]})
    return out


def _spend(videos: list, channel_keys: set = None) -> dict:
    """Cost per generated video versus cost per *published* video.

    The second is the real number. If you throw away half of what you
    make, each published video costs twice what the generation log says —
    and that gap is invisible unless something computes it. A film and its
    teasers are one output (decision 112), and only the channels being
    looked at count.
    """
    from core import production
    records = costs.read_records()
    if channel_keys is not None:
        records = [r for r in records if r.get("channel_key") in channel_keys]
    film_costs = _film_costs(records)
    outputs = _outputs(videos, film_costs)
    made_films = {production.film_of(gallery.OUTPUT_DIR / o["video"]["relpath"]) for o in outputs
                  if gallery.is_long(o["video"]["relpath"])}
    # Films still being made: spent on, no video yet. Not a failure.
    in_progress = sum(usd for key, usd in film_costs.items() if key not in made_films
                      and production.state(production.load(*key), "video") not in ("ready", "approved"))
    costed = outputs
    attributed = sum(o["cost"] for o in outputs)
    published = [o for o in outputs if o["published"]]
    all_time = costs._summarize(records)

    # Spend on runs that produced no video at all — a crash after the
    # voiceover, a cancelled job. It is real money and the largest single
    # step (the voiceover) is usually already paid for by the time
    # anything downstream can fail, so hiding it would defeat the point
    # of this page.
    unattributed = max(0.0, all_time["total_usd"] - attributed - in_progress)

    return {
        "costed_videos": len(costed),
        # Everything ever spent, whether or not it produced a video.
        "total_usd": all_time["total_usd"],
        "attributed_usd": attributed,
        "unattributed_usd": unattributed,
        "in_progress_usd": in_progress,
        "per_video_usd": (attributed / len(costed)) if costed else 0.0,
        # Everything spent, divided by what actually went out.
        # (Not counting films still being made: they'll be outputs of their own.)
        "per_published_usd": ((all_time["total_usd"] - in_progress) / len(published)) if published else 0.0,
        "published_count": len(published),
        "all_time": all_time,
    }


def _audience(videos: list, limit: int = 30) -> dict:
    """How published videos are doing with viewers (core.audience).

    Medians rather than means: one video that happens to take off would
    otherwise say more about luck than about the channel. Percentage
    viewed is the one to watch for short-form; views follow it.
    """
    measured = [v for v in videos if v["published"] and v.get("stats")]
    rows = []
    for video in sorted(measured, key=lambda v: v["links"].get("published_at") or "",
                        reverse=True)[:limit]:
        stats = video["stats"]
        rows.append({
            "long": gallery.is_long(video["relpath"]),
            "film": _film_relpath(video),
            "name": video["title"],
            "channel": video["channel_name"],
            "channel_key": video["channel_key"],
            "relpath": video["relpath"],
            "published_at": (video["links"].get("published_at") or "")[:10],
            "url": video["links"].get("youtube_url"),
            "views": stats.get("views"),
            "likes": stats.get("likes"),
            "avg_view_percent": stats.get("avg_view_percent"),
            "avg_view_seconds": stats.get("avg_view_seconds"),
            "subscribers_gained": stats.get("subscribers_gained"),
        })

    def median(field):
        values = sorted(v["stats"][field] for v in measured
                        if isinstance(v["stats"].get(field), (int, float)))
        if not values:
            return None
        middle = len(values) // 2
        return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2

    longs = [r for r in rows if r["long"]]
    by_film = {r["relpath"]: r for r in longs}
    for r in longs:
        r["teasers"] = []
        r["watch_hours"] = ((r["views"] or 0) * (r["avg_view_seconds"] or 0)) / 3600
    shorts = []
    for r in rows:
        if r["long"]:
            continue
        if r["film"] in by_film:
            by_film[r["film"]]["teasers"].append(r)       # a teaser counts toward its film (decision 107)
        else:
            shorts.append(r)
    for r in longs:
        r["teaser_views"] = sum(t["views"] or 0 for t in r["teasers"])
    measured_long = [v for v in measured if gallery.is_long(v["relpath"])]
    measured_short = [v for v in measured if not gallery.is_long(v["relpath"])]
    return {
        "measured": len(measured),
        "published": sum(1 for v in videos if v["published"]),
        "median_views": median("views"),
        "median_view_percent": median("avg_view_percent"),
        "rows": rows,
        "longs": longs,
        "shorts": shorts,
        "long_views": sum(v["stats"].get("views") or 0 for v in measured_long),
        "long_hours": sum((v["stats"].get("views") or 0) * (v["stats"].get("avg_view_seconds") or 0)
                          for v in measured_long) / 3600,
        "long_median_percent": _median([v["stats"].get("avg_view_percent") for v in measured_long]),
        "short_views": sum(v["stats"].get("views") or 0 for v in measured_short),
        "short_median_percent": _median([v["stats"].get("avg_view_percent") for v in measured_short]),
    }


def _median(values):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def _film_relpath(video) -> str:
    """For a teaser short, its film's relpath (as list_videos gives it), else ""."""
    report = video.get("report") or {}
    rel = report.get("teaser_of_video")
    if not report.get("teaser") or not rel:
        return ""
    # The teaser's own relpath starts with its channel's folder; the film's sits under it too.
    channel_dir = video["relpath"].split("/")[0]
    return f"{channel_dir}/{rel}"


def _recent(videos: list, limit: int = 30) -> list:
    """Newest last, so a chart reads left to right in time order."""
    rows = []
    for video in videos[-limit:]:
        report = video.get("report") or {}
        rows.append({
            "name": video["title"],
            "channel": video["channel_name"],
            "relpath": video["relpath"],
            "channel_key": video["channel_key"],
            "mtime": video["mtime"],
            "state": ("discarded" if video["discarded"]
                      else "published" if video["published"] else "waiting"),
            "reason": video["links"].get("discard_reason"),
            "cost": (video.get("cost") or {}).get("total_usd"),
            "footage_repeated": bool(report.get("footage_repeated")),
            "footage_degraded": bool(report.get("footage_degraded")),
            "similarity_flagged": bool((report.get("similarity") or {}).get("flagged")),
        })
    return rows


def _by_channel(videos: list, channels: dict) -> list:
    rows = []
    # Everything the cost log has for the channel: a film's cost is never
    # beside its video, so summing the videos' own cost files showed Why,
    # Though?, the biggest spender, at $0 (28 Oct).
    spent = {}
    for r in costs.read_records():
        if r.get("channel_key"):
            spent[r["channel_key"]] = spent.get(r["channel_key"], 0.0) + float(r.get("cost_usd") or 0)
    for key, channel in channels.items():
        mine = [v for v in videos if v["channel_key"] == key]
        if not mine:
            continue
        discarded = sum(1 for v in mine if v["discarded"])
        rows.append({
            "key": key,
            "name": channel.channel_display_name,
            "total": len(mine),
            "published": sum(1 for v in mine if v["published"]),
            "discarded": discarded,
            "discard_rate": discarded / len(mine),
            "spend_usd": spent.get(key, 0.0),
        })
    rows.sort(key=lambda r: -r["total"])
    return rows


def headline(data: dict) -> str:
    """One sentence for the top of the page, chosen by what's most worth
    saying rather than always reporting the same metric."""
    totals = data["totals"]
    if not totals["total"]:
        return "Nothing generated yet."

    reasons = data["discard_reasons"]["rows"]
    if totals["discard_rate"] > 0.4:
        if reasons:
            top = reasons[0]
            return (f"{totals['discard_rate']:.0%} of videos are being discarded, "
                    f"most often because {top['label'].lower()}.")
        # A high discard rate with no reasons recorded is the worst of
        # both worlds: you know it's going badly and not why. Say that,
        # rather than reporting the keep rate as though it were news.
        return (f"{totals['discard_rate']:.0%} of videos are being discarded, and no "
                f"reasons have been recorded yet — so there's nothing to act on. "
                f"Discarding from the review queue starts capturing why.")
    if data["quality"]["footage_repeat_rate"] > 0.2:
        return (f"{data['quality']['footage_repeat_rate']:.0%} of recent videos "
                f"reused a footage clip — the library is stretched thin.")
    if totals["awaiting_review"] > 5:
        return f"{totals['awaiting_review']} videos are waiting to be reviewed."
    return (f"{totals['published']} published, "
            f"{totals['keep_rate']:.0%} of everything made was kept.")


# --- week by week (decision 139) ------------------------------------------------------
#
# The owner, 28 Oct: the page showed only the straight line to the targets,
# "but doesn't show the trajectory eg if my shorts a week ago were getting
# 10 views and this week they are getting 50 views then it's actually a
# marked improvement". Days swing with the schedule (nothing goes out on a
# Monday), so every comparison is a week with a week, and the week under
# way only with the same days of the one before.

WEEKS = 8
MEASURES = (("short_views", "Shorts views", "int"), ("per_short", "Views per Short out", "int"),
            ("long_views", "Long views", "int"), ("hours", "Watch hours", "hours"),
            ("subs", "Subscribers", "int"))


def _week_of(day: str):
    from datetime import date, timedelta
    d = date.fromisoformat(day)
    return d - timedelta(days=d.weekday())


def _sum_days(days: list) -> dict:
    return {"short_views": sum(d.get("short_views", 0) for d in days),
            "long_views": sum(d.get("long_views", 0) for d in days),
            "hours": round(sum(d.get("long_minutes", 0.0) for d in days) / 60, 1),
            "subs": sum(d.get("subs_net", 0) for d in days)}


def _change(now: float, before: float):
    """Percent change, or None when there's nothing to compare with."""
    if not before:
        return None
    return round((now - before) / abs(before) * 100)


def _weeks_of(days: list, out: list, today=None) -> dict:
    """{"weeks": [...], "so_far": {...}} from one or more channels' days
    (core.outlook.daily) and the videos that went out [(day, long)]."""
    from datetime import date, timedelta
    today = today or date.today()
    this_week = today - timedelta(days=today.weekday())
    starts = [this_week - timedelta(weeks=n) for n in range(WEEKS - 1, -1, -1)]
    by_week = {s: [] for s in starts}
    for d in days:
        s = _week_of(d["day"])
        if s in by_week:
            by_week[s].append(d)
    rows = []
    for s in starts:
        row = {"start": s.isoformat(), "label": s.strftime("%d %b").lstrip("0"), "partial": s == this_week,
               **_sum_days(by_week[s]),
               "shorts_out": sum(1 for day, long in out if not long and _week_of(day) == s),
               "long_out": sum(1 for day, long in out if long and _week_of(day) == s)}
        row["per_short"] = round(row["short_views"] / row["shorts_out"]) if row["shorts_out"] else 0
        rows.append(row)
    for prev, row in zip(rows, rows[1:]):
        # The week under way is compared day for day in `so_far`, never whole.
        row["change"] = {m: None if row["partial"] else _change(row[m], prev[m]) for m, _, _ in MEASURES}
    if rows:
        rows[0]["change"] = {m: None for m, _, _ in MEASURES}
    # The week under way against the same days of last week. YouTube's
    # figures run a day or two behind, so "the same days" are the days of
    # this week it has figures for.
    have = sorted({d["day"] for d in days if _week_of(d["day"]) == this_week})
    so_far = None
    if have:
        n = date.fromisoformat(have[-1]).weekday() + 1
        last_week = this_week - timedelta(weeks=1)
        now_days = [d for d in by_week[this_week] if date.fromisoformat(d["day"]).weekday() < n]
        then_days = [d for d in by_week.get(last_week, []) if date.fromisoformat(d["day"]).weekday() < n]
        a, b = _sum_days(now_days), _sum_days(then_days)
        for part, chosen, week in ((a, now_days, this_week), (b, then_days, last_week)):
            shorts = sum(1 for day, long in out if not long and _week_of(day) == week
                         and date.fromisoformat(day).weekday() < n)
            part["per_short"] = round(part["short_views"] / shorts) if shorts else 0
        so_far = {"days": n, "through": date.fromisoformat(have[-1]).strftime("%a"),
                  "now": a, "then": b, "change": {m: _change(a[m], b[m]) for m, _, _ in MEASURES}}
    else:
        # No figures for this week yet: the last full week against the one before.
        full = [r for r in rows if not r["partial"]]
        if len(full) >= 2:
            so_far = {"days": 7, "through": "", "now": {m: full[-1][m] for m, _, _ in MEASURES},
                      "then": {m: full[-2][m] for m, _, _ in MEASURES}, "change": full[-1]["change"]}
    peak = {m: max([r[m] for r in rows] + [0]) for m, _, _ in MEASURES}
    return {"weeks": rows, "so_far": so_far, "peak": peak}


def weekly(channels: dict, today=None) -> dict:
    """Week by week for these channels, together and one by one:
    {"total": {...}, "channels": [{"key", "name", **}], "measures",
    "error"}. Read from YouTube's day-by-day figures (core.outlook, cached
    twelve hours); a channel without a connection that can read them is
    left out."""
    from core import outlook, youtube
    every, out_all, per, errors = [], [], [], []
    for key, channel in channels.items():
        try:
            if not youtube.connection(key).get("stats"):
                continue
            figures = outlook.daily(key)
        except Exception as exc:  # noqa: BLE001 - one channel's figures mustn't take the page down
            errors.append(f"{channel.channel_display_name or key}: {getattr(exc, 'user_message', '') or exc}")
            continue
        if figures.get("error"):
            errors.append(f"{channel.channel_display_name or key}: {figures['error']}")
        days = figures.get("days") or []
        out = []
        for v in gallery.list_videos(channel.output_dir):
            stamp = (v.get("links") or {}).get("published_at")
            if stamp and not v["discarded"]:
                out.append((stamp[:10], gallery.is_long(v["relpath"])))
        every += days
        out_all += out
        per.append({"key": key, "name": channel.channel_display_name or key, **_weeks_of(days, out, today)})
    merged = {}
    for d in every:
        m = merged.setdefault(d["day"], {"day": d["day"], "short_views": 0, "long_views": 0,
                                         "long_minutes": 0.0, "subs_net": 0})
        for f in ("short_views", "long_views", "long_minutes", "subs_net"):
            m[f] += d.get(f, 0)
    return {"total": _weeks_of(sorted(merged.values(), key=lambda d: d["day"]), out_all, today),
            "channels": per, "measures": MEASURES, "error": "; ".join(errors)}
