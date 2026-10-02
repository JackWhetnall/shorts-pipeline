# 062 — Quiz rounds made ahead, ready to use

**Status:** active. Replaces writing a text round's questions while its
video is made (050's top-up, the fact-store fallback and free writing),
and the ladder of easier rounds written first (043) for text rounds.

## What happened

A Medium Ancient History round asked "whose code of laws survives from
ancient Babylon?". The bank had 5 Medium Ancient History questions. The
round then:
1. wrote 3 batches on the spot, which came back rated harder;
2. tried the fact store, which had nothing;
3. wrote the whole round itself, unrated and unfiled.

So it was off-topic and too hard at once.

The owner set out what they wanted:
- a new category ("Music Theory") should have 60 questions (10 per round
  times 6 difficulties) ready, and several times that;
- the difficulty inside a round should be consistent, and it should fit
  the round's theme;
- "a second set of General Knowledge" should need zero calculation and
  zero API calls;
- questions should never be written while a script is being written;
- a category that's running out should say so, and stop being offered
  for another set;
- questions should be set without writing each quiz's whole script.

## What was decided

**Rounds made ahead** (`pipeline/facts/rounds.py`, a `ready_rounds`
table). Each quiz channel keeps 3 rounds ready for every category at
every difficulty. Each round is:
- 10 questions within a tight band of its level: at most 0.75 easier or
  0.5 harder, widening only to the bank's second band, never its widest;
- spread over shapes and areas;
- free of clashes with itself and of repeats of anything the channel has
  asked or written, or any other ready round;
- ordered easiest first, so it warms up.

Named categories are assembled before General Knowledge, which can ask
anything, so it takes what they leave. Assembly is local, a few seconds
with no model calls. It runs hourly, and after imports and stocking.

**Planning another set** (Topic plan, "Plan another set", or the
scheduler's top-up) needs a complete set ready: a ready round at every
difficulty. Each new plan entry takes its round straight away, so it
costs nothing and needs no calculation.

**Making a video** takes the entry's round and writes only the host's
lines. If a question has been taken out of the bank since (on review),
the round is replaced. With no round ready, the job stops with "Science
has no Easy round ready" rather than writing questions. The automatic
picker skips entries whose category has run dry.

**Running dry is shown**: each category on the topic plan reads "3 sets
ready", "running low: N ready" or "running dry". The hourly stocking
writes where ready rounds are fewest, rather than where raw bank counts
are lowest.

**Picture rounds** (flags, countries) still write and check their
questions with the round, since they don't come from the bank.

## What was rejected

- **Writing the easier rounds first to pitch a harder one above them**
  (the ladder) for text rounds. It cost a full script per rung, and
  levels from the rater make it unnecessary.
- **Falling back to writing a round when the bank is short.** That's
  how the Babylon question got in. Being honest that a category is dry is
  better.
