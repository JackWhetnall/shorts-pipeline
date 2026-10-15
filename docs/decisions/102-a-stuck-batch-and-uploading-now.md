# 102 — A stuck picture batch, and "Uploading now"

**Status:** active.

## What happened on the night of 14 to 15 October

Nothing was made overnight. At 17:13 the first film's teasers were
started again, at batch prices. They sent five pictures to OpenAI as one
batch. That batch then sat "in progress" for 16 hours with none of the
five drawn. `_wait_batch` waited up to 20 hours, and while one of a
channel's jobs runs, the autopilot starts nothing else for that channel.
The night's film (t0003) never started its storyboard. The first real
image batch had taken 40 minutes, so 20 hours of patience looked
harmless. It wasn't.

The teasers had already been marked "interrupted" at 17:23 while they
were still running. A preview copy of the app, started on another port
with `--no-scheduler`, ran decision 097's startup recovery against the
same files and saw the real app's "working" stage.

## Decision

- **A picture batch gets two hours** (`BATCH_WAIT_MAX`), counted from
  when it was sent, so a restart doesn't reset the clock. After that it
  is cancelled, the app waits up to ten minutes for what the batch had
  drawn, and anything still missing is drawn straight away at full
  price. A slow batch now costs at most two hours and the half-price
  saving on those pictures; it can no longer hold a channel all night.
- **Only the app that makes films runs startup recovery.** A copy started
  with `--no-scheduler` leaves the films' states alone.
- **The stuck batch was cancelled by hand on 15 October**, so the running
  app could finish its job and restart onto this code.

## "Uploading now"

The owner set the long-video time to 16:00 at 15:59. At 16:01 the page
showed video A going out on Friday and video B on Monday, as if A's slot
had been missed. In fact A was uploading: `publish_due` records the slot
as used before it sends, and an upload takes minutes, so the page moved
A to the next free slot while it went.

Now:
- `send` marks a video as being sent, and `schedule_for` gives it an
  `Uploading` time.
- `publish_queue.slot_text` shows "Uploading now" for a video being
  sent, "Going out now" for one whose slot has come but which hasn't
  started yet, and the slot time otherwise.
- The channel page, the review queue, the queued list, the gallery and
  Today all show these labels.
