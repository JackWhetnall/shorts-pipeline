# 030 — A clip belongs to the first channel that uses it

**Status:** active.

## What happened

Reviewing the videos waiting in the queue, the same stock clip (an old
man silhouetted in a chair by a window) turned up in a Minute Pastor
video and a Wren's Guide video rendered the same afternoon. The library
is shared across channels by design (decision 008), and nothing stopped
two channels from drawing the same generic shot.

That matters beyond looking lazy. YouTube's reused-content policy is
aimed at "mass production", and the same footage on several channels run
by one person is one of the most visible signs of it. It is also the
first thing a viewer who follows both channels would notice.

## What was decided

`clips.owner` records the channel that first used a clip, set in the
same statement that records usage (`store.mark_used`) and never
overwritten afterwards. Retrieval filters clips owned by another channel
inside the FTS query, before its `LIMIT`, so they can't crowd a
channel's shortlist. Both fallback paths (degraded and shortfall) apply
the same rule to their least-recently-used candidates. Unused clips are
open to everyone. Tools and tests that name no channel see the whole
library.

Backfilled from the videos still on disk and not discarded, oldest
first: 24 clips to Minute Pastor and 15 to Wren's Guide, with the one
shared clip going to Minute Pastor, which used it first. 308 clips were
still open.

## What this costs

The two channels' subjects barely overlap, so ownership mostly bites on
generic clips (hands, candles, windows, silhouettes). When a channel's
own pool runs short of those, the existing fetch rounds add new footage.
That is free to download, costs about half a cent per clip to describe,
and grows each channel's own distinct library, which is the point.

## Not done

Discarding a video doesn't release its clips. A clip a channel rejected
for footage reasons is still that channel's, with a ranking penalty,
rather than passed to another channel as a hand-me-down.
