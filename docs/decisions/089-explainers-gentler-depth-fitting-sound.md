# 089 — Explainers, gentler depth, sound that fits the picture

**Status:** active. Builds on 086, 087 and 088.

## What happened

On 12 October the owner watched the remade plague film (088). The
pictures and the voice were better. Three things were not:

> "the depth thing is not good - it really churns the pictures up ...
> especially with faces ... panning up close is horrible"

> "the sound affects are jarring - is there a fire sound effect or
> something? it is loud and harsh and goes on through many pictured
> scenes, inconsistent with what is on show"

> "its a story about a baker. but there is no hook, no question
> answered ... it doesnt ask or answer any questions that a viewer might
> have ... maybe i need to see a more personally captivating channel
> style ... a more interesting, explanatory and informative video on a
> given subject, let's try with a more cartoon style"

## Decisions

**Depth only where it can't warp** (`depth.suits`).
- A push, pull or hold keeps its depth; the owner found zooms fine.
- A pan gets depth only across the whole of a wide picture. A crop is a
  close look, and a close-up pans flat.
- The sideways spread was 2.5 times nearness, which sent the far
  background the opposite way to the camera. It's now 0.6
  (`PAN_SPREAD`), so everything moves the same way and near things a
  little more.

**Sound under the scenes that show it.**
- A chapter's bed now plays only under scenes whose direction names its
  place (`ambience.FITS`: fire under a hearth, oven or forge; a street's
  sound under streets), never under cards.
- On the plague film, the fire would have run under 9 scenes, not 24,
  and 39 of 72 scenes would have had no bed.
- Beds sit 24 dB under the voice (was 15), and a crackle louder than
  three times a bed's average level is turned down (`CREST`).

**Explainers** (`documentary.kind`, `pipeline/documentary/kinds.py`).
- A documentary channel makes either a story (the default) or an
  explainer.
- An explainer's writers are told the film answers a question a curious
  viewer really has:
  - each chapter answers the next question they'd ask, and ends on the
    one after;
  - every idea is made concrete with an analogy, a human-scale number
    or a real attempt;
  - the wrong answer people assume is said before the right one;
  - pictures are cartoon metaphors and cutaways;
  - cards are allowed up to about one scene in eight;
  - background sound is off unless a place is loud.
- The pitch's angles are questions people search for, and the critic
  scores momentum by questions answered, not by a character's want.
- The only story text that moved into `kinds.py` is the part that
  differs. Story prompts are byte-for-byte what they were, and a test
  checks this.

**A new channel, Why, Though?** (`why_though`).
- Each film answers a curious question about the world: the planet, the
  body, everyday things.
- It's a 9-minute explainer in a bright flat 2D cartoon look, with
  pictures every 7 seconds.
- It uses a different narrator from both other documentary channels
  (ElevenLabs "Alice", an educator's voice), on v4.
- No drifting air, no dialogue, no paintings.
- The first film is "Why a Soviet Drill Hit Rubber Rock at 12
  Kilometres". The highest-scored angle wasn't chosen because its first
  line was wrong (it said nobody had dug six kilometres down).
- A few lines of the script were corrected by hand before voicing:
  - mantle rock is mostly solid, not molten;
  - glass doesn't flow;
  - drilling ran 22 years, not 24.

**A small fix:** a contraction ("can't") no longer counts as a word the
title has to name.
