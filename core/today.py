"""
The home page: what needs you, and what's running by itself (decision 067).

The app used to be organised around what it contains (channels, footage,
facts, APIs) and left it to the owner to remember what to do next. A
YouTube connection died on 1 Oct and the only sign was a line on
Insights. A channel sat at "make and approve a first video" for twelve
days, and a draft channel sat unread. This gathers everything the owner
has to act on, from wherever it's known, into one ordered list. Each
item has one button that does the thing, and stays until the state
behind it changes. Nothing is dismissed by hand, so nothing is forgotten.

Each source is read on its own. One that fails is reported as an item
itself ("couldn't check X"), never left out silently, and never stops the
rest of the page.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from core import gallery
from core.logging_setup import get_logger

log = get_logger(__name__)

BAD, WARN, INFO = "bad", "warn", "info"
ORDER = {BAD: 0, WARN: 1, INFO: 2}
DAY = 86400

STALLED_DAYS = 3            # a setting-up channel untouched this long is mentioned
RUNWAY_WARN_DAYS = 7        # money or voice running out sooner than this
DRAFT_DAYS = 1              # a draft channel waiting this long is mentioned


@dataclass
class Item:
    severity: str
    title: str
    detail: str = ""
    action: str = ""         # the button
    url: str = ""            # where it goes (a page, or an outside billing page)
    post: bool = False       # the button is a form post (archive, retry)
    outside: bool = False    # opens another site
    extra: list = field(default_factory=list)   # [(label, url, post)] more buttons


def _age_days(stamp: float, now: float) -> int:
    return int((now - stamp) / DAY) if stamp else 0


def needs_you(channels: dict, url_for, now: float = None, forecast: dict = None) -> list:
    """Everything waiting on the owner, worst first. `url_for` is Flask's,
    passed in so this stays out of the web layer."""
    now = now or time.time()
    items = []
    for name, source in (("YouTube connections", _connections), ("money", _money),
                         ("review", _review), ("failed videos", _failed), ("topic plans", _topics),
                         ("setup", _setup), ("drafts", _drafts), ("quiz categories", _categories)):
        try:
            items += source(channels, url_for, now, forecast)
        except Exception as exc:  # noqa: BLE001 - one source mustn't hide the rest; reported as an item
            log.warning(f"Today: couldn't check {name}: {exc}")
            items.append(Item(WARN, f"Couldn't check {name}", "The details are in the log."))
    return sorted(items, key=lambda i: ORDER[i.severity])


def _connections(channels, url_for, now, forecast) -> list:
    from core import youtube
    out = []
    for key, channel in channels.items():
        if channel.archived:
            continue
        connection = youtube.connection(key)
        name = channel.channel_display_name or key
        if connection["expired"]:
            slots = _next_slot(channel, now)
            out.append(Item(BAD, f"{name} can't upload to YouTube",
                            "Google rejected its connection." + (f" Next slot {slots}." if slots else "")
                            + " If this happens weekly, publish the Google consent screen (TASKS step 7).",
                            "Reconnect", url_for("youtube.connect", key=key), outside=True))
        elif connection["connected"] and not connection["stats"]:
            out.append(Item(INFO, f"Reconnect {name} once to read its numbers",
                            "It can upload, but views and retention need the newer permission.",
                            "Reconnect", url_for("youtube.connect", key=key), outside=True))
    return out


def _next_slot(channel, now) -> str:
    from core import publish_queue
    if not channel.publishing.enabled or not channel.publishing.slots:
        return ""
    upcoming = publish_queue.upcoming_slots(channel.publishing, datetime.fromtimestamp(now).astimezone(), 1)
    return upcoming[0].strftime("%a %d %b %H:%M") if upcoming else ""


def _money(channels, url_for, now, forecast) -> list:
    if forecast is None:
        return []
    out = []
    claude = forecast.get("claude")
    if forecast.get("claude_balance") is None:
        out.append(Item(INFO, "Tell the app your Claude balance",
                        "Then it can say how long the credit lasts.", "Money", url_for("money.page")))
    elif claude and claude["days"] is not None and claude["days"] < RUNWAY_WARN_DAYS:
        left = forecast["claude_balance"]
        out.append(Item(BAD if claude["days"] < 3 else WARN,
                        f"Claude credit: ${left:.2f} left, about {claude['days']:.0f} days",
                        "When it runs out, every script and check fails. Top up, then enter the new balance.",
                        "Billing", "https://console.anthropic.com/settings/billing", outside=True,
                        extra=[("Enter balance", url_for("money.page") + "#balances", False)]))
    voice = forecast.get("voice")
    if voice and voice.get("runs_out") and not _spending_spare(voice, now):
        days = (voice["runs_out"] - datetime.fromtimestamp(now).date()).days
        out.append(Item(WARN if days > 2 else BAD,
                        f"Voice allowance short by {voice['short_by']:,} credits before "
                        f"{voice['resets'].strftime('%d %b')}",
                        f"The schedule still has {voice['videos_needed']} video"
                        f"{'s' if voice['videos_needed'] != 1 else ''} to voice before then "
                        f"({voice['needed']:,} credits) and {voice['remaining']:,} are left. Upgrade the "
                        "plan, or make fewer a week.",
                        "Money", url_for("money.page")))
    elif voice and voice.get("schedule_need", 0) > voice["limit"]:
        out.append(Item(WARN, "The voice allowance won't cover a month of this schedule",
                        f"It needs about {voice['schedule_need']:,} credits a month against {voice['limit']:,}. "
                        "Upgrade the plan, or make fewer shorts a week.", "Money", url_for("money.page")))
    return out


def _spending_spare(voice: dict, now: float) -> bool:
    """Whether the allowance is in the days before its reset when what's
    left is spent on purpose (core.spare_voice): running low then is the
    plan, not news."""
    from core import money, spare_voice
    resets = voice.get("resets")
    if not resets or not money.settings().get("spare_voice", True):
        return False
    days = (resets - datetime.fromtimestamp(now).date()).days
    return days <= spare_voice.WINDOW_DAYS


def _review(channels, url_for, now, forecast) -> list:
    out = []
    for key, channel in channels.items():
        if channel.archived:
            continue
        waiting = gallery.video_state_counts(channel.output_dir)["waiting"]
        if waiting:
            name = channel.channel_display_name or key
            out.append(Item(INFO, f"{waiting} {name} video{'s' if waiting != 1 else ''} to review", "",
                            "Review", url_for("review.queue", channel=key)))
    return out


GENERIC_ERROR = "Something went wrong while generating this video."


def failure_detail(job: dict, now: float) -> str:
    """What failed, when, and what it was doing: the owner saw only
    "A Minute Pastor video didn't finish" and a link to Activity, which no
    longer listed it."""
    from datetime import datetime
    seed = job.get("seed") or {}
    what = seed.get("reference") or seed.get("topic") or "A video"
    when = job.get("finished_at") or job.get("queued_at") or now
    days = _age_days(when, now)
    stamp = datetime.fromtimestamp(when).strftime("%a %d %b, %H:%M")
    error = (job.get("error") or "").strip()
    if not error or error.startswith(GENERIC_ERROR) or job.get("status") == "interrupted":
        doing = _last_step(job)
        error = (f"It stopped while {doing}" if doing else "It stopped part-way") + (
            ", most likely when the app restarted." if job.get("status") == "interrupted" else ".")
    return f"{what}, {stamp}{f' ({days} days ago)' if days > 1 else ''}. {error[:220]} " \
           f"Retry carries on from what it had made; Discard drops it."


def _last_step(job: dict) -> str:
    """The last stage it reported, as words ("preparing the background clips")."""
    from core import jobs
    for line in reversed(jobs.read_log(job["id"], tail=40)):
        text = line.strip()
        if text.startswith("[") and "/5]" in text[:6]:
            return text.split("]", 1)[1].strip().rstrip(".").rstrip("…").lower()
    return ""


def _made_since(channel, job: dict) -> bool:
    """A video of the same quote or plan entry has been finished since:
    the failure is history, not something to do."""
    from core import gallery
    seed = job.get("seed") or {}
    name = seed.get("reference") or seed.get("topic") or ""
    if not name:
        return False
    from core.paths import slugify
    stem = slugify(name, fallback="")
    directory = gallery.resolve_output_dir(channel.output_dir)
    if not stem or not directory.exists():
        return False
    since = job.get("finished_at") or 0
    return any(v.stem.startswith(stem) and v.stat().st_mtime > since
               for v in gallery.videos_in(directory))


def _failed(channels, url_for, now, forecast) -> list:
    from core import jobs
    out = []
    for key, channel in channels.items():
        if channel.archived:
            continue
        job = jobs.latest_failed_for_channel(key)
        if not job:
            continue
        if _made_since(channel, job):
            jobs.dismiss_job(job["id"])
            continue
        out.append(Item(WARN, f"A {channel.channel_display_name or key} video didn't finish",
                        failure_detail(job, now), "Retry", url_for("today.retry", job_id=job["id"]),
                        post=True, extra=[("Discard", url_for("today.dismiss", job_id=job["id"]), True)]))
    return out


def _topics(channels, url_for, now, forecast) -> list:
    """Running out of topics stops a channel dead; only useful in advance."""
    from core import curriculum
    out = []
    for key, channel in channels.items():
        if channel.archived or channel.content_mode != "topic" or not curriculum.exists(key):
            continue
        # A running channel's plan tops itself up (core.scheduler.top_up_plans)
        # while there's an outline left to write from; only then is it news.
        if channel.publishing.enabled and (channel.format == "quiz" or curriculum.next_unfilled_topic(key)):
            continue
        state = curriculum.progress(key)
        if state["running_low"]:
            out.append(Item(WARN, f"Running low on topics: {channel.channel_display_name or key}",
                            f"{state['pending']} left, about {state['runway_days']} days. It stops when the plan runs out.",
                            "Topic plan", url_for("curriculum.page", key=key)))
    return out


def _setup(channels, url_for, now, forecast) -> list:
    """Channels part way through setting up, with how long they've sat."""
    from core import launch
    out = []
    for key, channel in channels.items():
        if channel.archived:
            continue
        state = gallery.video_state_counts(channel.output_dir)
        stages, _ = launch.stages(channel, state)
        current = launch.current(stages)
        section = launch.section(channel, stages, state)
        name = channel.channel_display_name or key
        if current is None:
            continue
        if section == "live":
            if current.id == "shadow":
                continue        # the app's own step, shown on the channel; nothing to do but review
            out.append(Item(INFO, f"{name}: {current.label.lower()}", current.detail,
                            "Open", url_for("channels.dashboard", key=key)))
            continue
        last = gallery.latest_video_mtime(channel.output_dir) or 0
        idle = _age_days(last, now) if last else None
        if idle is not None and idle < STALLED_DAYS:
            continue
        since = f"untouched for {idle} days" if idle else "no videos yet"
        out.append(Item(INFO, f"{name} is setting up: {current.label.lower()}", since,
                        "Resume", url_for("channels.dashboard", key=key),
                        extra=[("Archive", url_for("channels.archive", key=key), True)]))
    return out


