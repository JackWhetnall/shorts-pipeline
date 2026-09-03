"""
In-memory background job registry for triggering video generation from
the web UI without blocking the request that started it.

Only ONE job actually executes at a time, globally, across every channel
- not per-channel. Earlier this allowed different channels to run
concurrently (their own worker threads, own captured logs, all correctly
isolated - the isolation work below still matters for THAT), but real use
showed that's the wrong default: each job already fans out several
parallel ElevenLabs calls and stock-footage downloads internally, so two
channels generating at once multiplies that fan-out and risks hammering
the same external APIs (ElevenLabs, Pexels/Pixabay) harder than they can
take. Instead, starting a job for a channel while another is already
running QUEUES it (status "queued") rather than either rejecting it or
running it in parallel; when the running job finishes, the oldest queued
job is started next (FIFO, see _advance_queue). A channel that already
has a running OR queued job still can't queue a second one for itself -
see start_job.

Capturing each job's output correctly under real parallelism is the part
that isn't obvious: every module in this pipeline uses plain print(), not
a logger that could be scoped per job, and print() always writes to
whatever sys.stdout currently is - a single process-wide object, not
something threads each get their own copy of. The old design (still
visible in git history) swapped sys.stdout/stderr for the duration of one
job via contextlib.redirect_stdout - fine for exactly one job at a time,
actively wrong for two: job B's redirect would either stomp on job A's
capture or get stomped on itself, and unwinding B's context manager could
restore the wrong "original" stream.

The fix here doesn't swap sys.stdout per job at all. A single
_DispatchStream is installed ONCE as the real sys.stdout/sys.stderr
(idempotent - start_job only installs it if it isn't already there).
Every job thread stamps its own job_id into job_context (a small shared
thread-local — see that module) the moment it starts; the dispatcher's
write() reads THAT to decide which job's buffer to append to, falling
back to the real original stream for anything running outside a tracked
job thread (the Flask main thread, etc). Because threading.local()
genuinely is per-OS-thread storage, two job threads calling print() at
the literal same instant each get routed to their own buffer - no
interleaving, no shared mutable redirect target.

job_context is a SEPARATE module (project root, not here) specifically
so a job's own internal parallelism (tts_captions.py/footage_library.py
running several ElevenLabs calls or downloads at once via
job_context.parallel_map) can propagate the same job id into ITS worker
threads too — those threads don't inherit whatever this module tracks on
their own, so without a shared place to read/write it, output from a
job's parallel sub-work would silently fall through to the real stdout
instead of that job's visible log. job_context also carries granular,
structured progress the same way: pipeline code calls
job_context.report_detail(section, item_index, patch) (e.g. "segment 2/3
of the voiceover is now synthesizing", "clip 5/12 is now downloading")
without importing this module directly (would drag Flask into a plain
CLI run); _update_detail below is registered as job_context's one sink at
import time, merging each patch into job["detail"] so the frontend's
granular progress panel can render it - see create_video.html's
"Details" box.
"""

import io
import json
import re
import sys
import threading
import time
import traceback
import uuid

import job_context

_LOCK = threading.Lock()
_JOBS = {}
_STREAMS = {}  # job_id -> _JobCaptureStream, only while that job is running
_QUEUE = []  # job_ids waiting to start, oldest first; protected by _LOCK

_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")

# Matched against each COMPLETED log line, in order, to drive the
# frontend's visual stage tracker — no new pipeline instrumentation
# needed, these are text this app already prints today (main.py's
# numbered stage headers, video_assemble.py's own status lines).
# job["stage"] is set to the highest-numbered match seen so far (never
# moves backward), so an unrelated line in between two markers doesn't
# reset anything.
_STAGE_MARKERS = [
    (1, re.compile(r"^\[1/4\]")),                         # main.py: script
    (2, re.compile(r"^\[2/4\]")),                         # main.py: voiceover
    (3, re.compile(r"^\s*\[video\] matching footage")),   # video_assemble.py
    (4, re.compile(r"^\s*\[video\] rendering video")),    # video_assemble.py - real % starts here
    (5, re.compile(r"^\[4/4\]")),                         # main.py: metadata/description
]
STAGE_COUNT = len(_STAGE_MARKERS)


def _match_stage(line: str):
    for stage, pattern in _STAGE_MARKERS:
        if pattern.match(line):
            return stage
    return None


