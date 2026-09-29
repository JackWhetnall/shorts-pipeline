# 051 — Generated animation: a look, a bible, a storyboard, and a video model

**Status:** active. Replaces still illustrations (040) on channels that
switch it on. Templates and diagrams stay for numbers, structure and
geometry. The sprite scenes of 034-036 remain only as those diagrams.

## What happened

The owner looked at the animated output and called it "far from ideal":
sprites drawn by OpenAI's image model, moved about on a plain board. They
asked for genuine generated video instead, and set these conditions:

- self-consistent, and suitable for any subject;
- configurable in style, with adjustable parameters that are easy to use;
- genuinely good: artistic style, quality, and consistency through a
  video and across videos;
- cutting-edge tools, chosen for quality rather than for being first or
  fastest;
- API cost kept as low as possible without lowering quality. Generating
  every sprite as its own image doesn't scale.

## The landscape, September 2026

- **Sora 2 is gone.** OpenAI shut it down on 24 September, so the OpenAI
  key this project already has can no longer make video.
- **The best image-to-video models are on fal.** MiniMax H3 Max
  (post-trained by fal) tops the Artificial Analysis image-to-video arena
  at 1194 Elo. It costs $0.08 a second at 768p ($0.05 at 480p, $0.16 at
  1080p) and makes 5-15 second shots.
  - Veo 3.1 Lite sits at 1072 Elo and costs $0.03-0.05 a second without
    audio.
  - Seedance 2.0, Kling 3.0 and Wan 3.0 sit between those two and cost
    more.
- **The best picture models with reference images are OpenAI's.** GPT
  Image 2.5 (Flare and Sunburst) and GPT Image 2 lead both image arenas.
  They take several reference pictures on the edits endpoint and bill by
  the token. Measured here, a 9:16 keyframe with two or three references
  costs $0.015-0.03, a third of the flat per-image price assumed before.
- **This PC can't run models** (an i5 with integrated graphics and 8 GB),
  so generation is by API. The finishing is local.

## What was decided

**A studio pipeline, not a filter.** The stages are the ones an
animation studio uses, each doing the job it's best at:

1. **The look** (`pipeline/animation/looks/*.json`, `look.py`). There are
   ten art directions, each covering a medium and how it's rendered:
   - storybook gouache, clean 2D cel, painted anime film, stop-motion
     clay, layered paper cut-out, ink and watercolour, risograph, graphic
     noir, soft 3D, engraving;
   - each sets its light, camera habits, way of moving, the frame rate
     it's drawn at, and its grade and grain.

   A channel picks one, then adds its own notes, palette and sliders.
2. **The bible** (`bible.py`), drawn once per channel and look:
   - three style frames of the channel's world, of which the owner picks
     one;
   - a style sheet drawn from the chosen frame;
   - a model sheet for each recurring cast member.

   Everything else is drawn with these as references. That's where
   consistency within a video, and across videos, comes from.
3. **The storyboard** (`storyboard.py`): one Sonnet call directs the whole
   film. The guide asks for:
   - one visual concept, motifs and a colour script;
   - a hook shot and a landing shot, and varied scale;
   - cuts on the turn of a thought;
   - shots written for what today's models do well, with no text and no
     intricate hand work.

   Every recurring character, place and object gets a description the
   models can hold on to. The code then makes the result safe (`settle`):
   - cuts snap to real spoken words;
   - too-short shots merge;
   - too-long shots become continued takes;
   - shots are fitted to the budget.
4. **Keyframes** (`keyframes.py`): each shot's first frame, drawn with the
   style sheet and the sheets of whoever and whatever is in it.
   - All of them go to one vision call before anything is animated, which
     looks for the wrong subject, off-model characters, off-style frames,
     writing, broken anatomy and captions' space.
   - A failed frame is redrawn once with the problems named.
   - A frame costs about 2 cents and its shot about 40, so this is where
     mistakes are cheapest to catch.
5. **Motion** (`motion.py`, `fal.py`): the channel's video model animates
   each keyframe.
   - A continued take starts from the previous shot's last frame.
   - Three frames of every shot go to one vision call, which looks for
     melting, identity drift, writing, style drift, stillness and
     glitches. A broken shot is made again once if the budget allows.
6. **The finish** (`finish.py`, local ffmpeg). Every shot goes through the
   same chain:
   - retimed onto its narration by at most a quarter;
   - held on the look's cadence (twos, threes);
   - upscaled with a matched sharpen;
   - graded;
   - given paper tooth or film grain.

   Then the shots are cut together. Holding frames on twos is what makes
   it read as animation rather than "AI video", and it hides the shimmer
   video models leave between frames.

