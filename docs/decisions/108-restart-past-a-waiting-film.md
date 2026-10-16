# 108 — The app restarts past a film stage that's only waiting

**Status:** active.

## What the owner saw

The app restarts itself onto new code once nothing is running
(`code_freshness.watch`). A storyboard waiting on its picture batch
counted as running, so the restart, and every fix with it, waited hours
for OpenAI.

## Decision

- **The restart waits only for work being done** (`jobs.busy_for_restart`):
  - a job that is working, not just waiting;
  - anything queued;
  - a short waiting on a batch, since nothing would resume a short.

  A film stage that is only waiting on a batch no longer holds it.
- **A waiting film stage is resumed after the restart**
  (`jobs.resume_waiting`, run at startup before the scheduler starts).
  The restart marks it interrupted; it is retried under its own id. Its
  batch is picked up from the journal (Claude's or OpenAI's), so nothing
  is paid for twice; the stage's earlier steps reuse what they saved.
- Two of a channel's films caught waiting can both be resumed
  (`retry_job(behind=True)`).
