# 038 — Production polish: faster renders, sound, the visual hook, camera, maths, libraries, paintings

**Status:** active.

## What happened

After decision 037, the owner asked for every improvement suggested as
the next step for the videos. These were:

- a music bed and sound effects;
- a visual hook, with key words that pop;
- camera moves inside scenes;
- public-domain paintings (for Minute Pastor especially);
- more image libraries;
- maths tools;
- faster rendering.

All are free to run. None changes what a channel does until it is used
or switched on, except the sound effects, the hook text and the pops,
which improve every video.

## What was decided

### Faster rendering

**The background track is built in ffmpeg, not composited in Python.**
Profiling one render showed moviepy spending 280 of 373 seconds blending
full-screen masked background layers, pixel by pixel in Python, because
every crossfade gives a layer a mask.

Now:

- shots are cut, cropped and normalised by ffmpeg in parallel;
- they are joined with native `xfade` crossfades into one track;
- moviepy only lays the captions over it (`use_bgclip`).

A 39-second video assembles in about 110 seconds, down from about 6
minutes. An all-scenes video takes about 70 seconds. Intermediates use
`ultrafast` at CRF 14, because the final encode sets the quality.

### Sound (`pipeline/sound.py`)

**Effects are synthesised, not downloaded:** pop, whoosh, tick, chime
and clink. That means no licences and no files, and they sound the same
every time. They play on scene actions' exact moments (from each scene's
saved JSON), including every coin landing in a stack. Near-simultaneous
cues are thinned.

**Music comes from a folder: never generated, never fetched
automatically.** It is taken from `channels/<key>/music/`, then the
shared `music/`. It:

- runs under the whole video, including the outro;
- fades in and out;
- ducks under speech, using a level measured from the narration (fast
  attack, slow release), so it rises in pauses and under the outro;
- never clips (the whole mix is scaled down if needed).

Levels and on/off switches are under Settings → Voice & timing. With no
tracks present there is simply no music.

### The visual hook and key words

The script writer adds:

- **`screen_hook`:** the hook's punch in 2-6 words;
- **`emphasis`:** up to six key words.

The punch pops in large over the first seconds, in the captions' font
and colours, while the opening sentence is spoken (capped at 3.6
seconds). Emphasised words land large and settle slightly bigger than
the rest of the caption. A scene at the very start of a video is told to
keep the hook's band clear until the text has gone. Both can be switched
off under Look.

### Camera

The scene's drawing layer is filmed by a camera:

- **Drift:** a slow push-in (3.5% across the scene) so a finished
  picture never sits frozen.
- **Focus and reset:** actions that glide in on an element (zoom up to
  2×) and back out.

The layout check measures the picture without the camera, since a
close-up is deliberate. Camera moves get a soft whoosh.

### Maths

The engine has its own small typesetter for a LaTeX-like subset:
fractions, roots, powers, subscripts, colour per term, the usual
symbols and spacing. Bundling KaTeX was considered and rejected: KaTeX
brings its own typeface, and equations should match the channel's
fonts. Equations wipe in as they're said.

Also added:

- **plots:** grids, ticks, curves that trace themselves, labelled points;
- **number lines:** with marks;
- **a rotate action:** for rearrangement proofs.

All are validated like the rest of a scene.

### Libraries

Props are looked up across several open sets, in the order the art
direction lists them, before anything is generated:

- **colour looks:** Fluent Emoji, then Noto (Apache 2.0);
- **line looks:** Fluent's line set, then Phosphor (bold weight),
  Tabler and Lucide (MIT/ISC), all tinted to the channel's ink.

Between them they cover people doing things and diagram icons. The
scene writer names props the way icons are named.

### Paintings (`pipeline/artwork.py`)

For a channel with Paintings switched on, the segment that reads the
source passage (or the opening, on a topic channel) is shown over a
public-domain painting or engraving of it. These come from the Art
Institute of Chicago's and the Met's open-access collections: free APIs,
no key.

1. The script writer suggests `art_query`, a short search.
2. Candidates are found in both collections, paintings first.
3. Haiku looks at the thumbnails and picks the one that shows the
   passage, or none. It rejects any nudity or graphic violence, because
   those limit ads.
4. A tall work drifts slowly down itself. A wide work is shown whole,
   above the captions' space, over a blurred, darkened copy of itself,
   with a slow zoom.
5. The work is credited in the description.

If nothing fits, or a museum is unreachable, the segment keeps its
footage. Scenes leave a painted segment alone.

Two things were learned on the first live test:

- the Art Institute's image server refuses anonymous clients, so requests
  now identify the app, as its API asks;
- an error page shown to the picker as "artwork" made it reject
  everything, so only real images are passed on.

Its public images top out at 843 px wide, which is enough for a work
shown whole.

## Costs

The only new spend is the painting pick (under a cent) on channels with
Paintings switched on. Everything else runs locally.
