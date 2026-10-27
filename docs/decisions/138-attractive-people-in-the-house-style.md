# 138 — Attractive people, in the house style

**Status:** active. Adds to 137.

## What the owner said (27 Oct)

The owner pointed out that the channel's best short opens on a woman
pressing her own ribs, which reads at a glance as mildly suggestive. Sex
appeal stops people scrolling. They asked for pictures that lean that way,
with nothing explicit, and:

> make sure that it doesn't make the art style stray too far from the one
> we currently have

## Decision

**A new setting, `documentary.people_look`,** says how a channel's people
look. It's empty by default, which gives no steer, as before. It reaches:
- the outline, where each new cast member is described;
- the newsroom's briefs, through the channel text;
- the picture editor, for the poses in the directions it changes.

It never reaches the image prompt's art style, so the channel's style sheet
still sets how everything is drawn.

**For Why, Though?:**
- adults are drawn attractive within its own simple, rounded style;
- women are slim and shapely, in fitted, flattering everyday clothes,
  confident and expressive;
- men are fit and good-looking;
- where the line is about the body, poses are natural and led by the body;
- the same simple shapes, dot eyes and flat colours stay;
- nothing revealing, and nothing posed to draw the eye to the chest.

That last line is there because:
- the image model refuses or garbles sexual prompts, and each try is
  billed;
- a cartoon explainer that younger viewers see is where YouTube restricts
  suggestive images most.

**Teasers:** where a film has a fitting picture of an attractive woman, the
teaser opens on her (adds to 137).

**What it doesn't change:** cast members already in the library keep their
descriptions, which their model sheets were drawn from. That includes the
Curious Woman from the tickle film. No picture is redrawn and nothing is
voiced again. It applies to films written from now on.
