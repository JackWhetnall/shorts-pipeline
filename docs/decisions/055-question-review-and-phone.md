# 055 — Reviewing a quiz question by question, and the app on a phone

**Status:** active. Builds on the question bank of [050](050-question-bank.md)
and its independent rater.

## What happened

The owner asked for two things at once.

**A better way to check a quiz.** Checking a round meant reading its whole
script, host patter and all, to find the ten questions. And one bad
question out of ten meant writing the whole round again. They wanted:
- the questions and answers laid out, with nothing else;
- to say of each one that it's fine, too easy, too hard, or wrong (and why);
- a bad question swapped for another without rewriting the round;
- a question that's merely at the wrong level not lost: "it would move to
  an easier or harder category as implied", and only gone if they say so;
- Create video's flow, where scripts and videos are made without stopping,
  left alone.

**The workflow on their phone**, over the home network: what's up for
review, making new videos. Not the whole app.

## What was decided

### Question review (`pipeline/quiz_review.py`, `web/blueprints/quiz_review.py`)

It works on a round's script wherever the script lives. Nothing about
making videos changes: review is something you can go and do, not a step
the flow waits on.

- **A round written ahead of its video**: Topic plan → *Check questions*,
  or on the phone the channel's *rounds written ahead*. It is changed in
  place, so the video made from it later asks the new questions.
- **A made short**: *Check the questions* in Review (PC and phone). It is
  changed as a draft beside the video (`_script_draft.json`). Then
  *Remake with these changes* discards the short, stores the draft on its
  subtopic, and makes it again with the same number. Or *Drop the changes*.

The verdicts:
- **Fine**: marked checked. Its bank level is confirmed
  (`owner_level`), and a question the fact check had held is released.
- **Too easy / too hard**: the question moves in the bank to the channel's
  next easier or harder level (a step and a half past the ends), freed
  for a round at that level. A question from outside the bank (built on a
  fact or written with the round) is taken into the bank at that level.
  A replacement is swapped in.
- **Wrong** (a reason is optional): the question is rejected in the bank,
  and kept so it's never written again. A replacement is swapped in.

**Replacements** come from the bank at the round's level, in the
category's own areas first, then borrowed. They must not repeat anything
the channel has asked, anything the owner turned down, or clash with the
rest of the round (the same checks a round is built with). If the bank has
nothing, one small batch (about 3 cents) is written for it. Picture rounds
write and check fresh candidates of their kind instead.

Only the swapped question's two lines are rewritten, in one small call
(under a cent): the host's lead-in and the reveal. The hook, intro and
sign-off stay. If that call fails, the old lead-in and the plain answer
are used.

**Re-rating keeps the owner's level.** `rate_bank` sets
`level = COALESCE(owner_level, rated level)`. Without that, the next
re-rate would undo every "too easy".

**A remake pays only for the lines that changed.** Every voiced segment is
now kept in `cache/voice_segments/` for 60 days, keyed by exactly what
was said and how (text after respelling, voice, model, speed). Only a
remake reads the cache (`Seed.remake_of`). A video discarded for its
voice must be voiced afresh, so ordinary makes don't use it. The voice
quota check counts only what will actually be voiced. Shorts made before
this have nothing cached, so remaking one voices all of it once.

**Made shorts keep their script** (`_script.json`, written in
`run._finish`). The round sidecar now keeps each question's `bank_id`.
Shorts made before this are rebuilt from what was kept: every spoken line
is in `_meta.txt`, and the round is in `_quiz.json`. Bank ids are found by
the questions' wording. If the rebuild can't line up, the page is read
only: verdicts still teach the bank, but nothing is swapped.

A remade short's old round is dropped from the channel's record of what
it asked (`quiz.forget`). The questions swapped out of it can then be
asked in another round. Until the remake, that record keeps them out, so
releasing a moved question at once is safe.

### The phone (`core/phone_access.py`, `web/blueprints/phone.py`)

- **Off by default.** Then the app listens only on this PC, as before.
  Turned on (the new **Phone** page, on the PC only), it listens on the
  home network too. It restarts itself to do so once nothing is being
  made (`code_freshness.request_restart`).
- **An access code** (six digits) is required of anything not from this
  PC. It's checked before CSRF, on every request. A phone enters it once
  and stays signed in for a year. A new code signs every phone out. Eight
  wrong codes from one address lock that address out for a quarter of an
  hour. Phone access can only be turned on or off from the PC.
- **`/m`** is its own small layout (the PC's stylesheet assumes a wide
  window). It shows:
  - what's being made, refreshing itself;
  - what's waiting for review, with a player, the checks' flags, Approve,
    Discard with a reason, and Check the questions;
  - per channel, Make it: the next video, or one picked from the plan,
    started without the seed review.
  "Full app" is there for anything else.
- **Windows Firewall** must let the phone in. That's a system setting, so
  it's the owner's to add (TASKS.md), limited to private networks.

## What was rejected

- **Regenerating a round with an "avoid" note** when one question is bad:
  it rewrites and re-checks all ten questions and re-voices all of them,
  to fix one.
- **Deleting a question called too easy or too hard**: the owner's point
  was that it isn't a bad question, just at the wrong level.
- **Re-voicing only the changed lines by cutting the old video's audio**:
  the stitched track has fades, pads and no per-segment word timings.
  Keeping each segment as it's voiced is exact.
- **The phone on the whole internet** (a tunnel or port forward): no
  HTTPS, and a six-digit code is a lock for a home network, not for the
  world.
- **No code on the home network**: anyone on the Wi-Fi (guests, a
  compromised device) could discard or make videos, which spends money.

## Later (1 Oct): a hiccup at the voice service costs only what it hit

A video failed because ElevenLabs didn't answer one line within a minute.
The message said retrying usually works, and the retry voiced all 23
lines again. Two changes:
- **A request that times out or can't connect is now tried again by
  itself**, with the same backoff as rate limiting (up to five more
  tries). Before, only error statuses were retried, and a timeout failed
  the video at once.
- **Every line is kept as it lands**, in the voice cache above. The job
  also records which lines it has (a `voiced_segments` checkpoint), so
  retrying it reuses those and voices only the rest. The quota check
  counts only those too. A new job still voices everything afresh, for
  the reason given above.

Picture questions also wrap now. They had been held to one line, and a
78-character country question ran off the card even at the smallest
size. They now wrap to two or three lines, with the picture a little
smaller to make room.
