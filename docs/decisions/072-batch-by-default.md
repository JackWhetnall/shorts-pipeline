# 072 — Batch prices by default, Accelerate when it's wanted now

**Status:** active. Extends [063](063-background-calls-at-batch-prices.md).

## What happened

Decision 063 sent the scheduler's videos, made hours ahead of their
slots, through the Message Batches API at half price. Videos the owner
started by hand still went at full price. On 6 October the owner asked
for that the other way round:

> "making videos should default to being queued and done by slow/batch
> API/cheaper generation unless specified by the user - they would go
> to the queue page and click 'accelerate' which would then bump it up
> to next in the queue and make it quickly"

## Decisions

**Every video is made at batch prices** (`jobs.start_job(ahead=True)` is
now the default). That covers Make this video, the quick and make-all
buttons, the phone, remakes and long quizzes as well as the scheduler.
Only an animation preview goes direct, since it's started in order to
be looked at.

**"Make it now, at full price"** is a tick box beside Make this video,
for when the owner is waiting at the time they start it.

**Accelerate** sits on each batch-price job on Activity and on the
channel's progress view. It:

- puts the job next in the queue;
- makes its calls direct from then on. A call already waiting on its
  batch finishes that wait: cancelling it would throw away a request
  that may be nearly done.

And because a job is now waiting on it, whatever is running stops
batching its own calls too (`someone_waiting`, as in 063). Otherwise
"next" could mean an hour behind a batch.

**A retry stays at batch prices** unless the job had been accelerated.
Before, a retry always went direct on the grounds that someone was
waiting. Under this decision that's what Accelerate says.

**No time estimate at batch prices.** The estimates come from videos
made direct (batch waits are left out of the history, 063), so for a
batch job the page says "At batch prices" and offers Accelerate rather
than a time it can't know.