def _drafts(channels, url_for, now, forecast) -> list:
    from core import drafts
    out = []
    for record in drafts.all_drafts():
        if _age_days(record.get("created_at", 0), now) < DRAFT_DAYS:
            continue
        name = ((record.get("channel") or {}).get("name_options") or [record.get("pitch", "A draft")])[0]
        out.append(Item(INFO, f"Draft channel “{name}” not decided",
                        f"Drafted {_age_days(record.get('created_at', 0), now)} days ago.",
                        "Open", url_for("pitch.review", draft_id=record["id"]),
                        extra=[("Throw away", url_for("pitch.discard", draft_id=record["id"]), True)]))
    return out


def _categories(channels, url_for, now, forecast) -> list:
    """Quiz categories that are dead (decision 065): not written for any
    more, so only the owner can do something about them."""
    from pipeline.facts import rounds, store
    out = []
    quizzes = [c for c in channels.values() if c.format == "quiz" and not c.archived]
    if not quizzes:
        return out
    conn = store.connect()
    for channel in quizzes:
        for name, s in rounds.status(conn, channel).items():
            if s["state"] == "dead":
                out.append(Item(WARN, f"{channel.channel_display_name}: {name} has run out of questions",
                                f"{s['left']} left, and writing more has stopped adding to it. Drop it from "
                                "the plan, or rename it to something broader.",
                                "Topic plan", url_for("curriculum.page", key=channel.key)))
    return out


