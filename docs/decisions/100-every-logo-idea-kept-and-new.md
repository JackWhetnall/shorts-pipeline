# 100 — Every logo idea kept, and each batch new

**Status:** active.

## What happened

The owner generated a second batch of logo ideas for Why, Though?.
- The page went on showing the first batch, and on reload showed
  nothing. The app was probably restarting onto new code at that moment.
- Making the second batch had deleted the first. The generator cleared
  the folder each time, as it always had: "only the most recent batch is
  kept".
- One of the new ideas was almost identical to one from the first batch.

The owner asked for every idea to be kept, and for "Generate" to give
genuinely new designs each time.

## Why the second batch repeated the first

Decision 099 picked five looks at random from twelve, so two batches
shared some looks. Every idea also drew the brief's most obvious
subject: a question mark and a globe. Same look plus same subject gave
near-identical pictures.

## Decision

- **Nothing is deleted.** Every idea stays in `logo/candidates/`, and
  the page shows them all, newest first. A new batch is added in front
  of the earlier ones.
- **`ideas.json` records each idea:** the file, what it shows, its look,
  and the brief.
- **New subjects each batch.** Before each batch, one low-effort Claude
  call (`concepts`, about a cent) sketches five ideas for what the mark
  shows. It is told every idea already shown and must not repeat or
  closely vary them. Each idea names its own colours, varied across the
  batch, because the image model drifts to orange backgrounds when left
  to choose.
  - If the call fails, the batch is drawn from the brief alone, and a
    warning is logged.
- **Looks the channel has had least come first** (`directions(used=)`).
  No look repeats until all twelve have been used.

## Checked live

A live batch showed five different subjects, each in its own look:
- a lightbulb shaped like a question mark;
- an eye with a galaxy in the iris;
- a pixel-art magnifying glass over a planet;
- an engraved feather curled into a question mark;
- a drop of water forming one.

This was before the colour rule was added, and four of the five had warm
orange backgrounds.

## Not recovered

The batches deleted before this change (a5893ccb, 30bb50b0) can't be
recovered.
