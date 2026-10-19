"""
Where the ElevenLabs allowance goes, and what to change when it won't
last (decision 120).

The owner, as the allowance ran low: it was "really difficult to tell how
much a channel uses, what the average voice per video is", whether a
film's teasers counted, how a schedule change would affect the total,
and "which videos are pre made and which will actually spend the
remaining elevenlabs budget". Money showed one bar and a verdict.

This works out the billing month as blocks, one per output:

- **Spent:** every voice charge since the allowance last reset, from the
  cost log. A film's teasers are part of its block, since a film and its
  teasers are one output (decision 112). A short is matched to its video
  by its voice cost, so its block has a title and says whether the video
  went out, waits, or was discarded.
- **Still to come**, until the reset, per channel. For shorts, the slots
  left plus the buffer the generator keeps, less the videos already made.
  For films, those being made (their exact narration once scripted), the
  teasers still to make, and the films the autopilot will start: one for
  each that goes out, plus any room in its bank.
- **Suggestions** that would close a shortfall, cheapest in views first:
  each says what it saves before the reset. A settings change can be
  applied in one click.

Everything is in credits at the account's measured credits per character
(core.voice_quota). An estimate is marked as one.
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from core import costs, gallery, voice_quota
from core.logging_setup import get_logger

log = get_logger(__name__)

DAY = 86400
# Until a channel has history: a film's narration and its teasers', in
# characters (Why, Though?'s first films), and a short's.
FILM_CHARS = 7000
TEASER_CHARS = 1500
SHORT_CHARS = voice_quota.DEFAULT_VIDEO_CHARACTERS
# The validated categorical palette's dark steps, in fixed order (decision
# 120): a channel keeps its colour however many are shown.
SERIES = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767")
# ElevenLabs' next plan up, for the suggestion to upgrade: check its page.
UPGRADE = {"name": "Creator", "credits": 100_000, "usd": 22.0, "url": "https://elevenlabs.io/app/subscription"}


def _cycle_start(resets_at: float) -> float:
    """When the allowance last reset: the same day and time a month before
    the next reset."""
    nxt = datetime.fromtimestamp(resets_at)
    year, month = (nxt.year, nxt.month - 1) if nxt.month > 1 else (nxt.year - 1, 12)
    for day in (nxt.day, 30, 29, 28):
        try:
            return nxt.replace(year=year, month=month, day=day).timestamp()
        except ValueError:
            continue
    return resets_at - 30 * DAY


_seeds = {}


def _seed(job_id: str) -> dict:
    """A job's seed, while its record is kept (about a week)."""
    if not job_id:
        return {}
    if job_id not in _seeds:
        from core import jobs
        try:
            _seeds[job_id] = json.loads(jobs._record_path(job_id).read_text(encoding="utf-8")).get("seed") or {}
        except (OSError, ValueError):
            _seeds[job_id] = {}
    return _seeds[job_id]


def _voice_records(records: list) -> list:
    return [r for r in records if r.get("service") == "elevenlabs"]


# --- what a video takes -------------------------------------------------------------

def typical(channel_key: str, records: list) -> dict:
    """Characters one output of this channel typically takes: {"film" (its
    narration), "teasers" (all of a film's), "short", "long"}, from what it
    has actually used, retries included."""
    films, teasers, shorts, longs = {}, {}, {}, {}
    for r in _voice_records(records):
        if r.get("channel_key") != channel_key or r.get("operation") != "voiceover":
            continue
        chars = r.get("characters") or 0
        if r.get("production"):
            stage = _seed(r.get("job_id")).get("stage")
            into = teasers if stage == "teasers" else films
            into[r["production"]] = into.get(r["production"], 0) + chars
        elif r.get("job_id"):
            into = longs if _seed(r["job_id"]).get("type") == "longform" else shorts
            into[r["job_id"]] = into.get(r["job_id"], 0) + chars

    def median(values, floor, default):
        kept = [v for v in values if v >= floor]
        return int(statistics.median(kept)) if kept else default
    short = median(shorts.values(), 100, SHORT_CHARS)
    return {"film": median([v for k, v in films.items() if k not in teasers or v > 3000], 3000, FILM_CHARS),
            "teasers": median(teasers.values(), 200, TEASER_CHARS),
            "short": short, "long": median(longs.values(), 100, short)}


