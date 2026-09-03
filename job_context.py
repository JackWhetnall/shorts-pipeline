"""
Thin, dependency-free thread-local "which job is this" tracker, shared by
webapp/jobs.py (which sets it once per job thread and reads it to route
captured stdout/stderr — see that module's docstring) and any pipeline
code that spawns its OWN worker threads for parallel I/O
(tts_captions.py's per-segment TTS calls, footage_library.py's per-clip
downloads) and needs those workers' print() output attributed to the
same job instead of silently falling through to the real stdout — a
worker thread doesn't inherit threading.local() state from whoever
started it, so without this, parallelizing a job's internal work would
make that work's log output vanish from the job's visible log.

Lives at the project root, not under webapp/, so plain CLI usage of the
pipeline (main.py run directly, no Flask involved) never needs to import
anything web-related — get_job_id() is just None everywhere in that case,
and parallel_map still works exactly the same, it just has nothing
job-specific to propagate.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_local = threading.local()

# Per-job checkpoint storage: job_state/<job_id>/ holds webapp/jobs.py's
# own persisted job record (job.json, so job history/status survives a
# server restart instead of vanishing) AND pipeline checkpoints (script,
# voiceover audio+timings, footage picks) so a RETRY of an interrupted or
# failed job (webapp/jobs.py's retry_job) can skip redoing whatever
# expensive work already completed rather than paying for it twice. Lives
# at the project root next to output/ and footage/ (gitignored, same as
# those) since it's pipeline data, not a web-app-specific concept, even
# though only the web app currently creates retryable jobs.
CHECKPOINT_ROOT = Path(__file__).parent / "job_state"


def checkpoint_dir(job_id):
    """None outside a job (plain CLI use, or no job_id at all) - every
    checkpoint function below is a safe no-op in that case."""
    if not job_id:
        return None
    d = CHECKPOINT_ROOT / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_json_checkpoint(name: str, data):
    """Persists a JSON-serializable checkpoint for one pipeline stage of
    the CURRENT job (e.g. "script", "footage_picks") - a no-op outside a
    job. Best-effort is the caller's job, not this function's: a disk
    write failing here should never be allowed to fail the actual video."""
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
    """Path for a non-JSON checkpoint file (e.g. the finished voiceover
    mp3) inside the current job's checkpoint dir, or None outside a job."""
    d = checkpoint_dir(get_job_id())
    return (d / filename) if d is not None else None


def clear_checkpoints(job_id: str):
    """Deletes a job's entire checkpoint directory - called once a job
    finishes successfully (webapp/jobs.py), since nothing in it is needed
    once the real output exists. Failed/interrupted jobs keep theirs so a
    retry has something to resume from."""
    import shutil
    d = CHECKPOINT_ROOT / job_id if job_id else None
    if d and d.exists():
        shutil.rmtree(d, ignore_errors=True)

# Lets pipeline code (tts_captions.py, footage_library.py) report granular,
# structured progress - "segment 2/3 synthesizing", "clip 5/12 downloading"
# - without importing webapp/jobs.py directly (would break plain CLI use).
# webapp/jobs.py registers itself as the sink once, at import time;
# report_detail() is a no-op whenever there's no sink (CLI) or no current
# job id (nothing to attribute the update to).
_detail_sink = None


def set_job_id(job_id):
    _local.job_id = job_id


def get_job_id():
    return getattr(_local, "job_id", None)


def set_detail_sink(fn):
    """fn(job_id, section, item_index, patch) - called by report_detail
    below. webapp/jobs.py is the only real implementation; it merges patch
    into job["detail"][section] (item_index=None) or
    job["detail"][section]["items"][item_index] (item_index=an int)."""
    global _detail_sink
    _detail_sink = fn


def report_detail(section: str, item_index, patch: dict):
    job_id = get_job_id()
    if job_id and _detail_sink:
        _detail_sink(job_id, section, item_index, patch)


def parallel_map(fn, items: list, max_workers: int = 8) -> list:
    """Runs fn(item) for every item in `items` concurrently (a thread
    pool — fine for I/O-bound work like network downloads/API calls, not
    CPU-bound work that would need real parallelism past the GIL),
    propagating the CALLING thread's job id into each worker thread first
    so any print() inside fn still gets attributed to the right job's
    captured log. Returns results in the SAME ORDER as `items`, not
    completion order — callers that need to stitch results back together
    positionally (TTS segments concatenated in script order, in
    particular) can rely on this."""
    if not items:
        return []
    job_id = get_job_id()

    def _wrapped(item):
        set_job_id(job_id)
        return fn(item)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        return list(pool.map(_wrapped, items))