def _update_detail(job_id: str, section: str, item_index, patch: dict):
    """job_context's registered detail sink (see module docstring).
    item_index=None merges patch into job["detail"][section]'s top-level
    keys (running totals like "8 shots needed"); an int index merges into
    job["detail"][section]["items"][item_index] instead, growing the list
    as needed - one row per TTS segment or per fetched clip."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        detail = job.setdefault("detail", {})
        sec = detail.setdefault(section, {"items": []})
        if item_index is None:
            sec.update(patch)
        else:
            items = sec.setdefault("items", [])
            while len(items) <= item_index:
                items.append({})
            items[item_index].update(patch)
    _persist(job_id)


job_context.set_detail_sink(_update_detail)


def _persist(job_id: str):
    """Writes this job's current state to job_state/<job_id>/job.json (via
    job_context's checkpoint dir) so it survives a process restart instead
    of vanishing - load_persisted_jobs reloads these at startup. Never
    called while holding _LOCK (it acquires its own, briefly, just to
    snapshot the dict) - every call site below releases _LOCK first.
    Best-effort: a disk hiccup here must never break real generation."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        snapshot = dict(job)
    try:
        d = job_context.checkpoint_dir(job_id)
        if d is None:
            return
        (d / "job.json").write_text(json.dumps(snapshot), encoding="utf-8")
    except Exception:
        pass


class _JobCaptureStream(io.TextIOBase):
    """Captures one job's output, splitting on whichever line terminator
    (\\n or \\r) comes first."""

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
                job["progress_percent"] = None
                stage = _match_stage(line)
                if stage is not None:
                    job["stage"] = max(job.get("stage", 0), stage)
        _persist(self.job_id)

    def _set_progress(self, line: str):
        if not line.strip():
            return
        with _LOCK:
            job = _JOBS.get(self.job_id)
            if job is not None:
                job["current_progress"] = line
                job["progress_percent"] = _extract_percent(line)

    def flush(self):
        pass


def _extract_percent(line: str):
    """Pulls a leading tqdm-style percentage ("chunk: 45%|###...") out of
    a progress line, or None if this line doesn't carry one - most of the
    pipeline's stages just print status text, only the final video encode
    step reports a real percentage."""
    m = _PERCENT_RE.search(line)
    if not m:
        return None
    return max(0, min(100, int(m.group(1))))


class _DispatchStream(io.TextIOBase):
    """Installed once as the real sys.stdout/sys.stderr. Routes each
    write() to the calling THREAD's job buffer if it's running inside a
    tracked job, otherwise passes through to the real original stream
    untouched - so ordinary Flask request handling, the CLI, etc. are
    completely unaffected."""

    def __init__(self, fallback):
        self._fallback = fallback

    def _current_stream(self):
        job_id = job_context.get_job_id()
        return _STREAMS.get(job_id) if job_id else None

    def write(self, s: str) -> int:
        stream = self._current_stream()
        return stream.write(s) if stream is not None else self._fallback.write(s)

    def flush(self):
        stream = self._current_stream()
        if stream is None:
            self._fallback.flush()

    def isatty(self):
        return self._fallback.isatty()


def _ensure_dispatch_installed():
    if not isinstance(sys.stdout, _DispatchStream):
        sys.stdout = _DispatchStream(sys.stdout)
    if not isinstance(sys.stderr, _DispatchStream):
        sys.stderr = _DispatchStream(sys.stderr)


# What job["stage"] means in plain English - used both for a friendly
# "interrupted while X" message (load_persisted_jobs) and could be reused
# anywhere else that wants a human phrase instead of a bare stage number.
_STAGE_LABELS = {
    0: "getting started",
    1: "writing the script",
    2: "generating the voiceover",
    3: "matching footage",
    4: "assembling the video",
    5: "finishing touches",
}


def _stage_label(stage: int) -> str:
    return _STAGE_LABELS.get(stage, "an unknown step")


def _guess_service(exc: Exception) -> str:
    request = getattr(exc, "request", None)
    url = getattr(request, "url", "") or ""
    if "elevenlabs" in url:
        return "The voice service (ElevenLabs)"
    if "pexels" in url:
        return "The stock footage service (Pexels)"
    if "pixabay" in url:
        return "The stock footage service (Pixabay)"
    if "anthropic" in url:
        return "The AI service"
    return "An external service"


