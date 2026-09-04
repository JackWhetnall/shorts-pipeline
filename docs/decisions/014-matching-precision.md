# 014 — Matching on what a clip is, not what is in it

**Status:** active. Builds on [012](012-shot-briefs.md).

## The remaining problem

Shot briefs fixed the abstraction gap: both sides of the comparison are
now literal. What they didn't fix is that one side is still a paragraph.

A description says everything visible:

> Dark wooden prayer beads coiled on a polished wooden table in the
> foreground, with a closed leather-bound Bible sitting at the edge of
> frame and a softly blurred bedroom setting behind.

Matched as one blob of text, the bedroom and the Bible are evidence
equal to the beads. So a brief asking for a Bible ranks a clip where a
Bible is a prop at the edge of frame, and a brief asking for a bedroom
ranks a clip that is really about prayer beads.

## Three changes

**A `subject` column, weighted eight times the prose.** What the clip is
*about*, in a few words. `setting` gets three times. FTS5's `bm25()`
takes per-column weights, so this is a ranking change rather than a new
mechanism — a clip that IS prayer beads outranks one that merely
contains some.

The attributes are distilled from the descriptions already stored, in
batches of 25, by a text call. **Not** by looking at the clips again: a
vision pass over 264 videos would cost far more, and the description is
what the matcher reads anyway — so if a description is wrong, the fix is
re-describing, not re-enriching. Measured cost for the whole library:
about 22 cents. `manage_library.py enrich` states that figure and asks
before spending it.

`motion`, `palette`, `time_of_day` and `has_people` come along in the
same call and cost nothing extra.

**Shot-to-shot diversity.** Consecutive shots that look alike read as a
mistake even when the footage is genuinely different — two different
ocean clips back to back is still one long ocean shot. Selection now
skips a candidate that shares the previous shot's subject or is within 14
bits of it perceptually, falling back to score order when every candidate
is similar, so this can never cause a shortfall. It uses the frame hashes
already stored for duplicate detection: no new data, no extra work.

The threshold is deliberately looser than the 6-bit duplicate bar. Those
clips are the same file; these merely look the same.

**Rejections feed back.** Discarding a video for its footage now
increments `reject_count` on every clip it used, and that adds a small
penalty to the clip's rank. This is the loop the discard reasons were
added to close: your repeated judgement, applied automatically.

Sized as a nudge, not a ban — one bad pairing doesn't make a clip bad,
and a strong match survives a rejection. Only footage rejections count,
because discarding a video for a weak script says nothing about its
clips, and only on the transition, so toggling discard twice doesn't
count twice.

## What this does not do

No embeddings, still. The reasoning from
[007](007-shortlist-before-matching.md) holds: the lexical stage only has
to get plausible candidates into a set of fifty that the model then reads
properly. Making that stage sharper is worth more than replacing it, and
weighted fields are sharper for a fraction of the complexity.

## The threshold, again

Still 5. Three things have now changed underneath it — briefs, the
rubric, and this — and the discard-reason data that would justify raising
it only started being collected with the last of them. Raise it when
"footage didn't fit" stops being the top discard reason, not before.
