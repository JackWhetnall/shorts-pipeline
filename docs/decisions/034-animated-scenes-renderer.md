# 034 — Animated scenes: a timeline engine in headless Chrome

**Status:** active, and so far only phase 1 of
[the spec](../specs/animated-scenes.md). The renderer and the first art
direction exist. Nothing in the pipeline calls them yet.

## What happened

Stock footage can't explain things. When a script names five pillars or
says that interest compounds, the best clip is only loosely related to
what's being said, and loosely matched footage is exactly what
YouTube's reused-content policy is aimed at. The owner wanted animated
explanations: a pentagram drawn with each point labelled, coins dropping
into a piggy bank while a counter climbs. They also didn't want flat,
boring "diagrams". It had to look good, suit many subjects, keep one
look per channel and be reliable.

## What was decided

**Scenes are data, not code.** A scene is JSON made of:

- **Elements:** shapes, labels, props, counters and charts.
- **Actions:** appear, draw, write, count, move, highlight, wiggle,
  stack and exit, each with a start time and a duration.
- **Anchors:** "70px beyond the star's third point" or "the prop's right
  side". These replace coordinates wherever a thing belongs to another
  thing, so labels land on what they name without anyone doing geometry.

A model writing data it can't get badly wrong is where the reliability
comes from. Asking a model to write animation code is where it would be
lost.

**The look is data too.** An art direction (`pipeline/scenes/styles/`)
sets the background, ink, five accents, stroke weight, fonts, shadow,
motion curves and a prompt for illustrated props. A channel keeps one
art direction, so every scene it makes looks like the same channel.

**The engine is ours:** `runtime.js`, about 400 lines of SVG. It is
pure: `__seek(t)` sets every element's state for time `t` from the
actions alone, with no clock and nothing carried over from the previous
frame. So:

- the same scene always renders the same frames;
- any single frame can be rendered on its own (for previews and the
  picture check);
- a frame is never lost to timing.

**Rendering** loads the page into the **Chrome already installed**
(Playwright with `channel="chrome"`). For each frame it calls
`__seek(i / fps)`, takes a screenshot and pipes it to the pipeline's
ffmpeg. A 10-second scene takes about 20 seconds. Playwright's own
Chromium download failed on this PC, and using the installed Chrome
means there's no second browser to keep up to date.

**Props** (a piggy bank, a coin, a candle) are drawn once per channel
by OpenAI's image model with a transparent background, at about $0.04
each. They're cleaned up and kept in the channel's library, so the
channel's piggy bank is the same piggy bank in every video. Anything
geometric is drawn as vectors and never generated.

## What was tried and rejected

- **Manim:** its look is built for maths, it's slower, and it needs LaTeX.
- **Remotion / React:** good motion graphics, but the model would be
  writing code.
- **Pillow**, which draws the captions: no anti-aliased vectors, filters
  or real typography.
- **AI video:** it can't hold a style or spell a label.

## Things learned building it

- **The image model's "transparent" background isn't clean.** There is a
  faint haze and, sometimes, a hairline frame round the canvas edge
  (alpha about 80). Under the drop shadow this showed as a ghostly box
  round the prop. `props.clean` zeroes low alpha and a 4px edge band,
  then trims and downsizes. There's a regression test.
- **A generated coin came with a "$" on it, in a £ scene.** Prop
  prompts carry a detail line ("plain face, no currency symbol"), and the
  phase-2 picture check has to look at props, not just layouts.
- **Star vertices run clockwise from the top.** Vertex 4 is upper left,
  not lower. That puts the elements where the tradition puts them (Air
  upper left, Earth lower left), and the test now pins it.

## Consequences

- There's a new dependency, `playwright` (Python only). Chrome must be
  installed. Tests that need it are marked slow and skip without it.
- Only Clean flat exists, chosen as the first art direction. More art
  directions are more JSON files, not more code.
- Scenes leave the bottom third clear, because that's where the captions
  go.
- Phase 2 (a model writes scenes from a shot brief, plus a layout check,
  a picture check, one repair round and a fallback to stock footage)
  and phase 3 (into the pipeline) are still to build.
