# Spec: generated footage alongside stock b-roll

*Draft for review, 24 Sep 2026. Costs are estimates from published
per-unit prices (sources at the end) and this project's own numbers; each
would be confirmed in a pilot before anything is switched on.*

## 1. The problem

Stock footage can carry a mood. It can't *show* anything. A line about
prayer gets hands in window light, which works. A line about why the
derivative of x² is 2x gets nothing useful from any stock library, and
neither does a news story about a specific discovery. For maths, science,
history or any "how it works" channel, the picture has to demonstrate the
thing being said, and only generated visuals can do that.

The pipeline already has the right seam for this. Every segment carries a
**shot brief**, a literal description of what should be on screen, and
footage is matched against the brief, never the spoken line. So adding
generated footage means adding other ways to *fulfil* a brief. The script,
voice, captions, timing and assembly stay as they are.

## 2. The design: a visual kind per shot

1. **The script writer chooses a visual kind per segment**, alongside the
   shot brief it already writes, from the kinds the channel allows:
   `stock`, `diagram`, `illustration`, `ai_video`, `text_card`. For a
   diagram it also writes a precise spec: what is drawn and what moves,
   with the actual numbers and labels.
2. **Channel settings say which kinds are allowed**, which is the default,
   and a **per-video budget** for paid kinds. Minute Pastor: stock only, as
   now. A maths channel: diagram by default, stock for the human moments. A
   history channel: illustration by default.
