# Spec: animated scenes in each channel's own art style

*24 Sep 2026. Supersedes the "diagrams" option in
`generated-footage.md`: same seam (the shot brief), much wider idea.*

**Status:** phase 1 built (renderer, Clean flat, two hand-written
scenes); see decision [034](../decisions/034-animated-scenes-renderer.md).
Decisions in §6 answered: Playwright yes (using the installed Chrome),
Clean flat first, explanations only. Phases 2 and 3 not started.

## 1. What we want

Picture that **shows** what's being said, not just sets a mood:

- Wren's Guide: a pentagram draws itself stroke by stroke, and as each
  pillar is named, its label lands on a point.
- A maths channel on compound interest: coins drop into a piggy bank, a
  counter ticks up, and the growth curve bends upward as the narrator
  says "and it keeps accelerating".
- Minute Pastor: a verse's key phrase set in type on parchment, one word
  lighting as it's read; a simple map of Jerusalem with Peter's route.

And four things that make it work at volume:

1. **Interesting to look at**, not flat textbook diagrams.
2. **One art style per channel**, held across every video, so a channel
   is recognisable in a scroll and doesn't look templated.
3. **Adaptable**: the same system covers maths, witchcraft, history,
   devotional, science, finance.
4. **Clean and reliable**: it renders every time, and never ships a
   broken frame.

## 2. The design in one paragraph

Each channel gets an **art direction**: palette, typefaces, line and fill
treatment, background texture, motion personality, and a prompt for how
its illustrated props look. For each segment the script writer may ask
for a **scene** instead of stock footage. A second model call writes that
scene as **structured data, never code**: which props, shapes, labels,
counters and charts appear, and exactly which spoken word each one
enters, moves or changes on. The app's own renderer (written once, and
tested) turns that data into video in the channel's style. Props are
illustrated once in the channel's style and reused, so a channel's piggy
bank is the same piggy bank in every video.

## 3. The parts

### 3.1 Art direction (per channel)

| Setting | Examples |
|---|---|
| Palette | Existing vetted palettes, extended with 2–3 scene colours |
| Typefaces | A display face and a text face (free, open-licence, bundled) |
| Line | Crisp vector, hand-inked with slight wobble, chalk, neon glow |
| Fill | Flat, soft gradient, paper/grain texture, watercolour wash |
| Background | Paper, parchment, blackboard, deep gradient, starfield, or blurred stock footage behind |
| Motion | Calm and eased, or bouncy and punchy; how fast things arrive |
| Prop style | e.g. "flat vector icons, thick dark outlines, two-tone shading" or "antique engraving, sepia ink on parchment" |

A handful of ready-made directions ship first (e.g. *Clean flat*,
*Sketchbook*, *Chalkboard*, *Neon line*, *Old parchment*). The pitch draft
picks one and adjusts it; the Look settings preview it on a sample scene.

### 3.2 The scene language

Schema-constrained JSON the model fills in. Nothing it writes is
executed, so it can't crash the renderer, only describe something the
checker then rejects.

- **Things:** `prop` (an illustrated object from the channel's prop
  library: "piggy bank", "coin", "candle", "atom"), `shape` (line,
  arrow, circle, polygon, star, bracket, simple paths), `label` (a word
  or short phrase, optionally pointing at something), `counter`
  (animated number: money, %, years), `chart` (bar, line, pie, with
  axes), `equation` (typeset maths), `map` (a simple region outline with
  points).
