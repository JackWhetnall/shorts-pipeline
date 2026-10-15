# 103 — A job waiting on a batch steps aside

**Status:** active. It replaces decision 102's two-hour limit on picture
batches.

## What the owner asked

Decision 102 cut a picture batch's wait to two hours, then drew the rest
at full price. The owner didn't want to lose the batch price: "There
should be plenty of time between videos - but is the issue that the
batching is stuck in series, rather than parallel?" They also asked
whether a cheap checker agent should watch the batches.

## What was found

The waiting itself was the problem, not the batch. The app runs one job
at a time, for all channels together (`jobs.start_job` queues behind
whatever is running). The teaser job spent 16 hours polling a stuck
OpenAI batch while still holding that one place. Every other job waited
behind it, and the autopilot started nothing else for the channel.

A checker agent isn't needed. A batch's status is a free API call that
the waiting code already makes every few minutes. The problem was only
that the wait held everything else up.

## Decision

- **A wait reports itself.** `job_context.waiting_on_batch()` wraps both
  waits: Claude's (`llm._wait_for`) and OpenAI's (`images.draw_batch`).
  The job is marked `waiting` while it's in one. The count goes up and
  down, so calls made side by side are all covered.
- **A waiting job steps aside.** While its `waiting` count is above zero:
  - the next queued job starts;
  - the waiting job carries on in its own thread when the batch is back;
  - only a job that is actually working holds the one place
    (`_occupying`), so two jobs never work at once;
  - its channel may start another job.
- **The autopilot moves another film on.** `_busy` ignores waiting jobs,
  and `_next_film` skips films that already have a stage in a job. So
  while one film's teasers wait on OpenAI, the next film's storyboard can
  start, at batch prices.
- **OpenAI gets its full 24 hours.** `BATCH_WAIT_MAX` is 25 hours. Only
  past OpenAI's own window is a batch cancelled and the rest drawn at
  full price.
- **Activity shows "Waiting on batch"** on a job that has stepped aside.
