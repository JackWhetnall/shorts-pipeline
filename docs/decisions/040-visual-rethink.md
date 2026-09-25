# 040 — A visual director, designed templates and illustrations, replacing free-form scenes

**Status:** active. Supersedes the free-form scene *planner* of
[035](035-scenes-in-the-pipeline.md). Free-form diagrams remain, for
geometry and plots only.

## What happened

The first video made with scenes throughout (Curiosity Leak, "Why yawns
are contagious", $0.42) was, in the owner's words, a car crash:

- **The pictures made no sense.** A lavender polygon stood for "the
  brain", and there were empty frames.
- **Labels were missing.** Three were white text on white pills.
- **The frames were sparse.** Small things were stranded in corners.
- **The sound was intrusive.** Every element popped as it arrived.
- **It still passed every check.**

The diagnosis: an AI placing primitives on an empty canvas cannot make
polished motion graphics, and every fix since 035 had patched symptoms.
It was also the wrong medium for this video. Yawning is about people and
dogs, and footage of a dog yawning beats any diagram. The channel draft
had set the channel to "always animated" because the subject was
science.

## What was decided

**A director chooses each segment's medium** (`pipeline/director.py`).
One Sonnet call reads the script and picks, per segment:

- footage, for anything a camera can film;
- an illustration, for what can't be filmed;
- a template, for structure;
- a diagram, for geometry and plots only.

For each it gives a brief, a reason, and a 0-10 score for how much the
segment needs something other than footage. The slider keeps the
meaning the owner defined in 037: it is the bar that score must clear.
0 is always footage; 100 is never footage. The director is never told
the slider.

**Templates, not free drawing** (`pipeline/templates/`). There are
twelve designed motion-graphics templates, in HTML/CSS:

- big number, versus, list, steps, timeline, bars;
- myth/fact, definition, quote, equation, one-in-N, scale.

A small engine sets every element's state for any time `t`, so frames
are deterministic, as with scenes. Text is shrunk to fit its box before
the first frame, so nothing overflows. Each channel's art direction
becomes CSS variables, plus a finish per look:

- Clean flat: sticker cards;
- Chalkboard: chalk wobble;
- Neon: glow;
- Parchment: paper grain.

Text on filled shapes is chosen by contrast from the ink, the
background, white and near-black. The model only writes a template's
words, numbers and icon names and times its beats to spoken words: one
small call, about a cent, with validation and one repair. It never lays
anything out, which is why every frame is full, balanced and legible.

**Illustrations** (`pipeline/illustrate.py`) are one gpt-image-1
portrait image (about 6 cents) in the channel's style, with no text in
it and a calm bottom third for the captions, slowly pushed in.

**Sound is quieter and sparser.** Effects come only on templates'
declared big moments and on diagram highlights: at most eight a video,
at least 1.2 seconds apart, at a third of the old level, with a softer
pop.

**Checks that judge quality:**

- Free-form label colours that would be invisible are corrected.
- Near-blank frames are measured (brightness spread) and block the
  video, with no AI needed.
- The picture check is told to block frames that are sparse, unfinished,
  illegible or unrelated to the words.

**Defaults.**

- The channel draft sets the bar from the subject: people and everyday
  life 20-35, ideas 40-60, maths 80+, and never 100 for a filmable
  subject.
- Footage cuts at most every 3.5 seconds.
- Each dashboard shows every template in the channel's look.

## Tried and rejected

- **Keep patching free-form scenes:** the ceiling is too low.
- **Bundling KaTeX:** its own typeface would clash with each channel's
  fonts; a small typesetter covers the subset.
- **AI video generation:** expensive per second, inconsistent between
  shots, and unreliable with facts.
