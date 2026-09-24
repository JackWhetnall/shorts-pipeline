"""
Start the web app with no console window, for Windows Task Scheduler.

    pythonw tools/start_web.pyw

`pythonw` has no console, so stdout and stderr go nowhere; everything
the app would print goes to cache/web.log instead, so there is still
something to read when it misbehaves. The log is started fresh once it
passes a few megabytes. Same flags as `python -m web`, which is what this
runs; the scheduler is on.

Registered as the "Shorts Pipeline" logon task. Remove it from Task
Scheduler, or with:
    schtasks /Delete /TN "Shorts Pipeline" /F
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "cache" / "web.log"
MAX_LOG_BYTES = 5 * 1024 * 1024


def _redirect_output() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_LOG_BYTES else "a"
    stream = open(LOG_PATH, mode, encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = stream


if __name__ == "__main__":
    _redirect_output()
    sys.argv = [sys.argv[0]]
    from web.__main__ import main
    main()
