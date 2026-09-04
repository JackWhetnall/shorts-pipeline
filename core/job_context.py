"""
"Which job is the current thread working on", plus the structured
side-channel pipeline code uses to report progress without knowing the
web app exists.

Two things changed from the version this replaces.

First, it uses contextvars rather than threading.local(). The old design
stamped a job id into thread-local storage and then hand-propagated it
into every worker a job spawned, because a ThreadPoolExecutor worker gets
its own empty thread-local and would otherwise lose the attribution.
contextvars.copy_context() does exactly that propagation as a language
feature — parallel_map below just runs each call inside a copy of the
calling context, and nothing has to be stamped by hand.

Second, progress reporting is explicit. Stage transitions used to be
recovered by regex-matching the pipeline's own printed output
(`^\\[1/4\\]`, `^\\s*\\[video\\] rendering video`) — rewording a log line
silently stopped the UI's stage tracker with no error anywhere. Stages,
percentages and per-item detail are now first-class calls that a reader
can follow from the pipeline to the UI.

Everything here is a no-op outside a job: plain CLI runs never register a
sink, so report_stage/report_detail/report_progress cost a contextvar
read and return. That's what keeps the pipeline importable and runnable
with no web dependency at all.
"""

from __future__ import annotations

import contextvars
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.paths import JOB_STATE_DIR

_current_job_id: contextvars.ContextVar = contextvars.ContextVar("job_id", default=None)
# Which channel the current work belongs to. Separate from the job id
# because CLI runs have a channel but no job, and cost records want to be
# attributable in both cases.
_current_channel_key: contextvars.ContextVar = contextvars.ContextVar("channel_key", default=None)

# The single registered consumer of progress reports — webapp's job
# registry in practice, nothing at all under the CLI. Kept as one object
# rather than four separate callbacks so there's one thing to implement
# and one thing to check for None.
_sink = None


class JobSink:
    """What a progress consumer has to implement. Every method is
    optional in practice (the base does nothing), so a consumer that only
    cares about stages doesn't have to stub out the rest."""

    def on_stage(self, job_id: str, stage: int) -> None: ...
    def on_progress(self, job_id: str, percent: float | None) -> None: ...
    def on_detail(self, job_id: str, section: str, item_index, patch: dict) -> None: ...
    def on_log(self, job_id: str, level: str, message: str) -> None: ...


def set_sink(sink: JobSink | None) -> None:
    global _sink
    _sink = sink


def get_job_id():
    return _current_job_id.get()


def set_job_id(job_id):
    """Returns the contextvars Token, so a caller that needs to restore
    the previous value can. Job threads never do — they start with a
    fresh context and end with the thread."""
    return _current_job_id.set(job_id)


def get_channel_key():
    return _current_channel_key.get()


def set_channel_key(channel_key):
    return _current_channel_key.set(channel_key)


# --- progress reporting -----------------------------------------------

# The pipeline's stages, in order. This list is the contract between the
# pipeline and the UI's stage tracker; both read it, so adding a stage is
# a one-line change in one place rather than a new regex plus a hardcoded
# count in the frontend.
STAGES = (
    (1, "Script", "writing the script"),
    (2, "Voiceover", "generating the voiceover"),
    (3, "Footage", "matching footage"),
    (4, "Assembling", "assembling the video"),
    (5, "Finishing", "finishing touches"),
)
STAGE_COUNT = len(STAGES)
STAGE_LABELS = {n: label for n, label, _ in STAGES}
STAGE_GERUNDS = {0: "getting started", **{n: gerund for n, _, gerund in STAGES}}


def report_stage(stage: int) -> None:
    job_id = get_job_id()
    if job_id and _sink:
        _sink.on_stage(job_id, stage)


def report_progress(percent) -> None:
    """0-100, or None to clear. Called from the encode progress hook (see
    core.progress) rather than scraped out of a tqdm bar's stderr writes."""
    job_id = get_job_id()
    if job_id and _sink:
        _sink.on_progress(job_id, percent)


def report_detail(section: str, item_index, patch: dict) -> None:
    """Granular per-item progress: item_index=None merges into the
    section's own keys (running totals), an int merges into
    section["items"][index], growing that list as needed."""
    job_id = get_job_id()
    if job_id and _sink:
        _sink.on_detail(job_id, section, item_index, patch)


# --- checkpoints ------------------------------------------------------

def checkpoint_dir(job_id):
    """None outside a job, which makes every checkpoint call below a safe
    no-op under plain CLI use."""
    if not job_id:
        return None
    d = JOB_STATE_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_json_checkpoint(name: str, data) -> None:
    """Persist one pipeline stage's result so a retry of an interrupted
    job can skip redoing it. Best-effort by contract: a disk failure here
    must never fail a render that otherwise succeeded, so callers wrap
    this in try/except and this never raises for a missing job."""
    d = checkpoint_dir(get_job_id())
    if d is None:
        return
    (d / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def load_json_checkpoint(name: str):
    d = checkpoint_dir(get_job_id())
    if d is None:
        return None
    path = d / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def checkpoint_artifact_path(filename: str):
    """Path for a non-JSON checkpoint (the finished voiceover mp3), or
    None outside a job."""
    d = checkpoint_dir(get_job_id())
    return (d / filename) if d is not None else None


def clear_checkpoints(job_id: str) -> None:
    """Called once a job succeeds — nothing in a checkpoint is needed
    after the real output exists. Failed and interrupted jobs keep theirs
    so a retry has something to resume from."""
    d = JOB_STATE_DIR / job_id if job_id else None
    if d and d.exists():
        shutil.rmtree(d, ignore_errors=True)


# --- parallelism ------------------------------------------------------

def parallel_map(fn, items: list, max_workers: int = 8) -> list:
    """fn(item) for every item, concurrently, results in INPUT order.

    Input order (not completion order) matters: the TTS stage stitches
    segments back together positionally, where each segment's start time
    depends on the cumulative duration of everything before it. Getting
    results back out of order there would silently desynchronise every
    caption in the video.

    Each call runs inside a copy of the CALLING context, so the current
    job id — and anything else contextvar-based — is visible inside fn
    without the caller doing anything. A thread pool is the right tool
    because every use here is I/O-bound (HTTP calls, downloads, ffmpeg
    subprocesses); none of it is CPU-bound Python that the GIL would
    block.
    """
    if not items:
        return []
    # A fresh Context copy per item: Context.run() may only be entered
    # once per Context object, and giving each task its own copy also
    # keeps any contextvar a task sets from leaking into its siblings.
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        futures = [pool.submit(contextvars.copy_context().run, fn, item) for item in items]
        return [f.result() for f in futures]