3. **Each kind has a renderer** that turns a brief into a clip file of the
   right length (from the voiceover's real timings, as now) at 1080×1920.
   The assembler neither knows nor cares where a clip came from.
4. **Every renderer can fail safely to `stock`, then to a `text_card`**
   (the key phrase on the channel's background). A generated shot that
   fails costs a weaker shot, never the video, matching how footage
   scoring already degrades.
5. **The frame check** (decision 028) already judges each shot against its
   brief. For diagrams it gets one extra question: *does the picture match
   the spec, and are the numbers and labels right?*

## 3. The options

### 3a. Diagrams and animations, drawn by code

**How:** Claude writes a short program (Manim, the library 3Blue1Brown's
videos use; or matplotlib and plain drawing for simpler charts). It's run
locally and rendered to video. If it errors, the error goes back to Claude
for a fix (up to 3 tries), then one frame goes to the vision check.

- **Good for:** maths, physics, charts, timelines, maps, anything with
  exact numbers or labels. Correct by construction when the code is right,
  which diffusion models are not.
- **Cost per shot:** about $0.03–0.10 in Claude calls (code, fixes, one
  check). Rendering is local and free.
- **Per video** (4–6 diagram shots): **~$0.20–0.60**.
- **Time:** 10–60s of CPU per shot to render on this PC; a minute or two
  per video, on top of the current render.
- **Risks:** generated code fails more often than prose; published research
  on this approach reports the render-and-fix loop is what makes it
  dependable. Formula text needs a LaTeX install (MiKTeX on Windows).
  Visual style has to be pinned down per channel (colours, fonts, pacing of
  motion) or every video looks different.
- **Build:** medium–large. The biggest single piece of work here, and the
  one that changes what kinds of channel are possible.

### 3b. Illustrations with motion

**How:** An image model draws the brief in the channel's own art style
(cartoon, woodcut, watercolour, flat vector: set once per channel). The
still is given gentle motion locally (slow zoom and pan, or a parallax
split of foreground and background) for the shot's length.

- **Good for:** history, stories, fables, anything with characters or
  places that don't exist on stock sites, and a consistent look that makes
  a channel recognisable.
- **Cost per image:** about $0.04–0.06 at medium quality (the image model
  the project already uses for logos), or $0.17–0.25 at high.
- **Per video** (6–10 images): **~$0.30–0.60** at medium.
- **Risks:** text inside images is unreliable (keep words in captions, not
  pictures). Consistency of a recurring character across images is only
  partly controllable. Stills with motion read as "illustrated", which suits
  some channels and not others.
- **Build:** small–medium. The motion is local image processing; the API
  call is one function.

### 3c. AI video clips

**How:** A text- or image-to-video model generates a 5–10 second clip from
the brief (optionally from an illustration made in 3b, for a consistent
look).

- **Good for:** a striking opening shot, or something that must move and
  can't be drawn or found.
- **Cost per second:** roughly $0.05 (Wan), $0.09–0.14 (Kling), $0.10
  (Sora 2), $0.15 (Runway), up to $0.40–0.75 (Veo 3.1). Budget for a third
  to a half of generations being unusable.
- **Per video:** a whole 60s video would be ~$5–45 before rejects, which is
  not viable against Shorts revenue. **One or two 5-second hero shots:
  ~$0.50–5.**
- **Risks:** it can't show exact numbers, labels or diagrams. It can't
  depict real people or events truthfully (a news channel must never
  fabricate "footage" of a real event). Realistic synthetic content needs
  YouTube's *altered or synthetic* disclosure, which the upload would set.
  Results vary run to run.
- **Build:** small to integrate one provider, but it needs the rejection
  and check loop to be worth anything.

### 3d. Text and kinetic type cards

**How:** The key phrase animated on the channel's background, drawn with the
existing card and caption code.

- **Good for:** a quote, a definition, a number that should land.
- **Cost:** free.
- **Build:** small. It's also the universal fallback in §2.

## 4. Cost-benefit

| | Per 60s video | vs today (~$0.25) | Enables |
|---|---|---|---|
| Stock only (today) | ~$0.25 | baseline | Mood channels (devotional, quotes, stoic) |
| + diagrams (3a) | ~$0.45–0.85 | +$0.20–0.60 | Maths, science, finance explainers: whole new channel types |
| + illustrations (3b) | ~$0.55–0.85 | +$0.30–0.60 | History, stories, kids, any channel wanting its own look |
| + 1–2 AI hero shots (3c) | ~$0.75–5 | +$0.50–5 | A stronger first second; little else |

**Is it worth it?** Shorts ad revenue is commonly a few cents per thousand
views, so no visual upgrade pays for itself from ad revenue alone. It pays
through *reach*: a better picture keeps people watching, and % viewed
(now on `/insights`) is what the algorithm distributes on. The honest test
is that number. Make the same channel's videos with and without the
upgrade and compare median % viewed over 10–20 videos each.

- **Diagrams** are the clearest case: without them a maths or science
  channel isn't viable at all, so the comparison is against *not having
  the channel*, and $0.50 a video is small.
- **Illustrations** are a good second: cheap, and the per-channel look
  answers the "generic template" risk in YouTube's reused-content policy
  better than shared stock does.
- **AI video** is the weakest case today: it costs the most, is the least
  controllable, is wrong for anything factual, and brings disclosure
  obligations. Keep it as an optional, budget-capped hero shot, added last,
  if at all.

## 5. Proposed pilot

1. Add the per-shot visual kind and the fallback chain (§2), with
   `text_card` as the first non-stock kind. It proves the plumbing at zero
   cost.
2. Build **one** generated kind, chosen by the next channel you want to
   run: **diagrams** for a maths or science channel, **illustrations** for
   history or stories.
3. Make 10 videos. Measure: share of shots that rendered without fallback,
   frame-check pass rate, cost per video, render time per video.
4. Then publish 10–20 and compare % viewed against the stock-only baseline
   before rolling it wider.

## 6. Decisions needed

1. Which kind first: diagrams (maths/science) or illustrations
   (history/stories)? That's really "which channel is next".
2. A per-video budget ceiling for generated visuals (proposed: $0.75,
   enforced like the voice quota).
3. AI video: leave out for now (recommended), or pilot one hero shot per
   video?

### Sources

- Video generation pricing: [DevTk 2026 comparison](https://devtk.ai/en/blog/ai-video-generation-pricing-2026/), [ModelsLab: Veo 3.1 vs Kling 3.0 vs Sora 2](https://modelslab.com/blog/api/veo-3-1-vs-kling-3-sora-2-ai-video-api-cost-2026), [BuildMVPFast July 2026](https://www.buildmvpfast.com/api-costs/ai-video)
- Code-drawn animation: [LLM2Manim (2026)](https://arxiv.org/html/2604.05266), [renderer-in-the-loop Manim generation (2026)](https://arxiv.org/html/2604.18364), [Manim Community](https://www.manim.community/)
- Image pricing: this project's `core/costs.py` (gpt-image-1: $0.011 / $0.042 / $0.167 per 1024² image at low / medium / high; portrait sizes cost more)
