"""
Spare voice: the ElevenLabs allowance left before it resets, spent on
videos made ahead rather than lost (decision 069).

The allowance resets monthly and what's left then is gone. The owner, on
5 Oct with 18,272 credits two days from a reset: "it is ideal to not waste
this usage... calculated to generate videos that last the longest
timeframe, ie fills all the gaps in the upload schedule up to the latest
possible date."

So in the last WINDOW_DAYS before a reset, the app plans videos for the
publishing slots no video is waiting for yet, across every channel in date
order: every slot filled, with no gaps, up to the latest date the credits
reach. Slots already covered (queued, waiting in Review, being made) are
skipped. When the next slot's video no longer fits, later slots are still
tried, so credits left over go on a cheaper channel's video rather than
being lost. The first slots in that order are the ones the scheduler
would fill anyway, so nothing is counted twice.

Bounded by:
- **credits**: what's left, less a margin (two of the dearest channel's
  videos) for retries and long quizzes' joining lines;
- **time**: one video at a time, each taking about as long as videos made
  ahead have taken (batch prices are slower), finished before the reset;
- **money**: everything bought here comes out of the Claude credit, and
  it's never taken below a reserve of two weeks of the schedule's own
  spending (a small fixed amount when the balance isn't known);
- **horizon**: nothing more than MAX_DAYS_AHEAD ahead.

`run` starts one planned video whenever nothing else is being made, at
batch prices, and the plan is worked out again from live state every
tick, so an estimate that was off corrects itself. Videos made this way go
to Review like any other, and a channel with a backlog in Review makes no
more until it's reviewed down. That's what carries the stock into next
month: the next allowance isn't spent on these slots.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

WINDOW_DAYS = 3             # how long before a reset the spare is used
MAX_DAYS_AHEAD = 90         # never plan for slots further out than this
AHEAD_MINUTES = 30          # a made-ahead video, until some have been timed
TIME_MARGIN = 3600          # the last one should finish this long before the reset
MARGIN_VIDEOS = 2           # credits kept back: this many of the dearest channel's videos
RESERVE_DAYS = 14           # Claude credit kept back: this many days of the schedule's spending
RESERVE_MIN_USD = 3.0
UNKNOWN_BALANCE_USD = 3.0   # spent at most when the Claude balance hasn't been entered
DEFAULT_VIDEO_USD = 0.30    # a channel with no videos costed yet
DAY = 86400


@dataclass
class Situation:
    """Everything a plan is worked out from, gathered from live state by
    `situation()` or built by hand in a test."""
    now: float
    remaining: int                       # credits left
    resets_at: float                     # unix time, 0 when unknown
    slots: dict                          # {channel key: [datetime, ...]} upcoming, in order
    covered: dict                        # {channel key: slots already spoken for}
    credits: dict                        # {channel key: credits a video}
    usd: dict                            # {channel key: dollars a video}
    usd_available: float                 # what may be spent
    minutes: float = AHEAD_MINUTES       # a video, made ahead
    names: dict = field(default_factory=dict)


@dataclass
class Plan:
    active: bool
    why: str = ""                        # why not, or what stopped it going further
    resets: datetime = None
    remaining: int = 0
    spare: int = 0                       # credits it may spend
    videos: list = field(default_factory=list)    # [(slot, channel key)], date order
    filled_to: datetime = None           # every slot up to here has a video
    credits: int = 0
    usd: float = 0.0
    names: dict = field(default_factory=dict)

    @property
    def by_channel(self) -> Counter:
        return Counter(key for _, key in self.videos)

    def summary(self) -> str:
        """One line: what's being made with the spare, and how far it reaches."""
        if not self.active:
            return self.why
        if not self.videos:
            return self.why or "Nothing to make with it."
        parts = ", ".join(f"{self.names.get(k, k)} {n}" for k, n in self.by_channel.most_common())
        reach = f", every slot filled to {self.filled_to.strftime('%a %d %b')}" if self.filled_to else ""
        return f"Making {len(self.videos)} ahead ({parts}){reach}. Claude about ${self.usd:.2f}."


