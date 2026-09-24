"""
Background video generation: one queue, persisted across restarts.

Lives in core/ rather than the web layer because a job is a domain
concept — the scheduler starts them too, and nothing here imports Flask.

**Output capture.** Jobs used to capture their output by installing a
dispatching object as `sys.stdout` process-wide and reassembling lines by
hand — careful code solving a routing problem the standard library
already solves, with a blind spot for anything that wrote to the real
stream without going through `print()`. The pipeline now logs, and this
module registers a handler that routes each record by the contextvar in
`core.job_context`. Encode progress arrives through a proglog hook rather
than a regex over a tqdm bar's stderr writes.

**Persistence.** The status record used to be rewritten in full — with
the entire accumulated log inside it — on every single log line, which is
quadratic I/O on the machine that is simultaneously encoding video. Log
lines now append to their own file and the status record is written only
on real state transitions.

**One at a time.** Each job already fans out several concurrent
ElevenLabs calls and stock-footage downloads internally, so running two
videos at once multiplies that against the same rate-limited APIs.
Starting a job while one is running queues it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

from core import job_context
from core.errors import JobError, friendly_message
from core.logging_setup import JobLogHandler, configure
from core.paths import JOB_STATE_DIR

# How many recent log lines the UI keeps in memory per job. The full log
# is always on disk; this only bounds what a poll response carries.
LOG_TAIL = 400

# Completed jobs older than this are removed at startup, directory and
# all. Without it the registry and the checkpoint directory grew forever.
RETENTION_DAYS = 7

RUNNING_STATES = ("running", "queued")
RETRYABLE_STATES = ("error", "interrupted")

_lock = threading.RLock()
_jobs = {}
_queue = []


@dataclass
class Job:
    id: str
    channel_key: str
    seed: dict
    status: str = "queued"          # queued | running | done | error | interrupted
    stage: int = 0
    stage_total: int = job_context.STAGE_COUNT
    progress_percent: float = None
    current_progress: str = None
    detail: dict = field(default_factory=dict)
    result_path: str = None
    error: str = None
    error_traceback: str = None
    warnings: list = field(default_factory=list)
    # Things that went right and are worth saying, such as an automatic
    # upload - kept apart from warnings so they don't read as problems.
    notes: list = field(default_factory=list)
    queued_at: float = None
    started_at: float = None
    finished_at: float = None
    # When each stage began, keyed by stage number as a string because
    # this round-trips through JSON. Finished records are the only honest
    # source of "how long does a video take" this project has — see
    # core.job_eta, which reads them back to answer it.
    stage_entered: dict = field(default_factory=dict)
    # A retry reuses this job's checkpoints, so its stages complete in
    # seconds and its timings describe nothing. Marked so core.job_eta can
    # leave it out of the history rather than learning that a video takes
    # four seconds to make.
    retried: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _dir(job_id: str) -> Path:
    return JOB_STATE_DIR / job_id


def _log_path(job_id: str) -> Path:
    return _dir(job_id) / "log.txt"


def _record_path(job_id: str) -> Path:
    return _dir(job_id) / "job.json"


def _persist(job_id: str) -> None:
    """Write the status record. Called on state transitions only — never
    per log line, which is what made this quadratic before."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        snapshot = job.to_dict()
    try:
        _dir(job_id).mkdir(parents=True, exist_ok=True)
        _record_path(job_id).write_text(json.dumps(snapshot), encoding="utf-8")
    except Exception:  # noqa: BLE001 - persistence must never break a render
        pass


class _Sink(job_context.JobSink):
    """Receives everything the pipeline reports about the running job."""

    def on_stage(self, job_id: str, stage: int) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            # Monotonic: an out-of-order report can never move the UI's
            # progress backwards.
            job.stage = max(job.stage, stage)
            # setdefault, not assignment: a retry re-enters stage 1 with
            # its checkpoints intact, and overwriting would record that
            # near-instant second pass as this stage's real duration.
            job.stage_entered.setdefault(str(stage), time.time())
            job.current_progress = None
            job.progress_percent = None
        _persist(job_id)

    def on_progress(self, job_id: str, percent) -> None:
        # Deliberately not persisted: this fires many times a second
        # during the encode and carries nothing worth recovering after a
        # restart.
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.progress_percent = percent
                job.current_progress = f"{percent:.0f}%" if percent is not None else None

    def on_detail(self, job_id: str, section: str, item_index, patch: dict) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            sec = job.detail.setdefault(section, {"items": []})
            if item_index is None:
                sec.update(patch)
            else:
                items = sec.setdefault("items", [])
                while len(items) <= item_index:
                    items.append({})
                items[item_index].update(patch)

    def on_log(self, job_id: str, level: str, message: str) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            if level in ("warning", "error"):
                job.warnings.append(message)
        # Append-only: one line, not a rewrite of the whole record.
        try:
            _dir(job_id).mkdir(parents=True, exist_ok=True)
            with open(_log_path(job_id), "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception:  # noqa: BLE001
            pass


_sink = _Sink()
_installed = False


def install() -> None:
    """Wire the pipeline's reporting to this registry. Idempotent, and
    called from the app factory and the CLI scheduler alike."""
    global _installed
    if _installed:
        return
    job_context.set_sink(_sink)
    configure(level=logging.INFO, extra_handlers=[JobLogHandler(_sink)])
    _installed = True


def read_log(job_id: str, tail: int = LOG_TAIL) -> list:
    path = _log_path(job_id)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-tail:]


