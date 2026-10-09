"""
What happens without anyone clicking: three duties on a five-minute tick.

1. **Publish** whatever is due in each channel's queue (core.publish_queue).
2. **Keep each channel's buffer filled**: start a video whenever fewer than
   `publishing.buffer` are queued, so there is always one ready for the
   next slot. Making and publishing are separate now; a render can take as
   long as it takes, hours before its slot.
3. **Refresh audience numbers** for published videos (core.audience).

And, in the last days before the voice allowance resets, its spare goes on
videos made ahead for the slots nothing covers yet (core.spare_voice).

Before generating, each running channel's topic plan is kept ahead of it:
a plan only ever had its first topic's videos written, so a channel left
to itself stopped dead when that topic ran out. Now the next topic is
written when fewer than curriculum.LOW_WATER_MARK remain (a quiz channel
gets another round of every category, free).

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
import time

from core import curriculum, gallery, jobs, publish_queue, voice_quota
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
    if channel.format == "documentary":
        return "Its videos are made stage by stage on Productions, each approved."
    try:
        channel.validate()
    except PipelineError as exc:
        return exc.user_message
    active = jobs.active_jobs() if active is None else active
    if key in active:
        return "A video for this channel is being made."
    # Shorts only: a long quiz waiting for a look mustn't stop the shorts.
    state = state or gallery.video_state_counts(channel.output_dir, long=False)
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
            jobs.start_job(key, seed.to_jsonable(), ahead=True)
        except Exception as exc:  # noqa: BLE001 - one bad channel must not stop the rest
            log.warning(f"Couldn't start a video for {key}: {exc}")
            continue
        started.append(key)
        log.info(f"Started a video for {key} to keep its queue filled.")
    return started


def top_up_plans(channels: dict = None) -> list:
    """Write more of each running channel's topic plan when it's low.
    At most one topic per channel per tick. Returns the keys topped up."""
    from pipeline import curriculum_gen, quiz

    channels = channels if channels is not None else load_channels(validate=False)
    done = []
    for key, channel in channels.items():
        if (channel.archived or not channel.publishing.enabled
                or channel.content_mode != "topic" or not curriculum.exists(key)):
            continue
        try:
            if channel.format == "quiz":
                if quiz.top_up(channel):
                    done.append(key)
                continue
            if not curriculum.progress(key)["running_low"]:
                continue
            topic = curriculum.next_unfilled_topic(key)
            if topic is None:
                continue
            subtopics = curriculum_gen.write_subtopics(channel, curriculum.load(key), topic)
            curriculum.add_subtopics(key, topic["id"], subtopics)
            log.info(f"{key}: its topic plan was running low; wrote topic {topic['title']!r}")
            done.append(key)
        except Exception as exc:  # noqa: BLE001 - one channel's plan must not stop the rest
            log.warning(f"Couldn't top up {key}'s topic plan: {exc}")
    return done


def fill_long_quizzes(channels: dict = None) -> list:
    """Start a quiz night (the mixed series: one difficulty, a round from
    each of several categories, in no set order) for every running quiz
    channel as soon as enough categories have a finished round at one
    difficulty. One waiting at a time per channel, so they keep pace with
    the long-video slots, and no sooner than `longform_every_days` after
    the last if that's set. Returns the keys started."""
    from pipeline import longform

    channels = channels if channels is not None else load_channels(validate=False)
    active = jobs.active_jobs()
    started = []
    for key, channel in channels.items():
        if (channel.archived or channel.format != "quiz" or not channel.publishing.enabled
                or not channel.quiz.longform_mixed_when_ready or key in active):
            continue
        try:
            if longform.waiting(channel, longform.MIXED):
                continue
            mixed = [v for v, data in longform._long_videos(channel) if data["series"] == longform.MIXED]
            every = channel.quiz.longform_every_days
            if every > 0 and mixed and time.time() - max(v.stat().st_mtime for v in mixed) < every * 86400:
                continue
            difficulty = longform.ready_difficulty(channel)
            if not difficulty:
                continue
            request = longform.plan_request(channel, {"difficulty": difficulty})
            jobs.start_job(key, {"type": "longform", **request,
                                 "topic": f"Long quiz: {request['rounds']} rounds, {request['difficulty']}"},
                           ahead=True)
        except Exception as exc:  # noqa: BLE001 - one channel must not stop the rest
            log.warning(f"Couldn't start a long quiz for {key}: {exc}")
            continue
        started.append(key)
        log.info(f"Started a long quiz for {key}.")
    return started


