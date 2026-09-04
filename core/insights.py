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
    purged = [r for r in gallery.purged_records()
              if not channel_keys or r.get("channel") in channel_keys]

    return {
        "totals": _totals(videos, purged),
        "discard_reasons": _discard_reasons(videos, purged),
        "quality": _quality(videos),
        "spend": _spend(videos),
        "recent": _recent(videos, limit=30),
        "by_channel": _by_channel(videos, channels),
        "video_count": len(videos),
        "purged_count": len(purged),
    }


def _totals(videos: list, purged: list = ()) -> dict:
    total = len(videos) + len(purged)
    discarded = sum(1 for v in videos if v["discarded"]) + len(purged)
    published = sum(1 for v in videos if v["published"])
    kept = total - discarded
    return {
        "total": total,
        "published": published,
        "discarded": discarded,
        "awaiting_review": kept - published,
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


def _spend(videos: list) -> dict:
    """Cost per generated video versus cost per *published* video.

    The second is the real number. If you throw away half of what you
    make, each published video costs twice what the generation log says —
    and that gap is invisible unless something computes it.
    """
    costed = [v for v in videos if v.get("cost") and v["cost"].get("calls")]
    attributed = sum(v["cost"]["total_usd"] for v in costed)
    published = [v for v in costed if v["published"]]
    all_time = costs.summary_all()

    # Spend on runs that produced no video at all — a crash after the
    # voiceover, a cancelled job. It is real money and the largest single
    # step (the voiceover) is usually already paid for by the time
    # anything downstream can fail, so hiding it would defeat the point
    # of this page.
    unattributed = max(0.0, all_time["total_usd"] - attributed)

    return {
        "costed_videos": len(costed),
        # Everything ever spent, whether or not it produced a video.
        "total_usd": all_time["total_usd"],
        "attributed_usd": attributed,
        "unattributed_usd": unattributed,
        "per_video_usd": (attributed / len(costed)) if costed else 0.0,
        # Everything spent, divided by what actually went out.
        "per_published_usd": (all_time["total_usd"] / len(published)) if published else 0.0,
        "published_count": len(published),
        "all_time": all_time,
    }


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
    for key, channel in channels.items():
        mine = [v for v in videos if v["channel_key"] == key]
        if not mine:
            continue
        discarded = sum(1 for v in mine if v["discarded"])
        costed = [v for v in mine if v.get("cost") and v["cost"].get("calls")]
        rows.append({
            "key": key,
            "name": channel.channel_display_name,
            "total": len(mine),
            "published": sum(1 for v in mine if v["published"]),
            "discarded": discarded,
            "discard_rate": discarded / len(mine),
            "spend_usd": sum(v["cost"]["total_usd"] for v in costed),
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
