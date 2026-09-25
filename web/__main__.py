"""
Run the web app:  python -m web

Debug mode is off by default. It used to be hardcoded on, and the
Werkzeug debugger is an interactive Python console — bound to localhost,
so the risk was low, but "on unless you remember to turn it off" is the
wrong default for something being built out rather than wound down. Pass
--debug when you actually want it.
"""

from __future__ import annotations

import argparse

from core import jobs, scheduler
from core.logging_setup import get_logger
from web import create_app

log = get_logger(__name__)


def already_running(host: str, port: int) -> bool:
    """Whether something already answers on this port.

    Windows lets two processes listen on the same port at once, silently.
    A logon-task copy left running from before an update went on serving
    requests with old code in memory, alongside a freshly started copy,
    and every settings page and render failed in ways that looked like the
    update was broken.
    """
    import socket
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Shorts Pipeline web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true",
                        help="Enable the Werkzeug debugger and auto-reload.")
    parser.add_argument("--no-scheduler", action="store_true",
                        help="Don't run scheduled generations in this process.")
    args = parser.parse_args()

    if already_running(args.host, args.port):
        log.error(f"Another copy of the app is already running at "
                  f"http://{args.host}:{args.port}/ - not starting a second one. Stop "
                  f"the other copy first (Task Manager: python/pythonw).")
        raise SystemExit(1)

    app = create_app(debug=args.debug)

    # Startup side effects live here, not at import time, so a test that
    # imports the app factory doesn't reload job history or start threads.
    restored = jobs.load_persisted_jobs()
    if restored:
        log.info(f"Restored {restored} job record(s) from the last session.")
    if not args.no_scheduler:
        scheduler.start_background()
    # Restart onto new code after an update, once nothing is running.
    if not args.debug:
        from core import code_freshness
        code_freshness.remember()
        code_freshness.watch(lambda: jobs.busy() or scheduler.busy())

    log.info(f"Open http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=args.debug,
            use_reloader=args.debug, threaded=True)


if __name__ == "__main__":
    main()