def fill_category_quizzes(channels: dict = None) -> list:
    """Start a category's long quiz (easiest to hardest) as soon as it has
    a finished round at every level, for running quiz channels that want
    them. One waiting at a time per channel, so they keep pace with the
    long-video slots rather than piling up. Returns the keys started."""
    from pipeline import longform

    channels = channels if channels is not None else load_channels(validate=False)
    active = jobs.active_jobs()
    started = []
    for key, channel in channels.items():
        if (channel.archived or channel.format != "quiz" or not channel.publishing.enabled
                or not channel.quiz.longform_category_when_ready or key in active):
            continue
        try:
            ready = longform.full_ladders(channel)
            if longform.waiting(channel, longform.CATEGORY) or not ready:
                continue
            difficulty = longform.CATEGORY_PREFIX + ready[0]
            request = longform.plan_request(channel, {"difficulty": difficulty})
            jobs.start_job(key, {"type": "longform", **request,
                                 "topic": f"Long quiz: {ready[0]}, easiest to hardest"},
                           ahead=True)
        except Exception as exc:  # noqa: BLE001 - one channel must not stop the rest
            log.warning(f"Couldn't start a category quiz for {key}: {exc}")
            continue
        started.append(key)
        log.info(f"Started {ready[0]}'s long quiz for {key}: all its levels are finished.")
    return started


def _spare_voice(channels: dict) -> None:
    """In the last days before the voice allowance resets, what's left goes
    on videos made ahead for the slots nothing covers yet, one at a time and
    only when nothing else is being made (core.spare_voice, decision 069)."""
    from core import spare_voice
    spare_voice.run(channels)


def _keep_facts(channels: dict) -> None:
    """Keep quiz channels' categories stocked with facts, in the background
    (pipeline.facts.keep; it acts at most hourly)."""
    from pipeline.facts import keep
    keep.keep_up(channels)


_last_reach = {}
REACH_EVERY = 6 * 3600      # reach reports come daily; looked for a few times a day


def _thumbnail_tests(channels: dict) -> None:
    """Thumbnail tests (core.thumbnail_tests, decision 083): new reach
    figures fetched, shorts in rotation put on the variant they're due,
    finished rounds judged."""
    from core import reach, thumbnail_tests, youtube
    for key, channel in channels.items():
        if channel.archived or not channel.publishing.thumbnail_tests:
            continue
        if not youtube.connection(key)["connected"]:
            continue
        if time.time() - _last_reach.get(key, 0) >= REACH_EVERY:
            _last_reach[key] = time.time()
            try:
                reach.fetch(key)
                reach.clear_error(key)
            except PipelineError as exc:
                reach.note_error(key, exc.user_message)
                log.warning(f"{key}: thumbnail reach not read: {exc}")
        thumbnail_tests.rotate(channel)
        for round_id in thumbnail_tests.finish_rotations(channel):
            log.info(f"{key}: thumbnail test {round_id} finished")


def _storyboards(channels: dict) -> None:
    """The next few videos' storyboards written ahead, to look at before
    they're made (core.storyboard; at most hourly, at batch prices)."""
    from core import storyboard
    storyboard.keep_up(channels)


def tick() -> None:
    """One pass of all three duties. Each is isolated from the others: a
    failed upload must not stop generation, nor either stop the stats."""
    channels = load_channels(validate=False)
    for name, duty in (("publishing", lambda: publish_queue.publish_due(channels)),
                       ("topic plans", lambda: top_up_plans(channels)),
                       ("generation", lambda: fill_buffers(channels)),
                       ("long quizzes", lambda: fill_long_quizzes(channels)),
                       ("category quizzes", lambda: fill_category_quizzes(channels)),
                       ("spare voice", lambda: _spare_voice(channels)),
                       ("fact store", lambda: _keep_facts(channels)),
                       ("storyboards", lambda: _storyboards(channels)),
                       ("thumbnail tests", lambda: _thumbnail_tests(channels)),
                       ("statistics", lambda: _refresh_audience(channels)),
                       ("remake kits", lambda: _sweep_kits(channels))):
        try:
            duty()
        except Exception as exc:  # noqa: BLE001 - the ticker must never die
            log.warning(f"Scheduler {name} step failed: {exc}")


def _sweep_kits(channels: dict) -> None:
    """What finished videos were made of, kept for remakes, once no remake
    will use it (core.remake)."""
    from core import remake
    removed = remake.sweep(channels)
    if removed:
        log.info(f"Removed {removed} remake kit(s) no longer needed")


def _refresh_audience(channels: dict) -> None:
    # Cheap when nothing is due: each video's numbers are refreshed at
    # most every audience.REFRESH_HOURS.
    from core import audience
    audience.refresh(channels)


_thread = None
_stop = threading.Event()
# Set while a tick is running: an upload mid-way must not be cut off by a
# restart (core.code_freshness).
_ticking = threading.Event()


def busy() -> bool:
    return _ticking.is_set()


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
            _ticking.set()
            try:
                tick()
            finally:
                _ticking.clear()

    _stop.clear()
    _thread = threading.Thread(target=loop, daemon=True, name="scheduler")
    _thread.start()
    log.info("Scheduler running.")


def stop_background() -> None:
    _stop.set()
