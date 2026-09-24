"""
What happens without anyone clicking: three duties on a five-minute tick.

1. **Publish** whatever is due in each channel's queue (core.publish_queue).
2. **Keep each channel's buffer filled**: start a video whenever fewer than
   `publishing.buffer` are queued, so there is always one ready for the
   next slot. Making and publishing are separate now; a render can take as
   long as it takes, hours before its slot.
3. **Refresh audience numbers** for published videos (core.audience).

This replaced a per-channel "every N days at hour H" timer that made and
published in one go, and refused to make anything while one video was
waiting. That rule was right about not building a backlog of unreviewed
video, and it stays in a narrower form: a channel stops generating while
`buffer` or more videos are waiting for a look. Held videos don't stop
the queue, but they can't pile up either.

Runs inside the web app (`python -m web`, started at logon by the "Shorts
Pipeline" task). Everything goes through the same job queue as a manual
run, so two videos are never made at once.
"""

from __future__ import annotations

import threading

from core import gallery, jobs, publish_queue, voice_quota
from core.channels import load_channels
from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

TICK_SECONDS = 300


def generation_block(key: str, channel, state: dict = None, active: dict = None):
    """Why this channel shouldn't start a video right now, or None if it
    should. One place, so the dashboard can say exactly what the
    scheduler is waiting for."""
    plan = channel.publishing
    if channel.archived:
        return "The channel is archived."
    if not plan.enabled:
        return "The publishing plan is off."
    try:
        channel.validate()
    except PipelineError as exc:
        return exc.user_message
    active = jobs.active_jobs() if active is None else active
    if key in active:
        return "A video for this channel is being made."
    state = state or gallery.video_state_counts(channel.output_dir)
    if state["queued"] >= plan.buffer:
        return f"{state['queued']} ready and queued, the {plan.buffer} this channel keeps."
    if state["waiting"] >= plan.buffer:
        return (f"{state['waiting']} video{'s' if state['waiting'] != 1 else ''} waiting for "
                f"a look in review. It makes more once those are dealt with.")
    if not voice_quota.has_room_for(voice_quota.typical_video_characters(key)):
        return "Not enough ElevenLabs characters left this month."
    return None


def fill_buffers(channels: dict = None) -> list:
    """Start a video for every channel that needs one. Returns the keys."""
    from pipeline.run import fetch_seed

    channels = channels if channels is not None else load_channels(validate=False)
    active = jobs.active_jobs()
    started = []
    for key, channel in channels.items():
        if generation_block(key, channel, active=active):
            continue
        try:
            seed = fetch_seed(channel)
            jobs.start_job(key, seed.to_jsonable())
        except Exception as exc:  # noqa: BLE001 - one bad channel must not stop the rest
            log.warning(f"Couldn't start a video for {key}: {exc}")
            continue
        started.append(key)
        log.info(f"Started a video for {key} to keep its queue filled.")
    return started


def tick() -> None:
    """One pass of all three duties. Each is isolated from the others: a
    failed upload must not stop generation, nor either stop the stats."""
    channels = load_channels(validate=False)
    for name, duty in (("publishing", lambda: publish_queue.publish_due(channels)),
                       ("generation", lambda: fill_buffers(channels)),
                       ("statistics", lambda: _refresh_audience(channels))):
        try:
            duty()
        except Exception as exc:  # noqa: BLE001 - the ticker must never die
            log.warning(f"Scheduler {name} step failed: {exc}")


def _refresh_audience(channels: dict) -> None:
    # Cheap when nothing is due: each video's numbers are refreshed at
    # most every audience.REFRESH_HOURS.
    from core import audience
    audience.refresh(channels)


_thread = None
_stop = threading.Event()


def start_background() -> None:
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
            tick()

    _stop.clear()
    _thread = threading.Thread(target=loop, daemon=True, name="scheduler")
    _thread.start()
    log.info("Scheduler running.")


def stop_background() -> None:
    _stop.set()