def _friendly_error(exc: Exception) -> str:
    """A short, plain-English description of what went wrong, shown
    prominently in the UI. The full traceback still goes to
    job["error_traceback"] (available in the collapsed log for anyone who
    actually needs it) - a raw "HTTPError: 429" or a Python stack trace is
    exactly what someone without this code open shouldn't have to parse
    just to find out whether their video got made."""
    import requests

    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        service = _guess_service(exc)
        if status == 429:
            return (f"{service} is temporarily rate-limiting requests. This usually "
                     "resolves on its own within a few minutes - retrying should work.")
        if status in (401, 403):
            return f"{service} rejected the request — check that its API key is set correctly."
        if status is not None and status >= 500:
            return f"{service} is temporarily having problems on their end. Retrying should work once it recovers."
        return f"{service} rejected a request (HTTP {status})."
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return "Couldn't reach an external service — check your internet connection and try again."
    if isinstance(exc, FileNotFoundError) and "manifest.json" in str(exc):
        return "The footage library has no usable clips yet — add some before generating a video."
    return (f"Something went wrong while generating this video ({type(exc).__name__}). "
            "The full technical details are in the log below.")


def _run_job(job_id: str, channel_key: str, seed: dict):
    import main as main_module
    import webapp.channel_store as channel_store

    job_context.set_job_id(job_id)
    _STREAMS[job_id] = _JobCaptureStream(job_id)
    try:
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
        # Nothing checkpointed is needed once the real output exists.
        # Kept for error/interrupted jobs specifically so a retry has
        # something to resume from - see retry_job.
        job_context.clear_checkpoints(job_id)
    except Exception as e:
        with _LOCK:
            _JOBS[job_id].update(
                status="error",
                error=_friendly_error(e),
                error_traceback=traceback.format_exc(),
                finished_at=time.time(),
            )
    finally:
        _STREAMS.pop(job_id, None)
        _persist(job_id)
        _advance_queue()


def _spawn(job_id: str, channel_key: str, seed: dict):
    thread = threading.Thread(target=_run_job, args=(job_id, channel_key, seed), daemon=True)
    thread.start()


def _advance_queue():
    """Called whenever a job finishes (done or error) - starts the next
    queued job, if any. FIFO: _QUEUE is only ever appended to (start_job/
    retry_job) or popped from the front (here)."""
    with _LOCK:
        if not _QUEUE:
            return
        next_id = _QUEUE.pop(0)
        next_job = _JOBS.get(next_id)
        if next_job is None:
            return
        next_job["status"] = "running"
        next_job["started_at"] = time.time()
        channel_key, seed = next_job["channel_key"], next_job["seed"]
    _persist(next_id)
    _spawn(next_id, channel_key, seed)


def start_job(channel_key: str, seed: dict) -> str:
    """Raises RuntimeError if a job is already running OR queued for THIS
    channel (enforced by the caller returning 409 — see webapp/app.py).
    Otherwise: if nothing is currently running (globally), this job starts
    immediately; if something is, this job is queued (status "queued")
    and starts automatically once its turn comes - see _advance_queue.
    Different channels queue up rather than running at the same time (see
    module docstring for why)."""
    _ensure_dispatch_installed()
    with _LOCK:
        if any(j["status"] in ("running", "queued") and j["channel_key"] == channel_key for j in _JOBS.values()):
            raise RuntimeError(f'A generation job is already running or queued for "{channel_key}".')
        running_now = any(j["status"] == "running" for j in _JOBS.values())
        job_id = uuid.uuid4().hex
        now = time.time()
        _JOBS[job_id] = {
            "id": job_id,
            "channel_key": channel_key,
            "seed": seed,
            "status": "queued" if running_now else "running",
            "log": [],
            "current_progress": None,
            "progress_percent": None,
            "stage": 0,
            "stage_total": STAGE_COUNT,
            "detail": {},
            "result_path": None,
            "error": None,
            "error_traceback": None,
            "queued_at": now,
            "started_at": None if running_now else now,
            "finished_at": None,
        }
        if running_now:
            _QUEUE.append(job_id)
    _persist(job_id)
    if not running_now:
        _spawn(job_id, channel_key, seed)
    return job_id


