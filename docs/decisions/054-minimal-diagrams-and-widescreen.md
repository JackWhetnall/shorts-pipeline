# 054 — Minimal diagram styles, and one style for both shorts and widescreen

**Status:** active. Extends [053](053-style-grammar.md) and the compositor
of [052](052-animation-formats.md).

## What happened

With the style builder in place, the owner raised two gaps.

**Minimalism wasn't possible.** Every style was an art style. They pointed
at [@Quant_Prof](https://www.youtube.com/@Quant_Prof/shorts), a channel of
quant interview puzzles that looks nothing like any of the options:
- a pure black background with a small series header;
- one precise mathematical object at a time: a bracketed matrix, formulas
  typeset in LaTeX and written in stroke by stroke, a bar chart on arrowed
  axes whose bars change height as the explanation moves on, a complete
  graph with coloured edges, a flat icon of a balance scale;
- things fade out as the next idea is written in over them;
- white upper-case captions with the spoken word boxed in red.

None of that is a drawn picture: it's typesetting and geometry. Asking an
image model for it would be expensive and wrong (no model draws a
correct number line).

**The frame was always vertical.** The owner wants the option of the same
explanation as a short and as a longer, more in-depth widescreen video, so
a style can't be tied to 9:16.

## What was decided

**The compositor draws diagrams itself** (`compositor/diagrams.py`), at
no image cost:
- **formula:** lines of LaTeX, typeset in Computer Modern by matplotlib's
  mathtext (`compositor/mathtext.py`; no TeX install, works offline; a
  line it can't parse becomes plain words rather than failing the video),
  written in left to right;
- **bullets:** points with inline maths;
- **matrix:** entries in brackets;
- **chart:** bars on arrowed axes, labels beyond each bar's end;
- **number_line:** ticks, points, jump arcs and a shaded interval;
- **plot:** axes, curves y = f(x), a shaded area, marked points. The
  expression is parsed into an allow-listed syntax tree
  (`compositor/expr.py`) and never executed, so the storyboard's text
  can't run code;
- **graph:** nodes and edges in a circle, row, column or tree, directed or
  not; word nodes are boxed.

A beat with a diagram uses the `diagram` layout: the diagram fills its box,
and up to two kit pictures sit above it (vertical) or beside it (wide).

**A continued diagram builds rather than cuts.** Every drawn primitive has
an identity ("the bar labelled X₁"). When the next beat keeps the same
diagram id:
- what's unchanged stays on screen;
- bars move to their new heights and points slide, with their labels
  riding along;
- only what's new is drawn;
- what's gone fades.

A continued chart, number line or plot keeps one scale across its beats
(`script._harmonise`), so its axes never jump. This is the Manim way of
explaining: a derivation built line by line, a chart that changes as the
argument does.

**Diagrams take the style's ink.**
- On plain black: crisp lines and Manim-like colours, with every word in
  Computer Modern when words are "typeset".
- On a whiteboard or chalkboard: the marker's wobble or the chalk filter,
  with the maths itself written in the style's handwriting face
  (matplotlib's custom fontset, falling back to Computer Modern for
  symbols).
- The data colours are the palette's colours that read against the
  background, in the palette's own order.

**The grammar gained minimal options:**
- stages: plain black and plain white, with the `fade` continuity and
  entrance;
- materials: crisp maths graphics, monoline icons and cut-out photographs;
- people: pictograms;
- mood: minimal and spare;
- motion: written and drawn precisely;
- words: typeset like a maths paper.

The styles that draw diagrams are every "draws it out" style and anything
on a plain background. Four new starting points use them: minimal maths
on black (after Quant_Prof), line icons on white, photos on black, and
minimal 3D in white space. The storyboard is only offered diagrams where
the style draws them. It sees one compact element shape: a role plus text,
ref, to, a, b and on_word. The first version had a nested object type per
diagram part, and the API refused to compile it ("compiled grammar too
large").

**The frame is per render, not per style** (`pipeline/animation/frame.py`).
- The vertical short is 1080x1920 and the widescreen video 1920x1080.
  Each frame fixes its size, its title line, the content box clear of the
  captions, a puppet's floor, the generated picture size, the video model's
  aspect ratio, and the composition rules in prompts.
- Every layout is arranged in the frame's content box. The vertical
  geometry is unchanged, and a test pins it.
- In wide:
  - steps run left to right;
  - grids reflow three across;
  - a statement sits beside its picture;
  - the host stands lower left;
  - scenes widen.
- The kit is shared between frames, since cut-outs don't care. Surfaces
  and backdrops are drawn once per frame shape (a backdrop's wide copy is
  filed as `key@wide`, hidden from the storyboard).
- The generated path draws 16:9 keyframes, asks Veo for 16:9 (MiniMax
  follows the first frame), finishes at 1920x1080, and tells the
  storyboard the frame.
- `stage.make` uses `plan.frame` ("vertical" unless a plan says "wide").

The builder has a Vertical short / Widescreen switch for previews. A
widescreen preview reuses the vertical one's written moment, so it costs
only its render.

## Also fixed here

- **Speech bubbles:** they stay inside the frame and below the title, and
  their tails still point at the speaker. The gallery had bubbles off the
  right edge and over titles.
- **Tables:** they sit on a card of their own on textured surfaces, and
  their things are labelled underneath. The wood board's grid was
  illegible, with labels off the edge.
- **Host styles:** their previews now show the host.
- **Surfaces:** prompts insist the surface is completely empty. A
  widescreen whiteboard came back covered in doodles.

## Not done

- **The long-form explainer pipeline:** an in-depth widescreen script
  from the same seed, its assembly, captions and upload slots. The
  animation layer is ready for it (`plan.frame = "wide"`); nothing makes
  such a plan yet.
- **A persistent series header**, as Quant_Prof has ("UNEXPECTED Quant
  Interview Question / #1059"). The storyboard can repeat a title, and a
  repeated title now stays up rather than flickering, but there is no
  channel-level header setting.
- **Karaoke-style captions** with the spoken word boxed. Captions belong to
  assembly, not animation.
