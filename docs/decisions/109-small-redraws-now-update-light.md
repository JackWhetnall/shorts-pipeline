# 109 — Small redraws drawn now; an update light; honest batch times

**Status:** active.

## What happened

- **Small redraw batches stalled.** Two storyboards waited on OpenAI
  picture batches for 7 to 10 hours with nothing drawn: one batch held 1
  picture, the other 12. A batch takes as long for one picture as for
  sixty, so a small batch saves a few cents and can cost the night.
- **The owner couldn't tell whether the app was on the latest code.**
  Nothing showed that an update was waiting for the restart.
- **Activity's batch estimates were wrong for films.** Activity showed
  "Batch: ~42 min" on storyboards. That estimate comes from Claude's
  batches (about two minutes each) and means nothing for OpenAI's.
- **Teaser endings assumed knowledge viewers don't have.** "Full video's
  got it" is jarring: a Shorts viewer doesn't know a full video exists.

## Decision

- **Small rounds are drawn now.** A storyboard round of fewer than
  `IMAGE_BATCH_MIN` (6) pictures is drawn straight away at full price,
  three at a time, even in batch mode. Large first rounds still go as one
  batch.
- **An update light.** When new code is waiting for the restart, a small
  refresh icon shows in the top bar, with the tooltip "Update ready ·
  restarts when idle". It reads `code_freshness.update_pending`, which
  checks at most every ten seconds.
- **Batch times are shown as they are.** On Activity, a job waiting on a
  batch shows "Waiting on batch · 7 h", timed from `waiting_since`. A film
  stage at batch prices shows just "Batch", with no made-up estimate.
- **Teaser endings say there's a full video, and where.** Examples:
  "Check out our page for the full explanation." "Go watch the full video
  on our channel." "…This and more, explained on our channel." Bare "full
  video's got it" and "watch the full video" lines are ruled out.
