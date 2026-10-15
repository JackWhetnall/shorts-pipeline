# 106 — Teasers that tease, from the film's own pictures

**Status:** active.

## What the owner said

The teasers "miss on all fronts". They didn't hook, didn't explain the
premise, and didn't make it known that there is a video to watch. A
teaser should give an interesting part of the film, then leave the
viewer wanting more: with questions left unanswered, or by saying there
is more to learn. The owner added that these are suggestions, not tactics
for every time. The owner also asked whether the film's own pictures,
cut to vertical without cropping in awkward places, would be cheaper than
drawing new ones.

## Why they missed

The teaser prompt (decision 074) told the writer that a teaser "never
mentions the documentary, a full video, a channel… The story does the
asking", and asked for a fixed shape every time: a moment of tension,
one piece of the story, then an open question. Each teaser read like one
more scene from the film.

## Decision

**The scripts:**
- Each teaser must do four things, each in its own way:
  1. hook in the first line;
  2. make the premise plain;
  3. pay off one real piece of the film;
  4. leave the viewer wanting the rest, saying once, in the narration's
     own voice, that the full video is on this channel.
- Ways to do the last are listed as examples, not a template. Stock
  calls to action are out ("like and subscribe", "link in bio").
- Teasers must differ from each other. The first and last lines of the
  channel's recent teasers are passed in, so their shapes aren't
  repeated.
- The film's narration is the authority on facts. The angle's hook still
  said "a complete map of Mars" after the film corrected it, and the
  first live teaser repeated it. On explainer channels the teasers also
  go through the film's fact check (`teasers.checked`), as one call.
- When the full video is already out, its link goes in the teaser's
  description.

**The pictures** (`pipeline.documentary.vertical`):
- Each teaser scene names one of the film's pictures instead of
  describing a new one.
- One low-effort look at a teaser's pictures (about a cent) gives, for
  each, how far across it the part that matters runs.
- The picture is cut to the narrowest window that keeps that part, with
  a small margin:
  - a subject that fits a tall slice fills the frame;
  - a wider one is shown as large as it can be across the middle, over a
    blurred, dimmed copy of the picture.
  Nothing that matters is cut. A failed look keeps every picture whole.
- Drawing the first film's teaser pictures again cost $0.17 in pictures
  and checks, plus style and character sheets the day before, and they
  waited on an OpenAI batch. Now the pictures cost about a cent and
  nothing waits on OpenAI.
- Teasers written before this change (with `direction` instead of
  `picture`) are still drawn the old way.

## Checked live

The ocean film's two teasers, written twice:
- **Before the last fixes:** neither mentioned the full video, and one
  opened with "a complete map of Mars".
- **After:** both hook, pay off, and end by pointing to the full video in
  their own words. The crops keep each subject whole.
