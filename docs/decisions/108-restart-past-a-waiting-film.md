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

## What resuming a storyboard needed

Picking the batch up from the journal wasn't enough on its own. A
storyboard resumed after a restart would have:
- **redrawn every picture.** A storyboard stage starting again moves its
  folder aside and keeps only the pictures the film had recorded, and an
  interrupted first run hasn't recorded any yet;
- **asked for different redraws.** The picture checks would run again and
  could ask for different redraws, leaving the batch already sent paid
  for and unused.

Now:
- **The folder is kept.** The stage saves a `stills_folder` checkpoint
  when it sets up its folder; a resumed run keeps that folder as it is.
- **Checks and redraw rounds are saved.** `stills.draw` saves each check's
  answer and each finished redraw round, so a resumed run asks for the
  same redraws (picking up the batch already sent) and doesn't draw a
  finished round again.

The two storyboards in flight when this was written (t0004, t0005) began
under the old code without these checkpoints. They were left to finish
rather than be resumed.
