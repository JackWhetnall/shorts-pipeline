# 010 — Logging instead of stdout capture

**Status:** active. Supersedes the `_DispatchStream` design.

## Decision

Pipeline code calls `logging`. The job runner attaches a handler that
routes each record to the right job using a `contextvars` job id. Encode
progress arrives through a proglog hook. Nothing patches `sys.stdout`.

## What this replaces

Every module used `print()`, and `print()` writes to whatever
`sys.stdout` currently is — one process-wide object, not something
threads each get a copy of. To capture per-job output, the runner
installed a dispatching stream object as the real `sys.stdout` and
`sys.stderr`, read a thread-local to decide whose buffer each `write()`
belonged to, and reassembled lines by hand, splitting on whichever of
`\n` or `\r` came first.

That was careful, correct code, and about 150 lines of it. It also had a
blind spot: anything writing to the real stream without going through
`print()` — a vendor library, a subprocess — either escaped capture or
corrupted the line assembly.

The standard library solves this. A handler plus a contextvar is a dozen
lines, gives levels and timestamps for free, and cannot be confused by
what anyone else writes to stdout.

## Two related simplifications

**Stage tracking.** Stages used to be recovered by regex-matching the
pipeline's own printed output (`^\[1/4\]`, `^\s*\[video\] rendering
video`) — parsing our own log as an API. Rewording a log line silently
stopped the UI's stage tracker, with no error anywhere.
`report_stage(n)` is now an explicit call, and the stage list lives in
one place that both the pipeline and the frontend read.

**Encode progress.** The percentage used to be pulled out of the tqdm
bar's carriage-return-terminated stderr writes with `(\d{1,3})\s*%`.
moviepy drives its bars through proglog, which supports custom logger
subclasses, so the number is now read from the value proglog already
computes. That was the last reason to intercept a standard stream at all.

## contextvars, not threading.local

The old design stamped a job id into thread-local storage and then
hand-propagated it into every worker a job spawned, because a
`ThreadPoolExecutor` worker gets its own empty thread-local and would
otherwise lose the attribution. `contextvars.copy_context()` does exactly
that propagation as a language feature.