# --- running by itself ------------------------------------------------------------------

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def schedule_label(plan) -> str:
    if not plan.enabled:
        return "Off"
    days = plan.weekdays or list(range(7))
    when = "Daily" if len(days) == 7 else " ".join(WEEKDAYS[d] for d in sorted(days))
    return f"{when} {', '.join(plan.slots)}" if plan.slots else "As soon as approved"


def running(channels: dict, now: float = None) -> list:
    """Per channel: its state, schedule, what's queued and waiting, and
    what it's waiting for, if anything."""
    from core import launch, publish_queue, scheduler
    now = now or time.time()
    rows = []
    for key, channel in channels.items():
        if channel.archived:
            continue
        state = gallery.video_state_counts(channel.output_dir, long=False)
        stages, _ = launch.stages(channel, state)
        section = launch.section(channel, stages, state)
        if section != "live":
            continue
        schedule = publish_queue.schedule_for(channel)
        upcoming = [when for _, when in schedule if when]
        block = scheduler.generation_block(key, channel, state=state)
        status = channel_status(channel, section)
        rows.append({"key": key, "name": channel.channel_display_name or key, "status": status,
                     "schedule": schedule_label(channel.publishing), "queued": state["queued"],
                     "waiting": state["waiting"],
                     "next": min(upcoming).strftime("%a %d %b %H:%M") if upcoming else "",
                     "making": block is None or "being made" in (block or ""),
                     "block": block if block and "ready and queued" not in block else ""})
    return rows


