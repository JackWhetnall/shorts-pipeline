# 120 — Where the voice goes, and what to change when it won't last

**Status:** active. Builds on the voice verdict of decision 080 and the
film-as-one-output costing of [112](112-a-film-costs-as-one-output.md).

## What the owner said

With the ElevenLabs allowance running low, it was hard to tell:
- how much each channel uses, and what a video takes on average;
- whether a film's teasers count towards it;
- how changing one channel's schedule would affect the total;
- which videos are already made and which will spend what's left.

Money had one small bar and a verdict. They asked for:
- a wide bar of blocks, coloured by channel, sortable by release date or
  by channel;
- suggestions for getting under the limit in the most sensible way.

## Decision

**A Voice page** (`/money/voice`, `core/voice_budget.py`, linked from
Money's voice allowance) for the billing month: since the last reset,
taken as a month before the next one.

**Spent blocks**, one per output, from the cost log:
- A film and all its teasers are one block, with the teasers' share in
  its hover.
- A short is matched to its video by its exact voice cost, since a job's
  own record is kept only a week. Its block then has a title and its
  state: out, queued, in review, discarded, or no video (a failed run).
- Stages run by hand from 11 to 13 Oct recorded no channel, and are shown
  as such.
- Credits per character are this month's own: what ElevenLabs reports
  used, over the characters logged. The blocks then add up to its
  figure, not a little over.

**Blocks still to come** before the reset, marked as estimates:
- **Shorts:** the slots left plus the buffer the generator keeps, less
  the videos already made. A quiz channel's long lane keeps one waiting.
- **Films:** those being made, at their exact narration once scripted;
  teasers still to make; and the films the autopilot will start, one for
  each that goes out plus any room in its bank. They're titled from the
  plan.
- A video takes what that channel's own outputs have taken: a film with
  its teasers, a short, a long one.

**The bar:**
- one block per output, sized by credits;
- spent first, then still to come, sorted within each by release date or
  by channel;
- a line at the allowance;
- solid for spent, hatched at 45° for to come, hatched at 135° for
  discarded or no video;
- channel colours from the validated categorical palette, fixed by
  channel order;
- a hover with title, credits and state;
- a table by channel and a table of every video.

**Suggestions**, when it won't fit:
- Each says what it saves before the reset, allowing for videos made
  ahead, and roughly what it costs in views: the channel's recent
  average a video.
- The changes that cost no views come first, then fewest views per
  credit saved. Those that together close the gap are marked.
- Each applies in one click, as that one setting (`voice_budget.apply`
  accepts only schedule and bank fields).
- When even all of them fall short, upgrading the ElevenLabs plan is
  marked too, with its price.

## Fixed on the way

- **Slot times:** `publish_queue.upcoming_slots` replaced the hour on a
  copy of today's time, so every slot after the clocks went back read an
  hour early. Publishing itself was right; the queue's times weren't.
- **The film bank:** `auto_films._in_hand` counted a film waiting for a
  look as banked even once discarded. Velcro, mirrors and the pen cap were
  holding three of Why, Though?'s eight places.
