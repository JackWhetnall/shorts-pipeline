"""
How much longer a video has to go.

"Is it nearly done, or should I come back after lunch?" is the only
question anyone actually has about a running job, and a stage tracker
answers it only for someone who already knows how long each stage takes.

The estimate is built from this installation's own finished jobs rather
than from a guess about hardware. Every job records when it entered each
stage (`core.jobs.Job.stage_entered`), so a completed record is a real
measurement of five real durations, on this machine, for this channel's
settings. With enough of those, "two minutes left" is a measurement; with
none, it is BASELINE below, which says so.

Three things make this honest rather than decorative:

  - **Per stage, not a single total.** Footage matching dominates and
    varies hugely with how many clips have to be downloaded. A job that
    is through footage and into assembly has far less left than a linear
    read of "stage 4 of 5" suggests.
  - **This channel first.** Segment count and target length are per
    channel and drive most of the variance, so a channel's own history
    beats the average across all of them. Other channels are the fallback,
    not the default.
  - **Median, not mean.** One job that stalled on a slow download
    shouldn't move every future estimate.

A queued job's estimate is the running job's remaining time plus every
job ahead of it, because only one runs at a time.
"""

from __future__ import annotations

import time

from core import job_context

# Seconds per stage before this installation has ever finished a video.
# Rough, and deliberately on the generous side — "sooner than promised"
# is a much better failure than "it said two minutes and it's been ten".
# Replaced by real measurements as soon as one job completes, which is
# why these are not worth tuning.
BASELINE = {1: 20.0, 2: 25.0, 3: 110.0, 4: 70.0, 5: 15.0}

# Below this many samples, a channel's own history isn't yet more
# trustworthy than everything else on the machine, so both are used.
MIN_SAMPLES = 3

# A job that took longer than this is assumed to have been left running
# while the machine slept, or otherwise stopped being a measurement of
# anything. Excluded rather than allowed to drag the median.
MAX_PLAUSIBLE_SECONDS = 3600.0


def _durations(job: dict) -> dict:
    """{stage: seconds} for one finished job, or {} if it can't be read.

    A stage's duration is the gap to the next stage's start; the last
    one's is the gap to `finished_at`. A job that skipped stages (an
    error part-way, a retry reusing checkpoints) yields only the stages
    it can actually account for.
    """
    if job.get("status") != "done" or job.get("retried"):
        return {}
    finished = job.get("finished_at")
    entered = job.get("stage_entered") or {}
    if not finished or not entered:
        return {}

    marks = sorted((int(n), ts) for n, ts in entered.items() if ts)
    out = {}
    for i, (stage, ts) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else finished
        seconds = end - ts
        if 0 < seconds < MAX_PLAUSIBLE_SECONDS:
            out[stage] = seconds
    return out


def _median(values: list) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def stage_seconds(history: list, channel_key: str = None) -> dict:
    """The per-stage estimate to use, given every job record available.

    Falls back stage by stage rather than all-or-nothing: a channel with
    two finished videos contributes what it knows and borrows the rest,
    which is better than discarding real local measurements because there
    weren't five of them.
    """
    mine, others = [], []
    for job in history:
        durations = _durations(job)
        if not durations:
            continue
        (mine if channel_key and job.get("channel_key") == channel_key
         else others).append(durations)

    estimate = {}
    for stage in job_context.STAGE_LABELS:
        samples = [d[stage] for d in mine if stage in d]
        if len(samples) < MIN_SAMPLES:
            samples += [d[stage] for d in others if stage in d]
        estimate[stage] = _median(samples) if samples else BASELINE.get(stage, 0.0)
    return estimate


def sample_count(history: list) -> int:
    """How many finished videos the estimate is actually built from. Shown
    on the page, because "about 4 minutes" from one sample and from thirty
    deserve to be read differently."""
    return sum(1 for job in history if _durations(job))


def total_seconds(history: list, channel_key: str = None) -> float:
    return sum(stage_seconds(history, channel_key).values())


def remaining_seconds(job: dict, history: list, now: float = None) -> float:
    """How much longer this running job has.

    The current stage is counted from when it actually started, so a
    stage that is already running long shrinks the estimate of itself to
    zero rather than being added on top of time already spent. It never
    goes negative: "a moment" is the floor, and the caller decides how to
    say that.
    """
    now = now or time.time()
    per_stage = stage_seconds(history, job.get("channel_key"))
    stage = int(job.get("stage") or 0)

    ahead = sum(seconds for n, seconds in per_stage.items() if n > stage)
    if stage < 1:
        # Not into stage 1 yet: everything is still to come.
        return sum(per_stage.values())

    entered = (job.get("stage_entered") or {}).get(str(stage))
    elapsed_here = max(0.0, now - entered) if entered else 0.0
    return max(0.0, ahead + max(0.0, per_stage.get(stage, 0.0) - elapsed_here))


def annotate(active: list, history: list, now: float = None) -> list:
    """Attach `eta_seconds` and `eta_at` to each job on an ordered list of
    everything in flight.

    Only one job runs at a time, so a queued job's wait is everything in
    front of it plus its own full run — the queue is the estimate, not a
    complication to it. Returns new dicts; nothing here mutates a job.
    """
    now = now or time.time()
    out = []
    running_total = 0.0
    for job in active:
        if job.get("status") == "running":
            seconds = remaining_seconds(job, history, now)
        else:
            seconds = running_total + total_seconds(history, job.get("channel_key"))
        running_total = seconds
        out.append({**job, "eta_seconds": seconds, "eta_at": now + seconds})
    return out


def describe(seconds: float) -> str:
    """A duration a person can act on.

    Rounded coarsely on purpose: "about 4 minutes" is as accurate as this
    estimate can honestly be, and "3 minutes 52 seconds" claims a
    precision it does not have.
    """
    if seconds is None:
        return ""
    if seconds < 45:
        return "under a minute"
    minutes = seconds / 60
    if minutes < 10:
        return f"about {round(minutes)} minute{'s' if round(minutes) != 1 else ''}"
    if minutes < 60:
        return f"about {int(round(minutes / 5) * 5)} minutes"
    hours = minutes / 60
    return f"about {hours:.1f} hours"
