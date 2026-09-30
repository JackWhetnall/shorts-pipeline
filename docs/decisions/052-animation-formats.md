# 052 — Animation formats: a grammar per channel, not a skin per channel

**Status:** active. Extends [051](051-generated-animation.md): its pipeline
becomes the *story* format, one of four.

## What happened

The owner looked at 051's ten looks and put their finger on the
problem. The looks are all the same video, a story in which characters act
out what is said. Changing the paint doesn't change that, and "have
characters act something out" is generic for most subjects. They gave
three examples of what a channel might actually want:

- **A fun science channel:** cute felt objects moving around a white
  tabletop, with diagrams and labels.
- **A history channel:** historical figures as paper-figure animation.
- **A CGP Grey-style channel:** a simple narrator avatar talking to you,
  with the concepts explained in the same art style.

Two of those need exact words and diagrams on screen, which no image or
video model can be trusted with. All three have a stage that persists (a
table, a theatre, a canvas) rather than a sequence of shots.

## What was decided

**A format is separate from a look.**
- A look is a medium: felt, gouache, engraving.
- A format is a grammar: what persists through the video, what is drawn
  once for the channel, how the storyboard thinks, and what renders it.

A channel chooses both, and any look works with any format. Each format
names the looks that suit it best, and settings offers those first. There
are four formats (`pipeline/animation/formats/*.json`):

| Format | Stage | Drawn once | Rendered by |
|---|---|---|---|
| Tabletop | one surface, seen from above | objects (from above), the surface | the compositor |
| Narrated canvas | one large canvas the camera travels across | icons (face on), the narrator in four poses | the compositor |
| Cinematic story | a world, in shots | style frames, cast sheets | the video model (051) |
| Paper theatre | a toy theatre, side-on | as story | the video model, with a theatre grammar and captions |

**The compositor** (`pipeline/animation/compositor/`) is a
motion-design engine. It isn't the sprite board of 034-036, which
failed for three reasons:
- a model placed primitives on an empty canvas by coordinates;
- the art was emoji;
- the motion was generic.

Here:
- **Pictures** are the channel's own kit: GPT Image 2.5 cut-outs
  (transparent) in its look, drawn once per object and reused by name,
  so the channel's felt brain is the same felt brain in every video.
- **Composition** comes from eleven designed layouts (hero, pair, row,
  grid, steps, cycle, group, travel, scale, statement, presenter) that
  place and size everything by rule. They fit the vertical frame, stay
  above the captions and can't overlap. The storyboard only chooses a
  layout and fills it. This is decision 040's lesson (templates, not free
  drawing) applied to objects.
- **Motion** has real motion design:
  - objects set down from above with a lift and a landing squash, or
    popped on with overshoot;
  - carried between beats with a hop, and slid off when finished;
  - drawn on the look's cadence (twos, threes) with a hand-moved boil;
  - contact shadows that grow as an object lifts;
  - a camera that pushes gently towards what the beat is about, or
    travels between areas of the canvas.
- **Words and diagrams are exact:** handwritten labels on paper tags,
  written in; hand-drawn arrows drawn on; rings, dotted paths, number
  badges, and vs / + / = between things. Every word is the storyboard's
  exact text, in the format's own face, embedded so any machine renders
  it the same.
- **Continuity is the format's.**
  - On a tabletop, an object still needed moves to its new place and one
    that isn't slides off: the table is one continuous performance, never
    a cut.
  - On a canvas, each beat has its own area and the camera travels
    there, so the picture builds up as a good explainer's does.
- **Timing is the narration's.** Each object arrives on the word that
  names it (the beat's first opens it, so the table is never empty while
  the words catch up), and labels are written once their object has
  landed.
- **The narrator** (canvas) is the channel's first cast member, or the
  format's default. It's drawn in four poses (talk, point, shrug, think),
  each with an open-mouth version edited from the closed one. All eight
  are cropped to one shared box so they stay aligned, and the mouth flaps
  on the narration's spoken words.

**The beats storyboard** (`pipeline/animation/beats.py`) writes the
explanation as beats. Each has a layout, objects with one-to-three-word
labels (only what the narration says), a title where it helps, what
joins the objects, and the word each object arrives on. It sees the
channel's existing objects and reuses them by name. `settle` makes the
beats safe:
- cuts snap to words inside the animated stretches;
- short beats merge;
- a layout that can't take its objects is changed;
- no presenter without a narrator;
- each object appears once per beat, a traveller keeping its start and
  end;
- counts and labels are bounded.

**The paper theatre** keeps 051's pipeline and adds a grammar and
captions:
- It stages the story being told: its people, places and events, as a
  play.
- Staging is side-on and layered, with jointed puppets and theatrical
  scene changes.
- Shots can carry a caption (a name, a date, a place). Captions are
  drawn as paper labels by Chrome and laid over the finished shots.

**Formats that draw their own diagrams keep templates out.** On a tabletop
or canvas channel, the visual director offers only animation (and
footage), because a motion-graphics template dropped in would break the
one continuous picture.

**Choosing:** settings shows a format picker first, each card with three
frames from a real render, what it suits and what it costs. Choosing a
format marks and lists first the looks that suit it, and switches to its
best look if the chosen one isn't among them. Three new looks came with
it: felt craft, flat minimal and paper puppets.

## Costs, measured on "why yawns are contagious" (34 seconds)

- **Tabletop, felt craft:** the storyboard $0.05, nine new felt objects
  and the surface about $0.15. Rendered locally in about three minutes,
  with stepped frames drawn once and repeated. A later video on the
  channel pays the storyboard and whatever objects are new.
- **Canvas, flat minimal:** the storyboard $0.05, twelve icons and the
  narrator's eight poses about $0.30, once.
- **Story (051) at the default video model:** about $3.
- **Paper theatre:** as story, plus captions at no cost.

The composited formats cost about a hundredth of a video model's price
per video. They're exact where they need to be, and they don't wait on
FAL_KEY.

## Things learned building it

- **An exit needs a "fully there" key.** The first tabletop render's
  objects faded from the moment they arrived. Exits keyed only the
  object's disappearance, so its opacity interpolated from its arrival
  all the way to its exit. Regression test.
- **An object that returns must be the same object.** A felt brain leaving
  and coming back two beats later overwrote its first appearance.
  Regression test.
- **The beat's first object opens it.** Arriving strictly "on the word
  that names it" left the table empty for three seconds when that word
  came late.
- **The camera stays on the table.** A push-in towards objects near the
  top showed black above the surface; the runtime now clamps the camera
  to the world.
- **Pose sets need one canvas.** Cropped separately, the narrator jumped
  as the pose changed; left uncropped, it was a tiny figure on a large
  empty canvas.
- **A travel beat's roles are positional**, so dropping a repeated
  traveller turned its destination into its start. Items now carry
  start and end.

## Tried and rejected

- **More looks.** A felt skin on the story format would still be
  characters acting in shots.
- **A video model for tabletop and canvas.** It can't be relied on for
  labels, numbers, diagrams or crisp vectors, and it costs 100 times
  more. It may come back as an optional pass for organic in-between
  motion (MiniMax H3 takes a first and a last frame), once FAL_KEY
  exists.
- **Locating objects in generated frames by vision to anchor labels.**
  Compositing from the kit gives exact positions for free.
