"""
Recurring generation, so the pipeline can run without someone clicking a
button.

This is the gap between "a tool that makes a video" and "a pipeline that
publishes at frequency", which is what the project is actually for. Until
now the only way to make a video was to be present.

Deliberately simple: a per-channel cadence in days plus an optional
hour-of-day, checked by a background thread. No cron expressions, no
external scheduler, no new dependency. The thing being scheduled takes
minutes and runs at most a couple of times a day per channel — a
five-minute tick is more than precise enough, and everything it does goes
through the same queue as a manual run, so nothing can start two videos
at once.

Eligibility is deliberately conservative. A channel is skipped unless it
is live and has nothing unpublished waiting: generating a second video
while the first is still sitting unreviewed just builds a backlog, and a
backlog of unreviewed AI video is the exact failure mode the project's
policy notes warn about.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from core import gallery, jobs
from core.channels import load_channels
from core.logging_setup import get_logger
from core.paths import SCHEDULE_PATH

log = get_logger(__name__)

TICK_SECONDS = 300


@dataclass
class Schedule:
    """`every_days` of 0 means off. `hour` is local, or None for "any time
    the cadence is due"."""

    enabled: bool = False
    every_days: int = 1
    hour: int = None
    last_run_at: float = None

    def due(self, now: float = None) -> bool:
        if not self.enabled or self.every_days <= 0:
            return False
        now = now or time.time()
        if self.last_run_at and now - self.last_run_at < self.every_days * 86400:
            return False
        if self.hour is not None and datetime.fromtimestamp(now).hour != self.hour:
            return False
        return True


def load_schedules(path: Path = None) -> dict:
    path = Path(path or SCHEDULE_PATH)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        log.warning("Schedule file unreadable; treating every channel as unscheduled.")
        return {}
    return {key: Schedule(**{k: v for k, v in value.items()
                             if k in Schedule.__dataclass_fields__})
            for key, value in raw.items()}


def save_schedules(schedules: dict, path: Path = None) -> None:
    path = Path(path or SCHEDULE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: asdict(v) for k, v in schedules.items()}, f, indent=2)


def get_schedule(channel_key: str, path: Path = None) -> Schedule:
    return load_schedules(path).get(channel_key, Schedule())


def set_schedule(channel_key: str, schedule: Schedule, path: Path = None) -> None:
    schedules = load_schedules(path)
    existing = schedules.get(channel_key)
    # Preserve the last-run stamp across an edit, or changing the cadence
    # would immediately make the channel due again.
    if existing is not None and schedule.last_run_at is None:
        schedule.last_run_at = existing.last_run_at
    schedules[channel_key] = schedule
    save_schedules(schedules, path)


def is_eligible(channel, checklist_remaining: int, state: dict, has_active_job: bool) -> bool:
    """Whether a channel should have a video generated for it right now.

    The same rule the manual "Generate" button uses, so the scheduler can
    never start something the button wouldn't have allowed.
    """
    return (not channel.archived
            and checklist_remaining == 0
            and state["published"] > 0
            and state["unpublished"] == 0
            and not has_active_job)


def due_channels(path: Path = None) -> list:
    """(key, channel, schedule) for everything due and eligible now."""
    from web.checklist import remaining_count

    schedules = load_schedules(path)
    active = jobs.active_jobs()
    out = []
    for key, channel in load_channels(validate=False).items():
        schedule = schedules.get(key)
        if schedule is None or not schedule.due():
            continue
        state = gallery.video_state_counts(channel.output_dir)
        if is_eligible(channel, remaining_count(key, channel, state), state, key in active):
            out.append((key, channel, schedule))
    return out


def run_due(path: Path = None) -> list:
    """Start a job for everything due. Returns the keys started."""
    from pipeline.run import fetch_seed

    started = []
    for key, channel, schedule in due_channels(path):
        try:
            seed = fetch_seed(channel)
            jobs.start_job(key, seed.to_jsonable())
        except Exception as exc:  # noqa: BLE001 - one bad channel must not stop the rest
            log.warning(f"Scheduled run for {key} couldn't start: {exc}")
            continue
        schedule.last_run_at = time.time()
        set_schedule(key, schedule, path)
        started.append(key)
        log.info(f"Scheduled generation started for {key}.")
    return started


_thread = None
_stop = threading.Event()


def start_background(path: Path = None) -> None:
    """Start the ticker. Idempotent, and a daemon thread so it never
    keeps the process alive on its own."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return

    def loop():
        # A first tick immediately on boot would fire anything that came
        # due while the app was down, which is usually surprising rather
        # than helpful. Wait one interval first.
        while not _stop.wait(TICK_SECONDS):
            try:
                run_due(path)
            except Exception as exc:  # noqa: BLE001 - the ticker must never die
                log.warning(f"Scheduler tick failed: {exc}")

    _stop.clear()
    _thread = threading.Thread(target=loop, daemon=True, name="scheduler")
    _thread.start()
    log.info("Scheduler running.")


def stop_background() -> None:
    _stop.set()