def retry_job(job_id: str) -> str:
    """Re-runs an interrupted or failed job, KEEPING its job id (unlike
    start_job, which always mints a fresh one) - checkpoints are stored
    under job_state/<job_id>/, so main.py/tts_captions.py/
    footage_library.py each transparently reuse whatever already
    completed (script, voiceover, footage picks) instead of redoing it,
    the same way a channel's own module-level generate_video_from_seed
    call always has. Raises RuntimeError if the job isn't in a retryable
    state, doesn't exist, or its channel already has something running/
    queued."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise RuntimeError("This job no longer exists.")
        if job["status"] not in ("error", "interrupted"):
            raise RuntimeError(f'This job is currently "{job["status"]}" and cannot be retried.')
        channel_key, seed = job["channel_key"], job["seed"]
        if any(j["status"] in ("running", "queued") and j["channel_key"] == channel_key and j["id"] != job_id
               for j in _JOBS.values()):
            raise RuntimeError(f'A generation job is already running or queued for "{channel_key}".')
        running_now = any(j["status"] == "running" for j in _JOBS.values())
        now = time.time()
        job.update(
            status="queued" if running_now else "running",
            log=[], current_progress=None, progress_percent=None,
            stage=0, detail={}, error=None, error_traceback=None, result_path=None,
            queued_at=now, started_at=None if running_now else now, finished_at=None,
        )
        if running_now:
            _QUEUE.append(job_id)
    _ensure_dispatch_installed()
    _persist(job_id)
    if not running_now:
        _spawn(job_id, channel_key, seed)
    return job_id


def load_persisted_jobs():
    """Called once at process startup (webapp/app.py) - reloads every
    job_state/<job_id>/job.json so job history/status survives a server
    restart instead of vanishing into an unexplained 404 (this is what a
    real incident exposed: an in-flight job's process died, the browser
    kept polling a now-nonexistent id, and there was no way to even see
    what had happened to it). A job that was "running" or "queued" when
    the PREVIOUS process stopped becomes "interrupted" here - never
    silently resumed on its own; retry_job is the explicit, user-
    initiated way to pick it back up, reusing whatever checkpoints
    (script/voiceover/footage picks) already completed."""
    root = job_context.CHECKPOINT_ROOT
    if not root.exists():
        return
    with _LOCK:
        for job_dir in root.iterdir():
            job_path = job_dir / "job.json"
            if not job_path.exists():
                continue
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if job.get("status") in ("running", "queued"):
                job["status"] = "interrupted"
                job["error"] = (
                    "This video's generation was interrupted (the app restarted or "
                    f"stopped) while {_stage_label(job.get('stage', 0))}. Nothing was "
                    "lost - retrying will reuse whatever already completed."
                )
                job["error_traceback"] = None
                job["finished_at"] = time.time()
            _JOBS[job["id"]] = job


def _with_queue_position(job: dict) -> dict:
    d = dict(job)
    d["queue_position"] = (_QUEUE.index(job["id"]) + 1) if job["id"] in _QUEUE else None
    return d


def get_job(job_id: str) -> dict:
    with _LOCK:
        job = _JOBS.get(job_id)
        return _with_queue_position(job) if job else None


def get_running_job_for_channel(channel_key: str):
    """The current running-OR-queued job for one channel, or None — used
    to resume a page's progress view after navigating away and back
    (including while still queued), and by the home page's per-card
    progress bars."""
    with _LOCK:
        for job in _JOBS.values():
            if job["status"] in ("running", "queued") and job["channel_key"] == channel_key:
                return _with_queue_position(job)
    return None


def get_latest_terminal_job_for_channel(channel_key: str):
    """Most recent error/interrupted job for a channel, or None - lets the
    create-video page proactively surface "your last attempt was
    interrupted while X — retry?" on load, without the user needing to
    already know a job id (nothing else exposes one)."""
    with _LOCK:
        candidates = [j for j in _JOBS.values()
                      if j["channel_key"] == channel_key and j["status"] in ("error", "interrupted")]
        if not candidates:
            return None
        best = max(candidates, key=lambda j: j.get("finished_at") or j.get("queued_at") or 0)
        return _with_queue_position(best)


def list_active_jobs() -> dict:
    """{channel_key: job} for every currently running-or-queued job — one
    call for the home page to check every channel at once instead of N
    lookups."""
    with _LOCK:
        return {j["channel_key"]: _with_queue_position(j) for j in _JOBS.values() if j["status"] in ("running", "queued")}


def any_job_running() -> bool:
    with _LOCK:
        return any(j["status"] == "running" for j in _JOBS.values())
