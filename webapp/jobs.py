"""
In-memory background job registry for triggering video generation from
the web UI without blocking the request that started it.

Only one job runs at a time. This isn't just simplicity: capturing
progress works by temporarily redirecting sys.stdout/sys.stderr, which
patches them process-wide, not per-thread — two concurrent jobs would
interleave and corrupt each other's captured output (and every module in
this pipeline uses plain print(), not a logger that could be scoped per
job). A single local user generating one video at a time doesn't need
more than that anyway.

Ordinary print() calls (main.py/tts_captions.py/video_assemble.py/
footage_library.py) go to stdout and are newline-terminated — each one
becomes one entry in the job's scrollback "log". moviepy's own
logger="bar" progress (video_assemble.build_video's encode step) goes to
STDERR by default (tqdm's default output stream — verified against the
installed proglog/tqdm, not assumed) and is carriage-return-terminated,
overwriting the same line — that's captured into "current_progress"
instead of the log, so a live percentage/ETA doesn't spam scrollback with
hundreds of bar-redraw lines.
"""

import contextlib
import io
import threading
import time
import traceback
import uuid

_LOCK = threading.Lock()
_JOBS = {}


class _JobCaptureStream(io.TextIOBase):
    """Captures both stdout and stderr writes for one job, splitting on
    whichever line terminator (\\n or \\r) comes first."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self._buf = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._buf += s
        self._drain()
        return len(s)

    def _drain(self):
        while True:
            nl = self._buf.find("\n")
            cr = self._buf.find("\r")
            if nl == -1 and cr == -1:
                break
            if cr != -1 and (nl == -1 or cr < nl):
                line, self._buf = self._buf[:cr], self._buf[cr + 1:]
                self._set_progress(line)
            else:
                line, self._buf = self._buf[:nl], self._buf[nl + 1:]
                self._append_log(line)

    def _append_log(self, line: str):
        if not line.strip():
            return
        with _LOCK:
            job = _JOBS.get(self.job_id)
            if job is not None:
                job["log"].append(line)
                job["current_progress"] = None

    def _set_progress(self, line: str):
        if not line.strip():
            return
        with _LOCK:
            job = _JOBS.get(self.job_id)
            if job is not None:
                job["current_progress"] = line

    def flush(self):
        pass


def _run_job(job_id: str, channel_key: str, seed: dict):
    import main as main_module
    import webapp.channel_store as channel_store

    stream = _JobCaptureStream(job_id)
    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            cfg = channel_store.get_channels()[channel_key]
            video_path = main_module.generate_video_from_seed(
                channel_key, seed, cfg, interactive=False
            )
        with _LOCK:
            _JOBS[job_id].update(
                status="done",
                result_path=str(video_path),
                finished_at=time.time(),
            )
    except Exception:
        with _LOCK:
            _JOBS[job_id].update(
                status="error",
                error=traceback.format_exc(),
                finished_at=time.time(),
            )


def start_job(channel_key: str, seed: dict) -> str:
    """Raises RuntimeError if a job is already running (enforced by the
    caller returning 409 — see webapp/app.py)."""
    with _LOCK:
        if any(j["status"] == "running" for j in _JOBS.values()):
            raise RuntimeError("A generation job is already running.")
        job_id = uuid.uuid4().hex
        _JOBS[job_id] = {
            "id": job_id,
            "channel_key": channel_key,
            "seed": seed,
            "status": "running",
            "log": [],
            "current_progress": None,
            "result_path": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
        }
    thread = threading.Thread(target=_run_job, args=(job_id, channel_key, seed), daemon=True)
    thread.start()
    return job_id


def get_job(job_id: str) -> dict:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def any_job_running() -> bool:
    with _LOCK:
        return any(j["status"] == "running" for j in _JOBS.values())
