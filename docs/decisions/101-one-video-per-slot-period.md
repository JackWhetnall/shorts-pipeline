# 101 — One video per slot, even when the time moves

**Status:** active.

## What happened

On 14 October Why, Though? published two films 10 minutes apart. The
first went at 16:26, in the 16:00 slot. The owner then moved the
channel's long-video time to 16:30. The second film was approved at
16:35 and went out at 16:36: 16:30 was later than the last slot used
(16:00), so it counted as a new, empty slot.

## Decision

A slot counts as filled if a video went out at or after it, or since
the slot before it (`publish_queue._filled`). `publish_due` and the
schedule shown on the page both use this check. Moving the time on a
day a video has gone out now moves the next video to the next slot day.

## Also on 14 October (no code can fix these)

**Why, Though? thumbnails** are refused with a 403. Custom thumbnails
are an "intermediate" feature, unlocked only by phone verification. A
phone number verifies at most two channels a year, and the owner's
number had already been used twice. YouTube doesn't let a number be
moved off a channel. The channel needs another number, or a landline by
voice call (TASKS A1).

**Pub Quiz Buzz Shorts** show YouTube's own frame in the Shorts shelf
and subscription feed. On published Shorts that frame was at question
4 or 7, with the earlier answers showing.
- `thumbnails.set` succeeds, but it sets the ordinary thumbnail, not the
  tall Shorts picture.
- The Data API has no way to set that picture.
- The only routes are the owner's own:
  - pick a frame in the YouTube app;
  - upload a Shorts thumbnail in Studio on desktop, where YouTube has
    made that available (rolling out since July 2026).
- The channel is frozen, so changing the video itself (for example,
  hiding answers already given) would need the owner's agreement.
