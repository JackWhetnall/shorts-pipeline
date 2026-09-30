# 053 — A channel's animated style is answers to questions, not a preset

**Status:** active. Replaces 052's four formats and thirteen looks (both
removed); keeps 052's compositor and 051's generated pipeline as the two
engines a style compiles to.

## What happened

052 split *format* (what kind of video) from *look* (what it's made of),
and the owner tried it. Two problems came back.

**It only offered what had been asked for.** The formats were the three
examples given plus the original story. The owner wanted cute, stubby,
round paper people for the history channel (not the looks' proper human
proportions), minimalist 3D meeples for a logic-puzzle and game-theory
channel, and in general "a vast expanse of ideas", not one new option per
request.

**Any format took any look.** Paper theatre plus stop-motion clay was
offered, and it's hard to say what it would even look like. Nothing
stopped a combination that makes no sense, and nothing showed what a
combination would look like before it was chosen.

The ask was for a guided builder:
- each setting an easy question;
- each answer narrowing the next question's options to the ones that fit;
- a preview of the style exactly as chosen;
- new styles described without touching backend code.

## What was decided

**A style is the answers to eight questions, asked in order**
(`pipeline/animation/style/grammar.yaml`):
1. How does the channel explain? Objects, diagrams, acted out, or cinematic scenes.
2. Where does it happen? Tabletop, game board, pinboard, diorama, canvas,
   whiteboard, chalkboard, notebook, blueprint, parchment, toy theatre,
   miniature set, animated film, storybook, open world, plain black or
   plain white.
3. What is it made of? 30 materials, from felt, clay, wood and knitted yarn
   to engraving, neon, pixel art, cut-out photographs and crisp maths
   graphics, or the user's own words.
4. How are people shown? Stubby, game tokens, cartoon, true to life, stick
   figures, blobs, silhouettes, pictograms, none, or the user's own words.
5. Is there a host?
6. What should it feel like?
7. How does it move?
8. How do labels and names appear?

**Conditions keep every combination sensible.** Each option says when it
makes sense: `when`, a condition on earlier answers, and `not`. A
condition may only look at earlier questions, so choosing in order always
works, and the tests check that every option is reachable. The builder
offers only options that fit. An earlier change that rules out a later
answer replaces it with that question's default for the new context, and
says so. Paper theatre plus clay can't be chosen: clay isn't offered on a
toy-theatre stage, only felt, paper and custom are.

**Options carry their meaning.** An option's `sets` holds what it means
for the engines and the drawing:
- the engine, the stage's continuity and entrance, and the kit's view;
- the storyboard's guide;
- the image prompt, light, palette and grade;
- label style, cadence and motion.

Later answers override earlier ones. A few text fields add up instead of
overriding (image, guide, avoid, people, light, kit view). A material
describes the surface for each stage it stands on (`boards`), so "felt on
a tabletop" is a linen table and "felt on a pinboard" is a felt board.
`style.compile` turns the answers into the `fmt` and `look` both engines
already ran on. Adding an idea means adding an option with its
conditions; nothing else changes.

**Starting points and descriptions.**
- 34 named styles (`starting_points.yaml`) each fill every answer, and
  each has an example picture drawn by the real renderer on its own
  subject (`style/examples/`, `tools/animate.py gallery`).
- "Describe it in your own words" makes one model call. It returns
  answers limited to the grammar's options (an enum per question), style
  notes for anything they can't say, and why. The answers go through the
  same conditions as anyone's, so a description can only land on a valid
  style.

**The preview is the style itself, not a picture of it.**
- For a composited style, "See this style" writes one line of narration
  and the beat that shows it, draws whatever kit that needs (kept for real
  videos), and films a frame through the real compositor: about 40
  seconds and 5 to 15 cents.
- For a generated style it draws the first frame: 2 to 3 cents.
- "Make it move" films a few seconds locally for free (composited), or
  animates the frame with the video model once `FAL_KEY` is set.
- Previews are cached by what they were made from.
- Each material shows its four example pictures (the same four subjects
  for every material), and the builder shows the nearest starting point's
  example until a preview is made.

**The browser and the server evaluate the same conditions.** The builder
(`app.js`, `styleNormalise`) reads the grammar from the page. The server
normalises whatever it's sent before saving. A test runs 600 random
answer sets, most of them invalid, through both and requires identical
results.

## Rejected

- **More formats and looks.** The problem was combinations, not the
  count; every new pair would need rules nobody wrote down.
- **Letting the model design the style freely.** Nothing it says could
  be relied on to render; the description path constrains it to the
  grammar instead.
- **A compatibility matrix per pair.** It's quadratic, and silent about
  why. Conditions on options state the reason where the option is
  defined.

## Consequences

- Old `format`/`look`/`cadence` settings are ignored on load and dropped
  on the next save. No channel had them saved.
- Kit, style frames and cast sheets are filed by the style's identity:
  the answers that decide drawing, plus the notes and palette. Changing
  motion or labels doesn't redraw anything.
- Widescreen and minimal diagram styles followed in
  [054](054-minimal-diagrams-and-widescreen.md).
