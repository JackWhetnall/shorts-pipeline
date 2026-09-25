"""
Is the running app the code on disk? And if not, restart it cleanly.

The app is a long-running process (started at logon), and pipeline code
is imported lazily when the first job needs it. So after an update, a
job could run new pipeline code against old core code already in memory:
the first time this happened, a render failed at its very last step with
"'ChannelConfig' object has no attribute 'sound'", after its script and
voiceover had been paid for.

So the app notes a fingerprint of its code when it starts. New jobs are
refused while it's stale (with a message saying why), and a watcher
restarts the process with its original command as soon as nothing is
running. A job started a minute later runs entirely on the new code.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parent.parent
WATCHED = ("core", "pipeline", "web")
CHECK_EVERY = 20              # seconds
RESTART_DELAY = 3             # seconds for the old process to let go of the port

_started_with = None


def fingerprint() -> tuple:
    """Every watched Python file's name, size and modification time."""
    entries = []
    for folder in WATCHED:
        for path in sorted((ROOT / folder).rglob("*.py")):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((str(path.relative_to(ROOT)), stat.st_size, stat.st_mtime_ns))
    return tuple(entries)


def remember() -> None:
    """Called once, as the app starts."""
    global _started_with
    _started_with = fingerprint()


def is_stale() -> bool:
    return _started_with is not None and fingerprint() != _started_with


def restart() -> None:
    """Start this app again with its original command, a few seconds from
    now (so the port is free), and end this process."""
    command = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])
    # The new copy has no console (it's detached), so its output goes to
    # the app's log, the same one the logon-task copy writes.
    log_path = ROOT / "cache" / "web.log"
    relauncher = ("import subprocess, sys, time; time.sleep(%d); "
                  "out = open(%r, 'a', encoding='utf-8'); "
                  "subprocess.Popen(sys.argv[1:], cwd=%r, stdout=out, stderr=out, "
                  "stdin=subprocess.DEVNULL)" % (RESTART_DELAY, str(log_path), str(ROOT)))
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, "-c", relauncher, *command], cwd=str(ROOT),
                     creationflags=flags, close_fds=True)
    log.info("Code changed on disk: restarting to pick it up.")
    os._exit(0)


def watch(is_busy) -> None:
    """In the background: restart once the code has changed and
    `is_busy()` says no video is being made."""
    def loop():
        while True:
            time.sleep(CHECK_EVERY)
            try:
                if is_stale() and not is_busy():
                    restart()
            except Exception:  # noqa: BLE001 - a watcher must never take the app down
                log.exception("code freshness check failed")

    threading.Thread(target=loop, name="code-freshness", daemon=True).start()
