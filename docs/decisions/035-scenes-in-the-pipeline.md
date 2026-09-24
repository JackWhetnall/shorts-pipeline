# 035 — Animated scenes in the pipeline, per channel

**Status:** active. Builds on [034](034-animated-scenes-renderer.md)
(the renderer).

## What happened

The owner liked the first hand-written scenes and asked for the rest:

- the art style should be per channel and editable, with a preview;
- the draft should set it automatically from the pitch;
- a slider should set how much of each video is animated, because some
  channels only want scenes for explanations and others (maths) want
  them throughout.

## What was decided

**A channel's look is a preset plus its own changes.** `scenes.art` on
the channel holds `{"preset": ..., ...overrides}`. There are four
presets: Clean flat, Chalkboard, Neon and Parchment. They differ in more
than colour:

- chalk and ink get a hand-drawn wobble;
- neon gets a glow in each element's own colour;
- paper and board get grain;
- there are grid, ruled and dot patterns.

The settings form sends every field, so only the values that differ from
the preset are stored. A later improvement to a preset still reaches
every channel built on it. Every value is validated (colours, installed
fonts, ranges); a bad one falls back to the preset's.

**The share is a number from 0 to 100** (`scenes.share`). 0 is stock
only, which is every existing channel's default, so nothing changes for
Minute Pastor or Wren's. At 100, every segment is a scene. In between,
the planner picks the segments where a picture explains best.

**The pitch sets both.** The channel draft now chooses a preset, a
palette, fonts, a prop style and a share, and gives its reason. This
replaced the old "visual approach" field, which only noted that diagrams
weren't built yet. The draft page and each channel's dashboard show the
same form: preview still, slider, preset, colours, fonts, pattern, line
weight and prop style. The preview re-renders about 2 seconds after a
change and is cached by content.

**The stage** (`pipeline/scenes/stage.py`) runs between the voiceover
and assembly, because scenes are timed to the real narration:

1. **Plan:** one cheap call decides which stretches of segments become
   scenes, grouping consecutive segments that build on one picture.
2. **Write:** one call per scene. Every action is anchored to the index
   of the spoken word it starts on, and converted to seconds from the
   voiceover's real timings.
3. **Check:** the structure is validated first. Then the layout is
   measured in the browser every half second: text off screen, anything
   in the captions' space, labels overlapping, and text straddling an
   area's edge.
4. **Repair:** once, with the problems given back as notes.
5. **Props:** drawn if new (at most four per video) and kept in
   `channels/<key>/props/<style>/`.
6. **Render:** held on the last frame for the crossfade.

A scene that still can't be made falls back to stock footage for its
segments. `scenes_fell_back` and `scene_notes` go on the video's report,
following the codebase rule (see CLAUDE.md) that anything degraded is
flagged, never silent.

**Assembly** gives each scene one shot spanning its segments, played
from its start rather than from a random window. Footage matching only
sees the segments left to stock. The frame check on the finished video
judges each sampled frame against the words spoken at that moment, not
the first segment of a long scene.

## What was tried and rejected

- **Structured outputs for the scene call.** The API allows at most 24
  optional fields per schema, and the scene language has about 55. So
  the scene call asks for plain JSON (`call_json(schema=None)`), and the
  validator plus the repair round are what keep it honest. The short
  planning call keeps a strict schema.
- **A separate per-scene picture check.** The frame check already looks
  at the finished video, scenes included, against the words. A second
  vision call per scene would roughly double the cost of checking for
  little gain.
- **Decorative script fonts.** The draft chose Segoe Script for a maths
  channel's headings. The heading font also sets every label, number and
  equation, so script fonts were removed from the list.

## What the Pythagoras demo taught

The first full run (a maths channel pitched from scratch, then
"Pythagoras' theorem") found four problems, each now fixed and pinned by
a test:

- **The plan covered one segment of four** despite a 100% share.
  Ranges that overlap are now trimmed instead of dropped, and at 100%
  any segment left out gets a scene built from its own shot brief.
- **A reference triangle showed as a solid block from the first frame.**
  It had no entry action. Elements can now be `hidden` (for anchoring
  only), and anything visible without an entry is sent back for repair.
- **Side anchors on rectangles landed in the middle.** Rectangles now
  have corners like any polygon.
- **A scene labelled the wall 6 (it was 8) and showed the answer early.**
  It had been written seeing only its own lines. Every scene is now
  written with the whole narration, under a rule that a number labels
  what the narration attaches it to and appears only once it has been
  said or worked out. The frame check caught this one and the gate held
  the video, which is the reliability design working as intended.

## Costs, measured

These are from the demo, with four scenes over 41 seconds:

- The plan call is $0.02.
- Writing a scene is $0.03-0.06, mostly the model's reasoning about
  geometry and timing. Every scene in the demo needed its one repair, at
  $0.015-0.04 each.
- A new prop is $0.042, once per channel per object; the demo drew two
  (a ladder and a brick wall).
- In total, scene calls came to about $0.25-0.30 for a fully animated
  video, on top of the usual script, voice and checks. At an
  "explanations" share it's about a third of that.
- Rendering is free (local Chrome) and takes about 2 seconds per second
  of scene, well inside the time the rest of the render already takes.

The voice (ElevenLabs quota) is still the scarce resource, not this. A
fully animated channel also skips footage matching and fetching, which
cost the demo's first, mostly-stock run $0.13.