- **Arrangements:** row, stack, grid, ring (N things around a circle:
  the pentagram's points), along a path, at a named anchor of another
  thing.
- **Actions:** appear (fade / pop / slide), draw (stroke reveals
  itself), write (text appears as spoken), move / follow a path, grow,
  count to, fill up, repeat into a stack (coins piling up), highlight,
  connect (an arrow draws between two things), camera focus, exit.
- **Timing:** every action is anchored to a **spoken word** of the
  segment. The voiceover already gives word-level timings, so a label
  lands exactly when the word does, which is the single biggest
  difference between "animated" and "explained".

The frame's bottom third stays clear for captions, like the current
render.

### 3.3 The renderer

The scene is laid out as SVG/HTML using the channel's art direction,
animated by a small timeline engine of our own, and captured frame by
frame in a headless Chromium at exact times, then encoded with the ffmpeg
the pipeline already uses. It's deterministic: the same scene always
renders the same frames.

Why this rather than the alternatives:

- **Manim (3Blue1Brown's library):** superb for equations, but
  maths-first in look, slower, and needs a LaTeX install.
- **Remotion / React:** excellent motion graphics, but the model would be
  writing code, which is where unreliability comes from.
- **Pillow (what renders captions now):** no real anti-aliased vector
  drawing, filters or typography.
- **AI video:** can't hold a style or get a label right.

Browser rendering gives the best type, vector quality and texture
effects (paper, chalk, glow) for the least new code, and typeset maths
comes free with KaTeX.

### 3.4 Props: illustrated once, reused forever

When a scene asks for a prop the channel doesn't have, it's generated in
the channel's prop style with a transparent background (OpenAI's image
model, which the project already uses for logos and whose budget is
nearly untouched), checked, and saved to the channel's **prop library**.
From then on it's reused. That's what keeps one channel's candle the same
candle in every video, and what makes the cost fall as a channel runs.
Simple geometric things (arrows, stars, circles) are drawn as vectors,
never generated.

### 3.5 Reliability, in layers

1. **Schema**: the scene can only be made of the parts above.
2. **Layout checker** (code, free): everything inside the frame and out
   of the caption zone, no unintended overlaps, text above a minimum size,
   every action inside the segment's time.
3. **Picture check** (the existing frame check, about a cent): a few
   rendered frames against the line and the intent. "Is the label on
   the right point? Is the chart going the right way?"
4. **One repair round**: the problems go back to the model once.
5. **Fallback**: a scene that still fails is replaced by stock footage
   for that segment and flagged, the same way unscored footage is today.
   It never ships a broken frame, and never loses the video.

### 3.6 In the pipeline

- The script writer marks each segment `scene` or `footage`, guided by a
  channel setting (e.g. *explanations only* / *most segments* /
  *occasional*). The shot brief says what the scene should show.
- The scene writer runs after the voiceover (it needs the word
  timings), the renderer after that, then assembly as now. The assembler
  only sees another clip.
- The review queue shows which segments were scenes; the gate treats a
  fallback like unconfident footage.

## 4. Costs (steady state, one 60s video)

| Step | Cost |
|---|---|
| Scene writer (one call, all scene segments) | ~$0.03–0.06 |
| New props (a new channel needs ~10–20 early on, then few) | ~$0.04–0.07 each; ~$0.00–0.15 per video once the library exists |
| Picture check (already paid today) | ~$0.006 |
| Occasional repair round | ~$0.01 average |
| Rendering | free (local), ~1–2 minutes of CPU per video |
| **Total added** | **~$0.05–0.25 per video**, falling as the prop library grows |

Against today's ~$0.25 per video, that's a modest rise for a
qualitatively different product. It needs Playwright and Chromium
installed (~150–200 MB, one time).

## 5. Build phases

1. **Renderer and look** (no model): the timeline engine, the core
   things and actions, three or so art directions, and hand-written
   scenes for the pentagram and the piggy bank rendered as real clips,
   to judge the look before building on it.
2. **Scene writer, checks and prop library**: the model call, layout
   checker, picture check and repair loop, prop generation. Tried on Wren's
   and on a maths pitch: 10 videos, measuring first-time render success,
   fallback rate, cost and time.
3. **Into the pipeline**: per-segment visual kind, assembly, review,
   art direction in channel settings and in the pitch draft.

## 6. Decisions needed

1. Install Playwright and Chromium (~150–200 MB) for the renderer?
2. Which art directions to prototype first?
3. How much of a typical video should be animated: explanations only,
   most of it, or occasional accents?
