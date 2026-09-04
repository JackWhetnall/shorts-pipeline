"""
Logging for both the CLI and the web app, replacing the process-wide
sys.stdout/sys.stderr hijack the job runner used to need.

The old design installed a dispatching stream object as sys.stdout, read
a thread-local to decide whose buffer each write() belonged to, and
reassembled lines by hand — about 150 lines of genuinely careful code,
solving a routing problem the standard library already solves. It also
had a real blind spot: anything that wrote to the real stdout without
going through print() (a vendor library, a subprocess) either escaped
capture or corrupted the line assembly.

Here, pipeline modules call logger.info(). The web app attaches a
JobLogHandler that routes each record to the job identified by the
contextvar in core.job_context — which propagates into worker threads on
its own. Nothing is swapped, nothing is global, and a third-party library
writing to stdout is simply irrelevant.

Format: the console handler prints the bare message, so CLI output looks
the same as the print() calls it replaces ("  [tts] synthesizing 1/4").
Levels above INFO get a prefix, because a warning that looks identical to
a status line isn't a warning.
"""

from __future__ import annotations

import logging
import sys

from core import job_context

LOGGER_NAMESPACE = "shorts"


def get_logger(name: str) -> logging.Logger:
    """`get_logger(__name__)` from anywhere in the project. Names are
    normalised under one namespace so a single call can set the level for
    everything this project logs without touching library loggers."""
    short = name.split(".")[-1]
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{short}")


class _ConsoleFormatter(logging.Formatter):
    """Bare message at INFO and below; a level prefix above it. Keeps
    ordinary progress output clean while making a warning visibly
    different from a status line."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.levelno <= logging.INFO:
            return message
        return f"{record.levelname.title()}: {message}"


class JobLogHandler(logging.Handler):
    """Routes each record to the job that produced it, via the contextvar
    in core.job_context.

    Records emitted outside a job (Flask request handling, startup) have
    no job id and are dropped here — the console handler already printed
    them. That check is why this can be attached once, permanently,
    rather than added and removed around each job.
    """

    def __init__(self, sink):
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        job_id = job_context.get_job_id()
        if not job_id:
            return
        try:
            self._sink.on_log(job_id, record.levelname.lower(), record.getMessage())
        except Exception:  # noqa: BLE001 - a logging failure must never break a render
            self.handleError(record)


def _make_console_utf8() -> None:
    """Print UTF-8 to the terminal on Windows.

    The Windows console defaults to a legacy code page, so an em dash or
    a curly quote in a log line comes out as a replacement character —
    which looks like a data bug and isn't one. Every file here is UTF-8;
    only the console needed telling.

    Wrapped because `reconfigure` needs Python 3.7+ and a real stream:
    under a captured or redirected stdout there may be nothing to
    reconfigure, and failing to prettify output must never stop the
    program.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_configured = False


def configure(level: int = logging.INFO, extra_handlers: list = None) -> logging.Logger:
    """Attach the console handler once, plus any extra handlers (the web
    app passes its JobLogHandler). Idempotent — safe to call from both a
    CLI entry point and an app factory in the same process."""
    global _configured
    root = logging.getLogger(LOGGER_NAMESPACE)
    root.setLevel(level)
    root.propagate = False

    if not _configured:
        _make_console_utf8()
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(_ConsoleFormatter())
        root.addHandler(console)
        _configured = True

    for handler in extra_handlers or []:
        if not any(isinstance(h, type(handler)) for h in root.handlers):
            root.addHandler(handler)

    return root
