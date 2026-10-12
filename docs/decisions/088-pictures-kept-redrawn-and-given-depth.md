# 088 — Pictures kept, redrawn and given depth

**Status:** active. Builds on 086 and 087.

## What happened

On 12 October the owner agreed to the depth model and enabled the
ElevenLabs sound-effects permission, and wrote:

> "some pictures seemed to fail generation and there is no way to fix
> them individually. could there be an option for remaking certain ones?
> or at least the ability to reuse pictures? ... some previous pictures
> can still be used rather than paying for the whole batch again. this
> smart-regeneration should be done automatically"

Drawing the remade plague film, 2 of 72 pictures failed and the video
stage then refused to start. The storyboard did have a Redraw per
picture, but with no note it handed back the same picture: the drawer
reuses any file that already exists. Drawing a storyboard again also
deleted every picture first.

## Decisions

**Kept automatically.**
- Every picture now records what it was drawn from (`still_keys`):
  - its direction;
  - its cast and how they're described;
  - its framing and medium;
  - the look it was drawn in.
- When a storyboard is drawn again after its script changes,
  `stills.reusable` keeps each picture whose new scene asks for the same
  thing, even if it moved position. It also keeps one whose direction is
  only reworded (90% similar, with the same cast, framing and look).
- Only the rest are drawn.
- A new look keeps nothing. Cards are always made again, since they're
  free.
- Kept paintings keep their credit lines.
- The old pictures are set aside until the new storyboard is done, so a
  failure loses nothing.
- The page names the cost before you press: "Draw 12 changed (60 kept)
  · $0.40", and a "N kept" pill afterwards.

**Fixed individually.**
- A redraw clears the old file first, so it's always a new picture,
  with or without a note.
- A missing picture shows a "Draw it" button, and the storyboard offers
  "Draw the N missing · $x".
- Pictures that fail are tried once more, unchecked, before the stage
  ends.

**Depth** (`pipeline/documentary/depth.py`, `documentary.depth`, on by
default).
- Depth Anything V2 Small is run here through onnxruntime. It's
  Apache-2.0, 99 MB, kept in `cache/models/`, and was downloaded with
  the owner's agreement.
- It makes a nearness map for each shot's picture, about 1.7 seconds,
  kept beside it.
- The shot's move is drawn with parallax: near points zoom and slide
  further than far ones, at 540p. The usual finish (exposure, grade,
  grain, air, caption) then scales it up.
- `finish.camera_shot` takes the moving clip (`moving=`) in place of its
  own zoompan.
- Shots are now rendered four at a time, so depth costs about 1.7
  seconds of work per second of film.
- Without the model, or if a shot fails, the move is flat as before.

**Sound:** with the permission in place, the four beds the remake needs
(street_quiet, interior_fire, street_busy, bells) were made and cached
for every channel.