# --- running ----------------------------------------------------------

def _run(job_id: str, channel_key: str, seed: dict) -> None:
    from core.channels import load_channels
    from pipeline.plan import Seed
    from pipeline.run import generate

    job_context.set_job_id(job_id)
    job_context.set_channel_key(channel_key)
    try:
        channel = load_channels()[channel_key]
        plan = generate(channel, Seed.from_jsonable(seed), interactive=False)
        with _lock:
            job = _jobs[job_id]
            job.status = "done"
            job.stage = job_context.STAGE_COUNT
            job.result_path = str(plan.video_path)
            job.finished_at = time.time()
            job.progress_percent = None
            if plan.footage_degraded:
                job.warnings.append(
                    "Footage was chosen without scoring because the matching step "
                    "failed. The video rendered, but watch it before publishing.")
            if plan.footage_unconfident and not plan.footage_degraded:
                job.warnings.append(
                    f"{plan.footage_unconfident} shot(s) had no footage that scored as a "
                    f"good match, even after fetching. Watch those before publishing.")
            if plan.footage_repeated:
                job.warnings.append(
                    "This video reuses a footage clip — the library ran out of distinct "
                    "matches. Worth reviewing before publishing.")
            if plan.similarity is not None and plan.similarity.flagged:
                job.warnings.append(f"Originality check: {plan.similarity.summary}")
        _persist(job_id)
        _autopilot(job_id, channel, plan)
        # Nothing checkpointed is needed once the real output exists.
        job_context.clear_checkpoints(job_id)
    except Exception as exc:  # noqa: BLE001 - a failed render must not kill the thread
        with _lock:
            job = _jobs[job_id]
            job.status = "error"
            job.error = friendly_message(exc)
            job.error_traceback = traceback.format_exc()
            job.finished_at = time.time()
        _persist(job_id)
    finally:
        _advance_queue()


def _spawn(job_id: str, channel_key: str, seed: dict) -> None:
    threading.Thread(target=_run, args=(job_id, channel_key, seed), daemon=True).start()


def _autopilot(job_id: str, channel, plan) -> None:
    """Publish the video if this channel publishes itself and it passed
    the gate; otherwise record why it's waiting. After the job is marked
    done, so an upload in progress never reads as a render in progress."""
    from core import autopilot

    decision = autopilot.after_render(channel, plan.video_path)
    if decision.action == autopilot.OFF:
        return
    with _lock:
        job = _jobs[job_id]
        if decision.action == autopilot.QUEUED:
            job.notes.append(decision.message)
        else:
            job.warnings.append(decision.message)
    _persist(job_id)


def _advance_queue() -> None:
    """Start the next queued job. Runs in the finishing job's thread, so
    a failure here would otherwise strand the queue silently — if the
    next job can't be started it's marked errored and the queue keeps
    moving, rather than stopping with nothing to show for it."""
    while True:
        with _lock:
            if not _queue:
                return
            next_id = _queue.pop(0)
            job = _jobs.get(next_id)
            if job is None:
                continue        # vanished from the registry; try the one after it
            job.status = "running"
            job.started_at = time.time()
            channel_key, seed = job.channel_key, job.seed
        _persist(next_id)
        try:
            _spawn(next_id, channel_key, seed)
            return
        except Exception as exc:  # noqa: BLE001
            with _lock:
                job = _jobs.get(next_id)
                if job is not None:
                    job.status = "error"
                    job.error = friendly_message(exc)
                    job.finished_at = time.time()
            _persist(next_id)
            # Loop round and try the next one instead of stranding the queue.


def start_job(channel_key: str, seed: dict) -> str:
    """Queue or start a job. Raises JobError if this channel already has
    one in flight."""
    install()
    with _lock:
        if any(j.status in RUNNING_STATES and j.channel_key == channel_key
               for j in _jobs.values()):
            raise JobError(
                f"job already active for {channel_key}",
                user_message="This channel already has a video being generated.",
            )
        running_now = any(j.status == "running" for j in _jobs.values())
        job_id = uuid.uuid4().hex
        now = time.time()
        _jobs[job_id] = Job(
            id=job_id, channel_key=channel_key, seed=seed,
            status="queued" if running_now else "running",
            queued_at=now, started_at=None if running_now else now,
        )
        if running_now:
            _queue.append(job_id)
    _persist(job_id)
    if not running_now:
        _spawn(job_id, channel_key, seed)
    return job_id