**Choosing a look by eye** (added the same day, at the owner's request).
Every look comes with four example pictures, drawn at its defaults with
the same four subjects. The subjects are chosen to show what matters when
picking a style:
- a person in a landscape;
- a face lit close;
- an animal in nature;
- an everyday interior.

Because the subjects are the same, the looks can be compared directly.
The settings page shows them on each look's card, and "See larger" steps
through the looks full size, with "Use this look". The examples are part
of the look, so they're kept in the repository (`looks/samples/`, about
4 MB), not the cache. `tools/animate.py samples` draws any that are
missing, for about a cent each.

**Where it sits.** When animation is on and FAL_KEY is set, the visual
director offers `animation` where it offered `illustration`. The
channel's Pictures slider keeps its meaning: at "Always" the whole video
is animated. All the animated segments of a video are storyboarded
together as one film. On but without the key, the channel falls back to
illustrations and says why on the video's report.

**Costs, and where they were cut without cutting quality:**
- Keyframe-first: pictures are checked before the expensive seconds are
  bought.
- The bible is drawn once per channel. Cast sheets are drawn once per
  character.
- Retiming by up to a quarter means no generated second is wasted
  rounding a shot up to the model's lengths.
- The pace slider sets shot length, which is the main cost lever. The
  price line on the settings page says what a 50-second video costs
  before anything is spent.
- A per-video budget, planned into the storyboard (fewer, longer shots)
  and then enforced. What doesn't fit goes back to other pictures, from
  the end, and is noted.
- Generated audio is discarded; the narration and music bed stay the
  project's own.
- An animatic mode (keyframes held and cut to narration, no video model)
  judges a look on a real script for about 25 cents. It's available from
  settings and `tools/animate.py`.

Measured on "why yawns are contagious" (34 seconds, Curiosity Leak, Clean
2D cel):
- style frames: $0.03;
- storyboard: $0.05;
- two reference sheets: $0.04;
- six keyframes: $0.13;
- keyframe check: $0.01.

The animatic came to $0.21 in all. At the default H3 Max 768p, the six
shots would add about $2.60 of video. A 50-second video at default
settings estimates at about $4.
That's more than stock footage ($0.25), and it's the price of footage
that shows exactly what is said, in the channel's own look.

## Tried and rejected

- **The style frame as the reference.** In the first test, the model
  copied the frame's content as well as its style. The frame's study, with
  its arched window and moon, appeared behind half the shots of a video
  about yawning, and every video would have had that room. The reference
  is now a style sheet of unrelated studies (two faces, hands, a tree,
  stone, sky, a still life, water) drawn from the chosen frame: all of its
  style, none of its content. The keyframe check also flags a frame that
  copies a study.
- **An object element drawn with a person.** In the same test, "brain
  glow" was drawn on the main character, so a stranger in a later shot
  inherited her face. Object sheets are now the object alone, and a
  passer-by is described in the shot, distinct from the cast.
- **Reference-to-video straight from sheets** (no keyframe). It's cheaper
  by the keyframe, but the frame can't be checked before paying for the
  shot, and composition is weaker. Kept as a possibility for later.
- **Running a model on rented GPUs.** At this volume, fal's price per
  second is already close to the cost of the hardware. Renting would mean
  infrastructure to manage, which isn't wanted before a channel earns
  (see the owner's constraints).
- **One model per shot tier** (premium model for the hook, a cheap one for
  the rest). Mixing models in one film changes its motion character. It
  may still be worth it later as a setting.

## Things learned building it

- The web app's restart onto new code fingerprinted the code *after*
  importing it. An edit made during those seconds was already in the
  fingerprint, so the running app served a new template with the old code
  behind it until a hand restart. It now fingerprints before importing
  (`web/__main__.py`), with a regression test.
- Previews write under `cache/animation_previews/`, not `output/`: every
  mp4 under output is a video waiting for review.
- `1.2 // 0.4` is 2.0 in floating point; the shot cap used it.

## Consequences

- There's a new key, `FAL_KEY`, and fal is on the APIs page. Nothing
  changes for a channel until animation is switched on.
- A stylised animated look doesn't need YouTube's altered-or-synthetic
  disclosure, which is for realistic content. A photoreal look would, and
  none of the presets is one.
- Templates keep their own art direction (the Pictures section). On a
  fully animated channel it's worth matching their colours to the
  animation's palette.
- Real motion is untested until the owner adds FAL_KEY. Everything up to
  the video model (bible, storyboard, keyframes, checks, finish,
  animatic) ran for real; the video model's request shapes follow fal's
  published schemas and are covered by tests with a faked service.