def channel_status(channel, section: str) -> tuple:
    """(kind, label) for a channel: the same words on Today, the channel
    list and a channel's own header. `section` is core.launch.section's."""
    if section == "archived":
        return ("archived", "Archived")
    if section != "live":
        return ("setup", "Setting up")
    if not channel.publishing.enabled:
        return ("paused", "Paused")
    if _expired(channel):
        return ("blocked", "Can't upload")
    if channel.autopilot.mode == "when_clean":
        return ("auto", "Autopilot")
    return ("review", "You approve")


def _expired(channel) -> bool:
    from core import youtube
    return youtube.connection(channel.key)["expired"]


def background() -> list:
    """The work nobody starts: spare voice, the question bank, long quizzes."""
    from core import spare_voice
    from core.channels import load_channels
    from pipeline.facts import budget, keep, store
    out = []
    every = load_channels(validate=False)
    plan = spare_voice.current_plan(every)
    out.append({"name": "Spare voice", "schedule": f"In the last {spare_voice.WINDOW_DAYS} days before "
                                                   "the voice allowance resets",
                "detail": plan.summary(), "running": bool(plan.active and plan.videos)})
    channels = [c for c in every.values() if c.format == "quiz" and not c.archived]
    if channels:
        summary = budget.summary(store.connect(), channels)
        out.append({"name": "Question bank", "schedule": "Hourly, until every round is ready",
                     "detail": f"${summary['spent']:.2f} of ${summary['limit']:.2f} · {summary['ready']} rounds ready"
                               + (f" · {summary['short']} short" if summary["short"] else ""),
                     "running": keep.busy()})
        for channel in channels:
            q = channel.quiz
            kinds = [k for k, on in (("quiz nights", q.longform_mixed_when_ready),
                                     ("category quizzes", q.longform_category_when_ready)) if on]
            if kinds and channel.publishing.enabled:
                out.append({"name": f"{channel.channel_display_name} long quizzes",
                            "schedule": " and ".join(kinds).capitalize() + " as soon as their shorts are ready",
                            "detail": f"Out {schedule_label(_long_plan(channel.publishing))}", "running": False})
    return out


def _long_plan(plan):
    from types import SimpleNamespace
    return SimpleNamespace(enabled=True, weekdays=plan.long_weekdays, slots=plan.long_slots)