def retry_job(job_id: str) -> str:
    """Re-run a failed or interrupted job under the SAME id.

    Reusing the id is what makes the retry cheap: checkpoints are keyed
    by job id, so the script, voiceover and footage picks that already
    completed are reused rather than paid for twice.
    """
    install()
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise JobError("no such job", user_message="That job no longer exists.")
        if job.status not in RETRYABLE_STATES:
            raise JobError(
                f"status {job.status}",
                user_message=f'This job is "{job.status}" and can\'t be retried.',
            )
        if any(j.status in RUNNING_STATES and j.channel_key == job.channel_key
               and j.id != job_id for j in _jobs.values()):
            raise JobError(
                "channel busy",
                user_message="This channel already has a video being generated.",
            )
        running_now = any(j.status == "running" for j in _jobs.values())
        now = time.time()
        job.status = "queued" if running_now else "running"
        job.stage = 0
        job.progress_percent = None
        job.current_progress = None
        job.detail = {}
        job.error = None
        job.error_traceback = None
        job.warnings = []
        job.result_path = None
        job.queued_at = now
        job.started_at = None if running_now else now
        job.finished_at = None
        job.retried = True
        channel_key, seed = job.channel_key, job.seed
        if running_now:
            _queue.append(job_id)
    _persist(job_id)
    if not running_now:
        _spawn(job_id, channel_key, seed)
    return job_id


# --- reading ----------------------------------------------------------

def _with_extras(job: Job) -> dict:
    data = job.to_dict()
    with _lock:
        data["queue_position"] = (_queue.index(job.id) + 1) if job.id in _queue else None
    data["log"] = read_log(job.id)
    data["stage_labels"] = job_context.STAGE_LABELS
    return data


def get_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    return _with_extras(job) if job else None


def active_job_for_channel(channel_key: str):
    with _lock:
        for job in _jobs.values():
            if job.status in RUNNING_STATES and job.channel_key == channel_key:
                return _with_extras(job)
    return None


def latest_failed_for_channel(channel_key: str):
    """The most recent retryable job, so a page can offer "your last
    attempt was interrupted — retry?" without the user already knowing a
    job id."""
    with _lock:
        candidates = [j for j in _jobs.values()
                      if j.channel_key == channel_key and j.status in RETRYABLE_STATES]
        if not candidates:
            return None
        best = max(candidates, key=lambda j: j.finished_at or j.queued_at or 0)
    return _with_extras(best)


def active_jobs() -> dict:
    """{channel_key: job} for everything in flight — one call for a page
    that needs to check every channel."""
    with _lock:
        return {j.channel_key: _with_extras(j)
                for j in _jobs.values() if j.status in RUNNING_STATES}


def active_in_order() -> list:
    """Everything in flight, in the order it will actually happen:
    whatever is running, then the queue as the queue holds it.

    `active_jobs` keys by channel, which is right for "does this channel
    have one going" and wrong for a page whose whole subject is the order
    — a dict has no queue in it.
    """
    with _lock:
        running = [j for j in _jobs.values() if j.status == "running"]
        queued = [_jobs[jid] for jid in _queue if jid in _jobs]
        ordered = running + queued
        return [_with_extras(j) for j in ordered]


def history() -> list:
    """Every record held, as plain dicts and without the log tail.

    `_with_extras` reads a file per job; a caller measuring how long
    videos take (core.job_eta) wants the numbers, not a week of logs.
    """
    with _lock:
        return [j.to_dict() for j in _jobs.values()]


def recent_finished(limit: int = 6) -> list:
    """The last few jobs that stopped, newest first — done, failed and
    interrupted alike. An empty queue with nothing else on the page reads
    as "nothing happened"; these say what just did."""
    with _lock:
        done = [j for j in _jobs.values() if j.status not in RUNNING_STATES]
        done.sort(key=lambda j: j.finished_at or j.queued_at or 0, reverse=True)
        return [_with_extras(j) for j in done[:limit]]


# --- persistence ------------------------------------------------------

def load_persisted_jobs() -> int:
    """Reload job records at startup and prune old ones.

    A job still marked running or queued belongs to a process that no
    longer exists, so it becomes "interrupted" — never silently resumed.
    Its checkpoints are deliberately kept, so retrying it picks up
    whatever already completed.
    """
    if not JOB_STATE_DIR.exists():
        return 0
    cutoff = time.time() - RETENTION_DAYS * 86400
    loaded = 0

    for directory in sorted(JOB_STATE_DIR.iterdir()):
        record = directory / "job.json"
        if not record.exists():
            continue
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        known = {f for f in Job.__dataclass_fields__}
        job = Job(**{k: v for k, v in data.items() if k in known})

        finished = job.finished_at or 0
        if job.status not in RUNNING_STATES and finished and finished < cutoff:
            import shutil
            shutil.rmtree(directory, ignore_errors=True)
            continue

        if job.status in RUNNING_STATES:
            job.status = "interrupted"
            job.error = (
                "This video's generation was interrupted (the app restarted or stopped) "
                f"while {job_context.STAGE_GERUNDS.get(job.stage, 'working')}. Nothing was "
                "lost — retrying picks up from whatever already finished."
            )
            job.error_traceback = None
            job.finished_at = time.time()

        with _lock:
            _jobs[job.id] = job
        loaded += 1

    return loaded
