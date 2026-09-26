# 044 — Long quizzes: finished shorts recut into widescreen videos

**Status:** active.

## What happened

The quiz shorts were the best output so far, and YouTube pays far more
for long-form video. It also offers a watch-hours route into the Partner
Program that a quiz can reach far sooner than ten million Shorts views.
The owner asked for:

- widescreen long videos, made from the same scripts;
- several rounds of different categories at one difficulty, with short
  joining remarks;
- two variants:
  - answers after each question, as in the shorts;
  - each round's questions first, then each question read again, with
    its row changing smoothly into the answer as it's given;
- on screen, the numbers 1-10 with each question appearing as it is read.

## What was decided

**Reuse the voice, don't repeat it.**

- A quiz short now saves where every question and spoken answer sits in
  its voice track (`<stem>_quiz.json`, from `quiz.save_round`).
- A long video cuts those pieces out. It only voices the host's joining
  lines: a welcome, a line into each round, a "pens down" before each set
  of answers, and a sign-off.
- Measured: $0.14 and about 450 characters for a two-round, 7.4-minute
  video. Six rounds come to about 1,000 characters, where voicing them
  afresh would take about 7,000.

**Shorts made before the timings file existed are rebuilt locally and
for free** (`longform.rebuild_round`):

- The ten clocks are the only silences of their length, so each
  question ends where a clock starts and each answer starts where it
  ends.
- An answer ends at the longest silence before the next clock. The host's
  own pauses can pass a second ("A nova. ... Not to be confused with
  supernova"), and taking the first long pause cut that answer short.
- Whisper finds the first question's start, and the displayed answer
  comes from what the host said first.
- Every cut was checked by transcribing it.

**Which rounds go in:**

- finished, undiscarded quiz shorts in different categories, at one
  difficulty, or "rising" (each round harder than the last);
- published ones first;
- a round goes into one long video only, so two never share questions.
  Discarding a long video frees its rounds.

"Rising" was added because random ordering spreads shorts across five
difficulties, so six at one level take a while to accumulate.

**The board** is a 1920×1080 template page, like the shorts' board:

- rows 1-10 on the left, each question appearing in its row as it's read;
- a panel on the right with the question, the clock, and the answer;
- a cover and a scores card;
- in the answers section, the question fades out and the answer fades in
  as it's given, in both the row and the panel;
- each round's rows leave when it ends.

Around it:

- a rendered thumbnail and YouTube chapters for each round and answer
  section;
- a music bed that moves through the channel's tracks with crossfades,
  because one track looped for twenty minutes wore thin. It works in
  float32, since a long video's soundtrack is tens of millions of
  samples.
- The joining lines, played next to the recut shorts, measured within
  about 1.5 dB of them.

**Publishing:**

- Long videos live under `longform/`, publish in their own slots
  (`publishing.long_slots`, `long_weekdays`), go to YouTube only with
  their thumbnail, and don't count against the shorts buffer.
- They always wait for a look.
- A channel can make one automatically every N days
  (`quiz.longform_every_days`, off by default), alternating the variants
  if asked.
- A long-quiz job runs through the same job queue, so it gets progress,
  retries and the Activity page.

## Tried and rejected

- **Voicing whole new rounds for long videos.** That costs about 7× the
  characters, and the owner's voice allowance is the binding limit.
- **One looped music track.** It wore thin over twenty minutes.
- **Both variants from the same rounds.** YouTube's inauthentic-content
  rules target near-identical videos.