def make_plan(s: Situation) -> Plan:
    """The videos to make with what's spare, in the order of the slots they
    fill. Pure: everything comes from `s`."""
    resets = datetime.fromtimestamp(s.resets_at).astimezone() if s.resets_at else None
    plan = Plan(active=False, resets=resets, remaining=s.remaining, names=s.names)
    if not s.resets_at:
        plan.why = "ElevenLabs isn't saying when the allowance resets."
        return plan
    left = s.resets_at - s.now
    if left <= 0:
        plan.why = "The allowance has just reset."
        return plan
    if left > WINDOW_DAYS * DAY:
        plan.why = (f"Spare credits are used in the last {WINDOW_DAYS} days before the allowance "
                    f"resets on {resets.strftime('%a %d %b')}.")
        return plan
    plan.active = True
    keys = [k for k in s.slots if s.slots[k] and s.credits.get(k)]
    if not keys:
        plan.why = "No channel publishes on a schedule, so there are no slots to fill."
        return plan
    margin = MARGIN_VIDEOS * max(s.credits[k] for k in keys)
    plan.spare = spare = max(0, s.remaining - margin)
    usd_left = max(0.0, s.usd_available)
    room = int((left - TIME_MARGIN) // (s.minutes * 60)) if s.minutes > 0 else 0
    horizon = datetime.fromtimestamp(s.now + MAX_DAYS_AHEAD * DAY).astimezone()

    gaps = sorted((when, key) for key in keys for when in s.slots[key][s.covered.get(key, 0):]
                  if when <= horizon)
    if not gaps:
        plan.why = f"Every slot for the next {MAX_DAYS_AHEAD} days already has a video."
        return plan
    stopped = ""
    last_filled = None
    for when, key in gaps:
        if len(plan.videos) >= room:
            stopped = stopped or "There's no time to make more before it resets."
            break
        credits, usd = s.credits[key], s.usd.get(key, DEFAULT_VIDEO_USD)
        if credits <= spare and usd <= usd_left:
            plan.videos.append((when, key))
            spare -= credits
            usd_left -= usd
            plan.credits += credits
            plan.usd += usd
            if not stopped:
                last_filled = when
        elif not stopped:
            stopped = ("The credits run out there." if credits > spare else
                       "More would take the Claude credit below its two-week reserve.")
    if not stopped:
        stopped = f"That's every slot for the next {MAX_DAYS_AHEAD} days."
    plan.filled_to = last_filled
    plan.why = stopped
    return plan


def situation(channels: dict, now: float = None) -> Situation:
    """What a plan needs, from live state: the quota, each scheduled
    channel's upcoming slots and what already covers them, what a video
    costs in credits and in dollars, and what may be spent."""
    from core import gallery, jobs, money, publish_queue, voice_quota
    from core import costs
    from pipeline.facts import budget
    now = now or time.time()
    quota = voice_quota.current()
    records = costs.read_records()
    active = jobs.active_jobs()
    after = datetime.fromtimestamp(now).astimezone()
    slots, covered, credits, usd, names = {}, {}, {}, {}, {}
    for key, channel in channels.items():
        plan = channel.publishing
        if channel.archived or not plan.enabled or not plan.slots or not plan.weekdays:
            continue
        try:
            channel.validate()
        except PipelineError:
            continue                # it can't make videos; nothing to plan for it
        per_day = len(plan.slots) * len(plan.weekdays) / 7
        state = gallery.video_state_counts(channel.output_dir, long=False)
        covered[key] = state["queued"] + state["waiting"] + (1 if key in active else 0)
        slots[key] = publish_queue.upcoming_slots(plan, after, covered[key] + int(per_day * MAX_DAYS_AHEAD) + 1)
        credits[key] = voice_quota.typical_video_credits(key)
        usd[key] = money.cost_per_video(records, key) or DEFAULT_VIDEO_USD
        names[key] = channel.channel_display_name or key
    saved = money.settings()
    balance = money.balance("anthropic", records, saved)
    if balance is None:
        available = UNKNOWN_BALANCE_USD
    else:
        daily = sum(r["monthly"] for r in money.plan_rows(channels, records)) / money.MONTH_DAYS
        available = balance - budget.remaining() - max(RESERVE_MIN_USD, RESERVE_DAYS * daily)
    return Situation(now=now, remaining=quota.remaining if quota else 0,
                     resets_at=float(quota.resets_at or 0) if quota else 0,
                     slots=slots, covered=covered, credits=credits, usd=usd,
                     usd_available=available, minutes=made_ahead_minutes(), names=names)


def made_ahead_minutes() -> float:
    """How long a video made ahead takes, from the ones finished (they wait
    on batches, so they're slower than one made by hand); AHEAD_MINUTES
    until three have been."""
    import statistics
    from core import jobs
    taken = [(j["finished_at"] - j["started_at"]) / 60 for j in jobs.history()
             if j.get("ahead") and j.get("status") == "done" and j.get("finished_at") and j.get("started_at")
             and not j.get("retried")]
    return statistics.median(taken) if len(taken) >= 3 else AHEAD_MINUTES


def current_plan(channels: dict = None) -> Plan:
    from core import money
    from core.channels import load_channels
    channels = channels if channels is not None else load_channels(validate=False)
    if not money.settings().get("spare_voice", True):
        return Plan(active=False, why="Using spare voice before it resets is switched off (Money).")
    try:
        return make_plan(situation(channels))
    except Exception as exc:  # noqa: BLE001 - shown as the reason; the scheduler goes on
        log.warning(f"Couldn't plan the spare voice: {exc}")
        return Plan(active=False, why="Couldn't work out the spare voice; the details are in the log.")


def run(channels: dict = None) -> str:
    """The scheduler's duty: when nothing else is being made, start the
    next planned video. Returns the channel key started, or None."""
    from core import jobs
    from core.channels import load_channels
    from pipeline.run import fetch_seed
    if jobs.active_jobs():
        return None             # one at a time, and never ahead of anything else
    channels = channels if channels is not None else load_channels(validate=False)
    plan = current_plan(channels)
    if not plan.active or not plan.videos:
        return None
    tried = set()
    for when, key in plan.videos:
        if key in tried:
            continue
        tried.add(key)
        try:
            seed = fetch_seed(channels[key])
            jobs.start_job(key, seed.to_jsonable(), ahead=True,
                           note=(f"Made ahead with spare voice before the allowance resets on "
                                 f"{plan.resets.strftime('%a %d %b')}, for the {when.strftime('%a %d %b')} slot."))
        except Exception as exc:  # noqa: BLE001 - one channel that can't must not stop the next
            log.warning(f"Spare voice: couldn't start a video for {key}: {exc}")
            continue
        log.info(f"Spare voice: started a {key} video for the {when:%a %d %b %H:%M} slot "
                 f"({len(plan.videos)} planned, {plan.spare:,} credits spare)")
        return key
    return None