# --- what's been spent --------------------------------------------------------------

def _state(info: dict) -> str:
    if info.get("discarded"):
        return "discarded"
    if gallery.is_out(info):
        return "out"
    if gallery.is_queued(info):
        return "queued"
    return "in review"


def _videos_by_voice_cost(channel, since: float) -> dict:
    """{voice cost rounded: video path} for the channel's videos made since
    `since`: how a short's job is matched to its video once the job's own
    record is gone."""
    out = {}
    directory = gallery.resolve_output_dir(channel.output_dir)
    if not directory.exists():
        return out
    for video in gallery.videos_in(directory):
        try:
            if video.stat().st_mtime < since - 2 * DAY:
                continue
            cost = json.loads(video.with_name(f"{video.stem}_cost.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        usd = (cost.get("by_operation") or {}).get("elevenlabs:voiceover")
        if usd:
            out[round(usd, 6)] = video
    return out


def _film_video(channel, sid: str):
    from core import production
    try:
        data = production.load(channel.key, sid)
    except Exception:  # noqa: BLE001 - a missing production is a film with no video yet
        return None, {}
    return production.video_file(channel, data), data


def spent(channels: dict, records: list, since: float, ratio: float) -> list:
    """Blocks for every voice charge since `since`, one per output."""
    groups = {}
    for r in _voice_records(records):
        if r.get("ts", 0) < since:
            continue
        key = r.get("channel_key") or ""
        if r.get("production"):
            g = (key, "film", r["production"])
        elif r.get("job_id"):
            g = (key, "job", r["job_id"])
        else:
            g = (key, "loose", "")
        entry = groups.setdefault(g, {"chars": 0, "usd": 0.0, "last": 0.0, "first": r.get("ts", 0),
                                      "teaser_chars": 0})
        entry["chars"] += r.get("characters") or 0
        entry["usd"] += r.get("cost_usd") or 0.0
        entry["last"] = max(entry["last"], r.get("ts", 0))
        entry["first"] = min(entry["first"], r.get("ts", 0))
        if r.get("production") and _seed(r.get("job_id")).get("stage") == "teasers":
            entry["teaser_chars"] += r.get("characters") or 0

    from core import curriculum
    matched = {}
    blocks = []
    for (key, kind, ident), g in groups.items():
        channel = channels.get(key)
        credits = round(g["chars"] * ratio)
        if not credits:
            continue
        block = {"channel": key, "credits": credits, "voiced": g["last"], "spent": True, "estimate": False,
                 "release": None}
        if kind == "film" and channel is not None:
            row = curriculum.find(key, ident) or {}
            video, _ = _film_video(channel, ident)
            info = gallery.load_publish_info(video) if video is not None and video.exists() else None
            block.update(kind="film", label=row.get("title") or ident,
                         state=_state(info) if info else "being made",
                         teasers=round(g["teaser_chars"] * ratio), video=str(video) if info else "")
        elif kind == "job" and channel is not None:
            if key not in matched:
                matched[key] = _videos_by_voice_cost(channel, since)
            video = matched[key].get(round(g["usd"], 6))
            seed = _seed(ident)
            if video is not None:
                info = gallery.load_publish_info(video)
                block.update(kind="long" if gallery.is_long(video) else "short",
                             label=info.get("title") or video.stem.replace("_", " "), state=_state(info),
                             video=str(video))
            else:
                block.update(kind="long" if seed.get("type") == "longform" else "short",
                             label=seed.get("topic") or "A video", state="no video", video="")
        else:
            # Stages run by hand, before they recorded their channel (11 to
            # 13 Oct), can't be put to one.
            span = _day(g["first"]) + ("" if _day(g["first"]) == _day(g["last"]) else f" to {_day(g['last'])}")
            block.update(kind="other", label=f"Run by hand, {span}" + ("" if channel else ": no channel recorded"),
                         state="other", video="")
        blocks.append(block)
    return blocks


# --- what's still to come -----------------------------------------------------------

def _slots(plan, now: float, until: float, long: bool = False) -> list:
    """Slot times from now until `until`; with `long`, the plan's long lane."""
    from types import SimpleNamespace
    from core import publish_queue
    if long:
        plan = SimpleNamespace(slots=plan.long_slots, weekdays=plan.long_weekdays)
    found = publish_queue.upcoming_slots(plan, datetime.fromtimestamp(now).astimezone(), 400)
    return [s.timestamp() for s in found if s.timestamp() < until]


def _made_ahead(channel, long: bool) -> int:
    counts = gallery.video_state_counts(channel.output_dir, long=long)
    return counts.get("queued", 0) + counts.get("waiting", 0)


def _shorts_to_come(channel, typ: dict, ratio: float, now: float, until: float) -> tuple:
    from core import publish_queue
    blocks, made, short_ready = [], 0, 0
    lanes = [(False, "short", channel.publishing.buffer)]
    if channel.format == "quiz":
        lanes.append((True, "long", 1))        # a quiz night is kept waiting (scheduler.fill_long_quizzes)
    for long, kind, keep in lanes:
        slots = _slots(publish_queue._lane(channel, long), now, until)
        ready = _made_ahead(channel, long)
        made += ready
        if not long:
            short_ready = ready
        for i in range(max(0, len(slots) + int(keep) - ready)):
            at = ready + i
            when = slots[at] if at < len(slots) else None
            blocks.append({"channel": channel.key, "kind": kind, "spent": False, "estimate": True,
                           "credits": round(typ[kind] * ratio), "release": when, "state": "to make",
                           "label": ("Short" if kind == "short" else "Long quiz")
                           + (f" for {datetime.fromtimestamp(when):%a %d %b %H:%M}" if when else " kept ready")})
    return blocks, made, short_ready


def _films_to_come(channel, typ: dict, ratio: float, now: float, until: float) -> tuple:
    from core import curriculum, production, publish_queue, storyboard
    doc = channel.documentary
    teasers = round(typ["teasers"] * ratio) if int(doc.teasers) > 0 else 0
    blocks, making, banked = [], 0, 0
    for data in production.all_for(channel.key):
        row = curriculum.find(channel.key, data["subtopic_id"])
        if row is None or row.get("status") == curriculum.SKIPPED:
            continue
        video = production.state(data, "video")
        left = production.narration_still_to_voice(data)
        title = row.get("title") or data["subtopic_id"]
        if video in ("ready", "approved"):
            made = production.video_file(channel, data)
            info = gallery.load_publish_info(made) if made is not None and made.exists() else None
            if info is None or info["discarded"]:
                continue
            if not gallery.is_out(info):
                banked += 1
            if teasers and not (data.get("teasers") or {}).get("videos"):
                blocks.append({"channel": channel.key, "kind": "film", "spent": False, "estimate": not left,
                               "credits": round(left * ratio) if left else teasers, "release": None,
                               "state": "teasers to make", "label": f"{title}: its teasers"})
        elif production.state(data, "outline") != "todo" and video != "working":
            making += 1
            narration = round(left * ratio) if left else round(typ["film"] * ratio)
            blocks.append({"channel": channel.key, "kind": "film", "spent": False, "estimate": not left,
                           "credits": narration + teasers, "teasers": teasers, "release": None,
                           "state": "being made", "label": title})
    slots = _slots(publish_queue._lane(channel, True), now, until)
    room = max(0, int(doc.parallel) + int(doc.ahead) - making - banked)
    new = len(slots) + room
    upcoming = storyboard.upcoming(channel, count=new) if new else []
    for i in range(new):
        title = upcoming[i]["title"] if i < len(upcoming) else "A new film"
        blocks.append({"channel": channel.key, "kind": "film", "spent": False, "estimate": True,
                       "credits": round(typ["film"] * ratio) + teasers, "teasers": teasers, "release": None,
                       "state": "to make", "label": title})
    # Films go out in order: those made, then those being made, then new.
    order = [b for b in blocks if b["state"] != "teasers to make"]
    for i, b in enumerate(order):
        at = banked + i
        b["release"] = slots[at] if at < len(slots) else None
    return blocks, banked, {"slots": len(slots), "room": room, "making": making}


def to_come(channels: dict, records: list, ratio: float, now: float, until: float) -> tuple:
    """(blocks, {channel: facts}) for what each running channel will still
    voice before `until`."""
    blocks, facts = [], {}
    for key, channel in channels.items():
        if channel.archived or not channel.publishing.enabled:
            continue
        typ = typical(key, records)
        if channel.format == "documentary":
            found, made, extra = _films_to_come(channel, typ, ratio, now, until)
        else:
            found, made, ready = _shorts_to_come(channel, typ, ratio, now, until)
            extra = {"short_ready": ready}
        blocks += found
        facts[key] = {"typical": {k: round(v * ratio) for k, v in typ.items()}, "made_ahead": made, **extra}
    return blocks, facts


# --- what to change -----------------------------------------------------------------

def _views_per_video(channel) -> float:
    """Views a video of this channel has had, on average, over its last ten
    published: what a video not made would likely have got."""
    directory = gallery.resolve_output_dir(channel.output_dir)
    found = []
    if directory.exists():
        for video in gallery.videos_in(directory):
            stats = gallery.load_stats(video) or {}
            if stats.get("views") is not None:
                found.append((video.stat().st_mtime, stats["views"]))
    found = [v for _, v in sorted(found)[-10:]]
    return statistics.mean(found) if found else 0.0


def suggestions(channels: dict, blocks: list, facts: dict, gap: int, now: float, until: float) -> list:
    """Ways to close a shortfall of `gap` credits before `until`, the ones
    costing fewest views first; those that together close it are marked
    `pick`. Each: {"id", "channel", "text", "saves", "views", "apply" or
    "url"}."""
    from core import publish_queue
    out = []
    upcoming = {k: [b for b in blocks if b["channel"] == k and not b["spent"]] for k in facts}
    for key, f in facts.items():
        channel = channels[key]
        name = channel.channel_display_name or key
        per_view = _views_per_video(channel)
        typ = f["typical"]
        if channel.format == "documentary":
            doc = channel.documentary
            film = typ["film"] + (typ["teasers"] if int(doc.teasers) > 0 else 0)
            if int(doc.ahead) > 1 and f.get("room"):
                fewer = min(f["room"], int(doc.ahead) - 1)
                out.append({"channel": key, "text": f"{name}: keep 1 finished film in hand, not {doc.ahead}",
                            "saves": fewer * film, "views": 0, "apply": {"ahead": 1}})
            if int(doc.teasers) > 1:
                films = len(upcoming[key])
                out.append({"channel": key, "text": f"{name}: 1 teaser a film, not {doc.teasers}",
                            "saves": round(films * typ["teasers"] * (int(doc.teasers) - 1) / int(doc.teasers)),
                            "views": 0, "apply": {"teasers": 1}})
            days = sorted(channel.publishing.long_weekdays)
            if len(days) > 1:
                kept = days[:-1]
                lost = f["slots"] - len(_slots(_with(channel.publishing, long_weekdays=kept), now, until, long=True))
                if lost > 0:
                    out.append({"channel": key, "text": f"{name}: films on {_days(kept)}, not {_days(days)}",
                                "saves": lost * film, "views": round(lost * per_view),
                                "apply": {"long_weekdays": kept}})
            continue
        short = typ["short"]
        buffer, ready = int(channel.publishing.buffer), f.get("short_ready", 0)

        def to_make(slots_left: int, keep: int = buffer) -> int:
            # Videos made ahead fill the first slots; only the rest are voiced.
            return max(0, slots_left + keep - ready)
        slots = sorted(channel.publishing.slots)
        base = len(_slots(channel.publishing, now, until))
        if len(slots) > 1:
            kept = slots[:1]
            fewer = to_make(base) - to_make(len(_slots(_with(channel.publishing, slots=kept), now, until)))
            out.append({"channel": key, "text": f"{name}: one a day at {kept[0]}, not {len(slots)} a day",
                        "saves": fewer * short, "views": round(fewer * per_view), "apply": {"slots": kept}})
        days = sorted(channel.publishing.weekdays)
        if len(days) > 4:
            kept = [d for d in (0, 2, 4, 6) if d in days] or days[:4]
            fewer = to_make(base) - to_make(len(_slots(_with(channel.publishing, weekdays=kept), now, until)))
            out.append({"channel": key, "text": f"{name}: {_days(kept)} only, not every day",
                        "saves": fewer * short, "views": round(fewer * per_view), "apply": {"weekdays": kept}})
        if buffer > 1:
            fewer = to_make(base) - to_make(base, 1)
            out.append({"channel": key, "text": f"{name}: keep 1 video ready, not {buffer}",
                        "saves": fewer * short, "views": 0, "apply": {"buffer": 1}})
    out = [s for s in out if s["saves"] > 0]
    out.sort(key=lambda s: (s["views"] / max(1, s["saves"]), -s["saves"]))
    left = gap
    for i, s in enumerate(out):
        s["id"] = i
        s["pick"] = left > 0
        if left > 0:
            left -= s["saves"]
    return out


def _with(plan, **changes):
    from types import SimpleNamespace
    fields = {"slots": plan.slots, "weekdays": plan.weekdays,
              "long_slots": plan.long_slots, "long_weekdays": plan.long_weekdays}
    fields.update(changes)
    return SimpleNamespace(**fields)


def _days(days: list) -> str:
    names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    return ", ".join(names[d] for d in sorted(days))


# --- one change, applied ------------------------------------------------------------

ALLOWED = {"slots": list, "weekdays": list, "long_weekdays": list, "buffer": int, "ahead": int, "teasers": int}


def apply(channel_key: str, change: dict) -> None:
    """A suggestion's settings change, saved to the channel."""
    from core.channels import load_channels, save_channel
    from core.errors import PipelineError
    channel = load_channels(validate=False).get(channel_key)
    if channel is None:
        raise PipelineError(f"no channel {channel_key}", user_message="No such channel.")
    for name, value in change.items():
        if name not in ALLOWED or not isinstance(value, ALLOWED[name]):
            raise PipelineError(f"not a voice change: {name}={value!r}", user_message="That change can't be made here.")
        target = channel.documentary if name in ("ahead", "teasers") else channel.publishing
        setattr(target, name, value)
    save_channel(channel)
    log.info(f"{channel_key}: voice budget change applied: {change}")


# --- dates, for sorting and the page ------------------------------------------------

def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%a %d %b").replace(" 0", " ")


def _published_at(info: dict) -> float:
    stamp = info.get("published_at") or ""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _dates(channels: dict, done: list, coming: list, resets: float) -> None:
    """Each block's release, where it has one, as `when` (what sorting by
    date goes by) and a few words."""
    from core import publish_queue
    slots = {}
    for b in done:
        when = None
        if b.get("video") and b["state"] == "out":
            when = _published_at(gallery.load_publish_info(Path(b["video"]))) or None
        elif b.get("video") and b["state"] == "queued" and b["channel"] in channels:
            if b["channel"] not in slots:
                try:
                    slots[b["channel"]] = {str(Path(v).resolve()): w for v, w in
                                           publish_queue.schedule_for(channels[b["channel"]])}
                except Exception:  # noqa: BLE001 - without its slot it sorts by when it was voiced
                    slots[b["channel"]] = {}
            at = slots[b["channel"]].get(str(Path(b["video"]).resolve()))
            when = at.timestamp() if at else None
        b["release"] = when
        b["when"] = when or b["voiced"]
        b["when_label"] = ((("out " if b["state"] == "out" else "goes out ") + _day(when)) if when
                           else f"voiced {_day(b['voiced'])}")
    for b in coming:
        b["when"] = b["release"] or resets + 1
        b["when_label"] = f"goes out {_day(b['release'])}" if b["release"] else f"after {_day(resets)}"


# --- the whole picture --------------------------------------------------------------

def picture(channels: dict = None, now: float = None) -> dict | None:
    """Everything the Voice page shows, or None when ElevenLabs won't say."""
    from core.channels import load_channels
    quota = voice_quota.current()
    if quota is None or not quota.resets_at:
        return None
    now = now or time.time()
    channels = channels if channels is not None else load_channels(validate=False)
    records = costs.read_records()
    since = _cycle_start(float(quota.resets_at))
    ratio = voice_quota.credits_per_character()
    # This month's own rate where the log covers it: the blocks then add up
    # to what ElevenLabs says was used, not a little over.
    chars = sum(r.get("characters") or 0 for r in _voice_records(records) if r.get("ts", 0) >= since)
    if chars and chars * ratio > quota.used:
        ratio = quota.used / chars
    done = spent(channels, records, since, ratio)
    logged = sum(b["credits"] for b in done)
    if quota.used > logged + 50:
        done.append({"channel": "", "kind": "other", "label": "Not in this app's log", "credits": quota.used - logged,
                     "spent": True, "estimate": False, "voiced": since, "release": None, "state": "other",
                     "video": ""})
    coming, facts = to_come(channels, records, ratio, now, float(quota.resets_at))
    shown = [k for k in channels if not channels[k].archived]
    colour = {k: SERIES[i % len(SERIES)] for i, k in enumerate(shown)}
    rows = []
    for key in shown:
        mine = [b for b in done + coming if b["channel"] == key]
        if not mine and key not in facts:
            continue
        rows.append({"key": key, "name": channels[key].channel_display_name or key, "colour": colour[key],
                     "spent": sum(b["credits"] for b in mine if b["spent"]),
                     "wasted": sum(b["credits"] for b in mine if b["spent"] and b["state"] in ("discarded", "no video")),
                     "coming": sum(b["credits"] for b in mine if not b["spent"]),
                     "videos_coming": sum(1 for b in mine if not b["spent"]),
                     **(facts.get(key) or {"typical": {}, "made_ahead": 0})})
    need = sum(b["credits"] for b in coming)
    gap = max(0, need - quota.remaining)
    _dates(channels, done, coming, float(quota.resets_at))
    for b in done + coming:
        b["colour"] = colour.get(b["channel"], "#8b8a85")
        b["name"] = channels[b["channel"]].channel_display_name if b["channel"] in channels else "Other"
        b["order"] = shown.index(b["channel"]) if b["channel"] in shown else len(shown)
    return {"used": quota.used, "limit": quota.limit, "remaining": quota.remaining,
            "resets": float(quota.resets_at), "since": since, "ratio": ratio,
            "resets_label": _day(float(quota.resets_at)),
            "days_left": max(0, int((float(quota.resets_at) - now) / DAY)),
            "spent": sorted(done, key=lambda b: b["voiced"]), "coming": coming, "need": need, "gap": gap,
            "rows": rows, "suggestions": suggestions(channels, coming, facts, gap, now, float(quota.resets_at))
            if gap else [], "upgrade": UPGRADE}
