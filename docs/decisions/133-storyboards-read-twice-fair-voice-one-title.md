# 133 — Storyboards read twice, voice by date, one title each

**Status:** active. Refines 130 (the newsroom's roles) and 131 (voice
priority).

## What the owner said (25 Oct)

> is there an agent that checks the storyboard as a whole to make sure it
> fits together well and is self-consistent, as well as an agent that
> checks individual pictures to make sure they fit with the script at that
> point?

> please make sure that this prioritisation doesn't mean that the extra
> videos (eg the bank of 3 videos made in advance) are prioritised over
> real videos that should be published this month on other channels. i
> dont want one channel to miss a video just so Why Though gets one made 3
> weeks in advance.

They also asked for teasers and long films to be told apart in a channel's
queue, and reported two bugs: "Before the stop sign existed" listed twice on
Wed 4 Nov, and a Why, Though? film going out on a Sunday.

## The storyboard, read twice

**Before:** one picture-editor pass followed Checkpoint 2. It read the
contact sheets: 27 pictures to an image, each a few hundred pixels wide.
Six of the eight reviews found "no faults". One of those was t0029, whose
scene 3 has a Sky Watcher with a blank, featureless face. That fault is
plain at 640 pixels, but the contact sheet was too small to show it.

**Now there are two roles:**

1. **The frame checker** (`newsroom-frame-checker`, Sonnet, 2 points).
   - It reads `frames`: six pictures to a sheet at 640×360, numbered.
   - Each picture comes with the line said over it and the picture asked
     for.
   - It redraws what doesn't fit its line: at most 15 pictures, about
     $0.56.
2. **The continuity editor** (`newsroom-continuity-editor`, Sonnet,
   1 point).
   - It reads the whole board in order as one film: the same people, the
     same places, one look, no jarring jumps and no repeats.
   - It redraws at most 12 pictures (about $0.45), then approves the
     storyboard and leaves the owner a note.

The desk hands out the continuity editor only once a frame check has been
accepted since the last continuity read (`frames_checked`).

## The proof's first viewers

**Before:** three of the nine final reads sent a finished script back.
Each time it was over the film's first minutes, from what the test
audience said:
- the same point made several times around scenes 4–9;
- questions stacked one on another;
- a slow first minute.

By then the draft, edit, facts, pictures and packaging had all been done.

**Now:** the same three viewers also see the proof (`proof_audience`). That
is the pitched title and thumbnail words with the first chapter, before the
draft is written. The script editor's proof read hears what they said. The
later test audience stays, since it's the only one that sees the real
title and thumbnail.

## Pictures planned against the code's counts

Nine of nine picture plans needed a second try. The code's checks are:
- anyone placed where they don't exist;
- a setting carrying too much of the film;
- too long a run in one place.

The first brief now lists what those checks already find, so the first plan
can fix them.

## Voice by date, then by channel

Decision 131 kept back credits for every channel ahead in priority, for all
their slots before the reset. That let a Why, Though? film for a slot three
weeks out block a Pub Quiz Buzz video due this week.

**Now a video due sooner goes first, whichever channel it's for**
(`voice_quota.needs` lists each need with its release time). Priority
decides only between videos due within 12 hours of each other
(`TIE_SECONDS`). Bank-ahead films fill no slot, so they have no date and
come last.

## One title each

**Cause:** when a film's teasers were remade, the old render stayed queued
beside its replacement. That is how "Before the stop sign existed" came to
be listed at 18:30 and at 22:30.

**Now:**
- remade teasers retire the renders they replace, unless those are already
  out (`run.retire_teasers`);
- on a documentary channel, a video isn't sent if another video that's out
  or queued has the same title. It goes back to review with a note
  (`publish_queue.title_clash`). A long film and its own Short are the
  exception;
- teasers that share a title can't be approved
  (`overseer.teaser_title_clashes`).

The stale render was discarded.

## The clocks going back

**Cause:** `latest_slot` built each slot by adding hours to midnight. On the
day after the clocks went back (25 Oct), that read Saturday's 16:30 slot as
17:30. The slot looked missed, and still inside the 20-hour make-up window.
So "The Freezer Time Bomb Behind Every Airline Meal" went out at 02:05 on
Sunday.

**Now:** a slot is the wall-clock time on its day, whatever the offset. The
owner was content for that film to stay out.

## The queue's markers

Each row of a channel's publishing queue is marked Long, Teaser or Short,
with a coloured stripe:
- the accent colour for long films;
- blue for teasers.
