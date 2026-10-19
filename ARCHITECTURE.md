# Architecture

What this system is, as it stands today. For *why* a given decision was
made — including approaches that were tried and rejected — see
[`docs/decisions/`](docs/decisions/). This file is kept current; that
directory is append-only history.

## What it does

Makes videos for the owner's own YouTube channels. It was built for
short-form vertical videos: a seed (a quote, or a topic) becomes a
script, which becomes narration with word-level timings, which drives
matched stock footage and burned-in captions.

**The project is moving to long-form** (decision
[075](docs/decisions/075-long-form-pivot-and-frozen-channels.md); the
plan is [`docs/specs/longform-pivot.md`](docs/specs/longform-pivot.md)):
widescreen documentaries made in approved stages (see Documentaries).
The two live short-form channels, **Minute Pastor and Pub Quiz Buzz
(with its long quizzes), are frozen**: their output must not change, and
`tests/frozen/` holds them to golden fingerprints of their real
pipelines (see Conventions).

It is **format-agnostic by design**. Quote channels and topic channels
differ only in configuration — what kind of content a topic channel makes
(jokes, explainers, anything) lives entirely in that channel's style
prompt. No module below `script_gen` knows what format produced the
segments it's working on.

## Layers

Dependencies point one way only: `web` → `core` → `pipeline`. Nothing in
`pipeline` imports Flask; nothing in `core` imports a blueprint.

```
core/         Domain concepts, usable from the CLI, the web app and the scheduler.
  paths         Every filesystem location, slugify, safe_join. One definition each.
  errors        The exception hierarchy and friendly_message(): one place that
                turns any exception into a sentence a person can act on.
  channels      The channel schema — validated dataclasses, sparse persistence.
  channel_admin Create / rename / reorder / archive / delete.
  jobs          The background queue, persistence, and retry.
  job_context   Which job the current work belongs to; progress reporting.
  job_eta       How much longer a running job has, from this installation's
                own finished jobs — per stage, per channel, median.
  logging_setup Logging for CLI and web, and the per-job log handler.
  progress      moviepy encode progress, as a number rather than scraped text.
  gallery       Finished videos: publish state, discard, thumbnails, cost,
                and purging a discarded take without losing why it was discarded.
  assets        Logos and merch photos on disk.
  fonts         The caption faces this machine can render, by key not path.
  caption_preview  One real caption frame, for the Look settings.
  card_preview  One real title/outro card frame, likewise.
  logos         Logo generation via the image API.
  voice_lab     Voice/cadence/speed auditioning.
  costs         What every API call cost.
  voice_quota   The ElevenLabs allowance in credits (a character of the voiceover
                model costs 0.2, measured from ElevenLabs' own history): read,
                shown, and checked before a voiceover or a scheduled run —
                decisions 025, 069.
  spare_voice   In the last days before the allowance resets, what's left goes on
                videos made ahead, filling every slot in date order (decision 069),
                after what documentaries in production still need (075).
  backup        A dated zip of the state nothing else can rebuild.
  today         The home page's lists: what needs you (each with one action) and
                what runs by itself — see decision 067.
  money         Cost a month at this schedule, credit and voice runway, payback,
                Partner Programme progress (decision 067).
  services      Which external APIs are configured, what each has cost, and
                where its billing page is. Spend, never a balance — see the
                module docstring for why that distinction is load-bearing.
  insights      Aggregate quality, spend and audience — the improvement loop.
  audience      Views and retention for published videos, read back from
                YouTube twice a day — see decision 029.
  scheduler     The five-minute tick: publish what's due, keep each channel's
                queue filled, refresh audience numbers.
  publish_queue Approved videos waiting for their publishing slot; sending
                one out (YouTube upload; TikTok/Instagram listed To post).
  music_library Each channel's music: openly licensed tracks found on Openverse,
                judged for fit, never shared between channels (decision 039).
  code_freshness Notices the code changed on disk; refuses new jobs and
                restarts the app once idle (decision 039).
  posting       Posting to TikTok/Instagram from this PC: the channel's own
                browser profile at the upload page, the video in Explorer.
  instagram     Reels posted by themselves through a Meta app in development
                mode: one Explorer token, each Page's lasting token, a step
                a scheduler pass (decision 116).
  launch        Each channel's launch pipeline: ordered stages from idea to
                publishing on its own, computed from real state.
  long_form     A long-form channel's setup steps: done, next, blocked (076).
  drafts        Draft channels from a pitch: kept as files until accepted,
                then created with their topic plan — see decision 032.
  youtube       OAuth and resumable upload to YouTube.
  publish_gate  Whether a finished video could go out without a person:
                one pure function over its render report.
  autopilot     Uploads a video that passed the gate, on a channel that
                publishes itself; otherwise records why it's waiting.
  curriculum    A channel's ordered syllabus of topics, and where it has got to.
  ordering      Which pending subtopic "make the next video" offers next,
                per a channel's Ordering settings — see decision 024.
  corpus        A channel's own quote list, for channels reading existing text.
  backgrounds   The still picture behind a channel's title and outro cards.
  style_choices Fixed vocabulary for the style & tone picker: format,
                register, personality and five optional axes.
  palettes      Pre-vetted caption colour/font combinations, so no combination
                offered anywhere can be illegible or clash.
  footage_stats Library health and clip poster frames.

pipeline/     The generation stages. No web dependency at all.
  plan          The typed data that flows through: Seed, Script, Segment,
                Shot, Voiceover, RenderPlan.
  llm           The single Claude client: prompt caching, structured outputs,
                usage recording, and batch mode (half price, for the hourly
                background run and videos the scheduler makes ahead -
                decision 063).
  quote_source  Source text for static-corpus channels.
  curriculum_gen  Designs a syllabus outline, then one unit's topics at a time.
  script_gen    Seed -> Script. Also the script studio: batch-writes real
                scripts for several subtopics of one topic in a single call
                (shared context, genuinely consistent), stored on the
                syllabus ahead of any render — see decision 023.
  style_gen     AI-suggested palette/font, and the style & tone picker's
                candidate drafting/sampling.
  channel_draft A pitch in, every decision a new channel needs out, for review.
  tts           Script -> narration + word timings + real segment spans.
  assemble      Footage + narration + captions -> the video file. The
                background track is built by ffmpeg; moviepy lays captions,
                the hook text and cards over it.
  sound         Music bed ducked under speech, synthesised scene effects.
  artwork       Public-domain paintings under the passage (AIC, the Met).
  director      Per segment: footage, illustration (or animation), template or
                diagram, with the channel's slider as the bar (decision 040).
  visuals       Carries out the director's plan; failures fall back to footage.
  illustrate    One image in the channel's style, pushed in.
  animation/    Animation in a channel's own style (decisions 051-054).
    style/        The style: answers to eight questions (053).
      grammar.yaml  Every question and option, what each means for the engines and
                    the drawing, and when it makes sense (conditions on earlier
                    answers). Adding an idea is adding an option here.
      __init__      Conditions, `normalise` (fill and repair answers), `compile`
                    (answers -> the engines' fmt and look), the sentence.
      starting_points.yaml  34 named styles; examples/ holds one real frame of each.
      materials/    Four example pictures of every material, the same subjects.
      describe      A style from a description, limited to the grammar's options.
      preview       One real frame (or a few seconds) of exactly the style chosen.
      gallery       Draws the starting points' examples.
    frame         Vertical short or widescreen: sizes, content box, prompts (054).
    samples       The materials' example pictures.
    look          Prompt text from a compiled look: style, frame rules, motion.
    models        The picture and video models, their prices, request shapes, and
                  the arithmetic of fitting generated seconds to narration.
    fal, images   The two generation clients (fal's queue; OpenAI's reference edits).
    bible         Style frames, the style sheet drawn from the chosen one, and the
                  cast's model sheets, per channel and style.
    storyboard    One call directs the film; `settle` makes it safe and affordable.
    keyframes     First frames with their references, checked before animating.
    motion        Keyframes animated on fal, checked, a broken shot made again once.
    finish        Retime, cadence, upscale, grade, grain; shots cut together.
    stage         Budget, bible, board, frames, motion, finish; resumable, degrading.
    preview       Animatics and animated previews of a finished video's script.
    beats         The composited styles' storyboard: beats of designed layouts and
                  diagrams, exact labels, things arriving on their words; `settle`.
    kit           Things drawn once per channel and style (cut-outs, reused by name),
                  backdrops and the surface per frame, the host's poses.
    compose       A composited style end to end: beats, kit, stage, render, finish.
    compositor/   The motion-design engine, filmed in Chrome:
      runtime.js    Sprites, shadows, stop-motion stepping, labels, arrows, rings,
                    bubbles, tables, diagram strokes, bars, dots and typeset maths,
                    a host, a camera; `__seek(t)`, deterministic.
      layouts       Fifteen designed arrangements in the frame's content box.
      diagrams      Formulas, bullets, matrices, charts, number lines, plots and
                    graphs as primitives, drawn exactly and at no picture cost (054).
      mathtext      LaTeX typeset in Computer Modern by matplotlib, cached.
      expr          Curves' expressions, parsed against an allow-list, never run.
      theme         A compiled style as the stage's inks, labels, rate and shadows.
      script        Beats to a timed stage: arrivals, continuity (move, fade,
                    persist, clear, scene), exits, diagrams that build, camera.
      render        The page (fonts embedded) to video; paper-label captions.
  templates/    Designed motion-graphics templates (HTML/CSS, a seekable
                engine, per-channel theme), filled by one small model call.
  description   The paste-ready description and the meta sidecar.
  social_caption TikTok and Instagram captions written for search: one
                Haiku call for both, never naming a quiz answer (085).
  editor_check  The automatic script and picture checks run on every video.
  similarity    Originality checking against the channel's own history.
  audio         Sample-level audio helpers.
  run           The stage sequence.
  footage/
    store         SQLite clip store (+ weighted FTS5 index).
    retrieval     BM25 shortlisting.
    enrich        Distils structured attributes from existing descriptions.
    compact       Trims and re-encodes clips to reclaim disk.
    intake        Normalize, perceptual-dedupe, describe, record.
    sources       Pexels / Pixabay search and download.
    library       The semantic matcher and the fetch-and-recheck loop.
  scenes/       Animated explanations in a channel's own art direction
                (decisions 034, 035).
    stage         The pipeline stage: plan, write, check, repair once, draw
                  props, render; a scene that can't be made falls back to
                  stock footage and is noted on the video's report.
    writer        The model calls (plan which segments; write each scene
                  with actions anchored to spoken words) and the checks
                  (structure; layout measured in the browser).
    art           A channel's art direction: preset + its own overrides,
                  validated; the preview still.
    runtime.js    The SVG timeline engine: scene JSON in, `__seek(t)` sets
                  every element for time t. Pure, so frames are deterministic.
    render        Scene + art direction -> one self-contained page, captured
                  frame by frame in the installed Chrome, piped to ffmpeg.
    props         The per-channel prop library (channels/<key>/props/<style>):
                  from the free library or illustrated once, cleaned, reused.
    iconlib       The free prop library: Fluent Emoji (MIT) via Iconify, tinted
                  to the channel's ink for line styles (decision 036).
    styles/       Art direction presets: clean_flat, chalkboard, neon, parchment.
    examples/     Hand-written scenes: the pentagram, compound interest.

web/          Flask only.
  __init__      App factory: CSRF, error handling, blueprint registration,
                and what every page's chrome needs (counts, a channel's header).
  templates/    Jinja. `base.html` is the header; `_channel_head.html` is the
                logo, status and tabs every page of a channel opens with;
                `_ui.html` holds the tally-light macros.
  static/       One stylesheet (tokens at the top: colour means state, decision
                068) and one script.
  blueprints/   today, money, backgrounds, channels, curriculum, footage, gallery, jobs
                (incl. the Activity page), logos, review, services,
                setup, style_setup, voice_lab, youtube.
  forms, helpers

tools/        Operator CLIs (footage library, downloads, caches).
tests/        pytest. `-m "not slow"` skips the real render.
```

## The three loops

The app opens on **Today** (`/`, `core.today`): one list of everything
waiting on you, worst first, each with the one button that deals with it,
beside what each channel is doing by itself and what this month costs;
**Money** (`/money`, `core.money`) has the detail. See decision
[067](docs/decisions/067-today-and-money.md). Each channel's own pages
(Overview, Videos, Plan, Settings, Profile) share one header with its
status and tabs between them; colour on screen only ever means state
(decision [068](docs/decisions/068-calmer-interface.md)). Around that, the app is
organised around what you actually do, at three different frequencies:

- **Setting up a channel** (once each) — a one-line pitch drafts the
  whole channel for review (`core.drafts`), or a name creates an empty
  one to fill in by hand; either way its
  dashboard shows the **launch pipeline** (`core.launch`): seven ordered
  stages from "say what the channel makes" to "switch on automatic
  publishing", each computed from real state, with the current one and
  its action at the top. A channel is deliberately creatable while
  incomplete; `channel_progress` refuses to generate until `validate()`
  passes and says why. See decisions
  [019](docs/decisions/019-channel-setup.md) and
  [031](docs/decisions/031-launch-pipeline-and-publishing-queue.md).
- **Producing and publishing** (daily) — `/review`: one cross-channel
  queue, oldest first, keyboard-driven, filterable by channel and by
  whether the checks flagged it. Approving a video queues it for its
  channel's next publishing slot; the scheduler publishes it then, and
  keeps each channel's queue topped up in the background. The unit of
  work is a video, not a channel, so actions address videos by path
  alone.
- **Working out why the output is not good enough** (continuous) —
  `/insights` and `/footage`. How published videos are doing with
  viewers (views, % viewed), discard reasons, render quality, cost per
  *published* video, and a browsable library. This loop did not exist,
  which is why the footage matching problem survived for months with no
  way to see it.

The daily loop also runs on a phone on the home network: `/m`
(`web/blueprints/phone.py`) shows what's being made and what's waiting
for review, with approve, discard, check the questions and make the next
video. It's off until turned on from the PC's **Phone** page
(`core.phone_access`). The app then listens on the network, and anything
not from this PC must give an access code first. See decision
[055](docs/decisions/055-question-review-and-phone.md).

## The pipeline

Each stage is `fn(plan) -> plan`, mutating one `RenderPlan`. Adding a
stage is a function and a line in `pipeline/run.generate`.

```
fetch_seed(channel)          -> Seed          (no prompts, no side effects)
_prepare_output(plan)        -> out_dir, stem
script_gen.run(plan)         -> plan.script   (segments, shot briefs, title, description)
                                 free when the subtopic already has a
                                 script written by the script studio;
                                 checked for originality here, and
                                 rewritten once if it's a retread
tts.run(plan)                -> plan.voiceover, and each Segment's real start/end
                                 (refused up front if the voice quota
                                 can't cover it)
visuals.run(plan)            -> plan.scene_clips: templates, illustrations
                                 (or generated animation, storyboarded as
                                 one film) and diagrams where the director's
                                 score clears the channel's bar (none at 0),
                                 and museum paintings where allowed and
                                 fitting; for a quiz, one board for the video
assemble.run(plan)           -> plan.shots (one per scene; stock footage
                                 matched for the rest), the video file
_finish(plan)                -> meta, description, script history, cost, render
                                 report, the script and picture checks, and
                                 the publish gate's verdict
```

Each segment carries a **shot brief** — a literal, filmable sentence
describing what should be on screen — alongside what is said. Footage is
matched against the brief, never the spoken line. Reflective narration is
abstract and clip descriptions are literal, so matching one against the
other never worked at any confidence threshold; see decision
[012](docs/decisions/012-shot-briefs.md).

Two properties matter and are load-bearing:

- **Timings come from the audio that was actually produced**, never from
  word-count estimates. Punctuation pauses and engine quirks make
  estimates drift enough to visibly desynchronise captions.
- **Every shot gets a distinct clip.** When the library can't manage
  that, `RenderPlan.footage_repeated` is set and surfaced on the finished
  video, because repeated footage is the visible signature of mass
  production.

## Configuration

`config/channels.json` — `{"version": 2, "channels": {...}}`, key order
being display order in the UI. Entries are **sparse**: only what differs
from the defaults in `core/channels.py` is stored. That is what makes a
partial save safe — a form can only change the fields it actually
carries.

Version 1 (a bare `{key: entry}` mapping) is detected on read and
upgraded in place on the next write.

## Footage

One shared library across all channels, in SQLite
(`footage/library.db`), with the clip files in `footage/library/`.

Every clip carries a prose description plus distilled attributes —
`subject`, `setting`, `motion`, `palette`, `time_of_day`, `has_people`.
Matching is a two-step: FTS5/BM25 shortlists ~50 plausible candidates,
weighting `subject` eight times the prose and `setting` three times, then
one Claude call scores those by meaning and picks. The shortlist is what keeps prompt size independent of library
size. Anything the model scores below `MATCH_CONFIDENCE_THRESHOLD` is
treated as no match at all; a shortfall triggers a capped, round-robin
fetch from Pexels/Pixabay and then re-scores everything, up to three
rounds. Clips a round adds are described and then enriched in the same
round, so the re-score sees their subject.

A segment still short after the last round is filled from the best of
what is left: the model's own 3-4 scores for that segment first, then its
lexical shortlist (never a clip the model called actively wrong for it),
and least-recently-used only when both run out. Every shot filled that
way is counted as `footage_unconfident` and shown in review.

The rubric scores one question — *would a competent editor cut to this
clip here?* — and penalises contradiction and inertness rather than
abstraction. Selection then skips any candidate that shares the previous
shot's subject or looks like it perceptually, so a video never cuts
between two shots that read as the same one.

The library is shared, but each clip belongs to the first channel that
uses it (`clips.owner`), and no other channel's search will return it.
The same shot on two channels run by one person is the mass-production
pattern, and viewers who follow both would notice it first. See decision
[030](docs/decisions/030-clip-ownership.md).

Discarding a video for its footage increments `reject_count` on the clips
it used, which adds a small ranking penalty — a nudge, not a ban. Per-channel `avoid_imagery` is enforced twice — candidates are filtered
out before the call, and the list is stated in the prompt as a hard
disqualifier. The deterministic filter catches the literal case; the
prompt instruction is the backstop for imagery a keyword wouldn't catch.

## Animation

A channel with `animation.enabled` gets animation wherever the director
would have drawn a still illustration; at the slider's "Always", the
whole video. Its **style** is answers to eight questions: how it explains,
where, made of what, how people look, a host or not, the mood, the motion,
the words on screen. Each question offers only what fits the answers
before it (`pipeline/animation/style/grammar.yaml`). The settings page
builds a style question by question, from one of 34 starting points or
from a description, and previews exactly what was chosen, as a vertical
short or widescreen. See decisions
[051](docs/decisions/051-generated-animation.md),
[052](docs/decisions/052-animation-formats.md),
[053](docs/decisions/053-style-grammar.md) and
[054](docs/decisions/054-minimal-diagrams-and-widescreen.md).

A style compiles to one of two engines:

| Engine | Styles | Drawn once | Per video |
|---|---|---|---|
| The compositor (`compose`) | objects and diagrams on a tabletop, board, pinboard, model world, canvas, whiteboard, chalkboard, notebook, blueprint, parchment or plain black/white; puppet plays on a toy-theatre stage | the channel's kit of cut-outs, the surface, backdrops, the host | the beats storyboard (~5 cents) and anything new to the kit; no video model, no FAL_KEY |
| Generated (`stage`) | acted or cinematic stories in an animated film, storybook, open world or miniature set | style frames, cast sheets | a storyboard, keyframes and a video model on fal |

**Composited styles.** The beats storyboard chooses designed layouts and
fills them; the layouts place everything in the frame's content box; the
kit supplies the channel's own pictures; diagrams (formulas, charts,
number lines, plots, graphs) are drawn exactly by the compositor, and a
diagram continued into the next beat builds on itself; the script times
it all to the narration's words, with the style's continuity (move, fade,
persist, clear, scene) and entrance; the compositor films it; the finish
grades it. On these channels the director offers no templates or
diagrams, which would break the one continuous picture.

**Generated styles** need `FAL_KEY` and work like a small studio
(`stage`):

- **Look.** The compiled style (medium, light, palette, people, motion,
  cadence, grade) plus the channel's notes, palette and sliders.
- **Bible.** Drawn once per channel and style: three style frames (one
  chosen), a style sheet of unrelated studies drawn from the chosen frame,
  and a model sheet per cast member. The style sheet, not the frame, is
  the reference every picture is drawn with: a scene given as a style
  reference gets its content copied too.
- **Storyboard.** One Sonnet call directs every animated stretch of the
  video as one film, cut on spoken words. `settle` makes it safe, and
  fits it to the per-video budget.
- **Keyframes.** GPT Image 2.5, with the style sheet and the relevant
  sheets as references. Checked together by vision, failures redrawn once,
  before any motion is bought.
- **Motion.** The channel's video model on fal (MiniMax H3 Max by
  default). Continued takes start from the last frame. Checked by vision,
  a broken shot made again once if the budget allows.
- **Finish.** Local ffmpeg. Retimed onto the narration by at most a
  quarter, held on the style's cadence, upscaled, graded and grained
  identically, then cut together.

**Frames.** The same style makes a vertical short (1080x1920) or a
widescreen video (1920x1080), chosen per render by `plan.frame`
(`pipeline/animation/frame.py`). Layouts, surfaces, backdrops, keyframe
sizes, the video model's aspect and the finish all follow it; the kit is
shared. The long-form explainer pipeline that would make widescreen plans
isn't built yet.

Everything is written to the video's working folder and reused on a
retry. A shot the model can't make is held as its keyframe; stretches
the budget can't cover go back to other pictures from the end; both are
noted on the video's report. Style previews land in
`cache/style_previews/`; animatics and animated previews of a finished
video's script run as background jobs from the settings page or
`tools/animate.py`, and land in `cache/animation_previews/`, never in
`output/`.

## Jobs

One job runs at a time, globally. Each job already fans out several
concurrent ElevenLabs calls and footage downloads internally, so running
two videos at once multiplies that against the same rate-limited APIs.
Additional starts queue.

Progress reaches the UI through explicit calls — `report_stage`,
`report_progress`, `report_detail` — routed by a `contextvars` job id
that propagates into worker threads automatically. Log lines reach it
through a logging handler keyed on the same contextvar.

State survives a restart: the status record is persisted on transitions,
log lines append to their own file, and a job still marked running when
the process died reloads as `interrupted`. Retrying reuses the same job
id, so the checkpoints for script, voiceover and footage picks are found
and the completed work isn't paid for twice.

`/activity` is the one page that shows everything in flight, in the order
it will happen: the running job, the queue behind it, and what just
finished or failed. Each job also carries an estimate of how much longer
it has, built by `core.job_eta` from this installation's own completed
records — every job stores when it entered each stage, so a finished one
is five real measurements. Per stage rather than one total (footage
matching dominates and varies most), this channel's history before
everyone else's (segment count and target length drive the variance), and
median rather than mean (one stalled download shouldn't rewrite every
future estimate). Retried jobs are excluded: they reuse their checkpoints
and measure nothing.

## Publishing by hand, and a channel's profile

`publish_queue.put_out` uploads a video to YouTube through the API (once)
and hands it off to TikTok and Instagram. The schedule calls it through
`send`; the video page and Review call it through `publish_now`
(`/api/videos/<path>/publish-now`), which also opens the social pages in
the channel's browser profile with the file selected (`posting.start_all`).

TikTok and Instagram are then posted by hand as numbered steps per
platform (`posting.plan`, `_post_steps.html`, on To post and the video's
page): the upload page opens with the video's path on the clipboard to
paste into the file picker, and each platform has its own caption and
hashtags (`posting.hashtags`). Videos waiting are hard-linked into
`Videos\Shorts to post` (`posting.stage`) and removed once posted. See
decision [059](docs/decisions/059-posting-steps.md).

Instagram is posted to by itself on a channel with a
`publishing.instagram_account` (`core.instagram`, decision
[116](docs/decisions/116-instagram-posts-by-itself.md)). Each scheduler
pass moves every Short handed off in the last two days a step on: a copy
with its index first, a container with the file uploaded into it, then
published once Instagram has processed it, and marked posted with its
link. The state is in the publish sidecar's `handoff.instagram.auto`, so
a restart carries on without posting twice. The Meta app and each
account's Page token are in `config/instagram.json`, outside version
control. TikTok has no such route for an unaudited app and stays by hand.

The captions are written for each platform's search when a video is
handed off (`posting.write_social`, kept in `<stem>_social.json` for the
title it was written for): the search phrase first, a line of related
search terms, up to five hashtags with the channel's own last, then any
licence line its music or pictures need (`posting.credits`). Without
one (the call failed, or the video was retitled), the plain caption is
the title and what the description says about the video, and To post
marks it "plain caption" with a priced button to write it. Decision
[085](docs/decisions/085-captions-written-for-search.md).

`core/channel_profile.py` writes a channel's tagline, YouTube About text,
TikTok and Instagram bios and keywords in one model call and keeps them
in `channels/<key>/profile.json`; the links are always read from the
channel's settings, not written by the model. `core/banner.py` draws the
YouTube banner from the channel's logo, colours and typeface. Both are on
the Channel profile page. See decision
[058](docs/decisions/058-publish-by-hand-and-channel-profile.md).

## Remaking a video

A finished job's checkpoints (script, voice track and timings, footage
picks, the pictures made and which kind each segment got) move beside the
video as `<stem>_remake/`, and its working folder of paid-for pictures
(`<stem>_scenes/`) is kept (a quiz board's isn't). **Remake as is**
(`core/remake.py`, `web/blueprints/remake.py`) starts a new job with its
checkpoints filled from that kit, under a new name, less the parts picked
to make again: an illustration or template for its segment
(`visuals._remake`), or single animated shots, whose files are removed so
the animation stage, which reuses everything else in its folder,
generates only those. A quiz board is always filmed again. Kits are
swept once their video has gone out, a week after it was discarded, or
after a month. See decision [056](docs/decisions/056-remake-as-is.md).

## Deleting output

Discarded videos and their sidecars can be removed, from
`tools/clean_output.py` or the gallery. `gallery.purge` refuses anything
not marked discarded, so the only route to deleting a video is to discard
it first.

Every listing in the app enumerates `output/**/*.mp4`, which means
deleting the file would also delete the fact that it was ever discarded.
So a purge appends a tombstone to `config/discard_history.jsonl` —
channel, stem, reason, dates — and `insights.collect` folds those into the
totals and the discard reasons, but deliberately not into quality, spend
or the recent list, whose sidecars are gone.

## Backups

`tools/backup.py DEST` writes a dated zip of `config/` (minus OAuth
credentials), `channels/`, the output sidecars and a consistent snapshot
of `footage/library.db`, keeping the newest 14. The clip files and the
videos are left out: the clips can be fetched again from their recorded
sources, and published videos live on the platforms. The zip is written
as `.partial` and renamed only when complete. See `core/backup.py`.

## Where a channel's words come from

One decision, two stored fields. `content_mode` is `topic` (everything
generated) or `static_corpus` (existing text read verbatim); for the
latter, `source` is a built-in — `bible`, `shakespeare` — or `custom`,
meaning the channel's own list in `config/corpora/<key>.txt`.

The built-ins are public domain, which is why they are the ones shipped;
each also does work that does not generalise. `custom` is what makes the
mode extensible without writing code.

## Topics

A `topic` channel can have a **syllabus**: an ordered list of topics used
one at a time, in a deliberate progression from what anyone could follow
to what only an enthusiast would search for.

It is built in two layers. One call designs an outline of 20-30 units in
teaching order — that is where the ordering lives, and 25 unit titles are
something a person can actually review. Topics are then written one unit
at a time as they are needed, each call seeing the whole outline and every
title already used so it cannot repeat one; `add_topics` drops duplicates
regardless, because repetition is what this exists to prevent.

`pending` → `used` → `published`, and **a discarded video returns its
topic to pending** — a take that did not work is not a topic that has been
covered. The claim happens at the top of `run.generate`, not in
`fetch_seed`, which must stay free of side effects so a seed can be
rerolled.

A running channel's plan tops itself up: when fewer than 30 are
pending, the scheduler writes the next topic (core.scheduler.top_up_plans).
It also grows by hand from the plan page or the settings' topic count:
topics are added, named, or removed only while empty, so nothing written
is ever touched (core.curriculum, "growing the plan"; decision 043).

A quiz channel keeps every question it has asked in
`config/question_banks/<key>.json`. The writer sees its category's and
related questions; a local check against the whole bank replaces repeats.
Difficulty is a level on a fixed 1-10 scale (`quiz.levels`). A category
that runs out gets its next round on demand; questions that clash (same
answer, one giving another away) are kept out of one round and one long
video; chemical symbols are respelled for the voice by rule (decision
[045](docs/decisions/045-quiz-robustness.md)). A category can be a picture
round (flags, outlines, faces, landmarks, paintings): pictures
come from reusable sources only and are looked at before use
(`pipeline/pictures.py`). Long quizzes run as two series, mixed and per
category, each using a round once
([046](docs/decisions/046-picture-rounds-and-series.md)).

**The question bank** (`pipeline/facts/bank.py`, in `facts/facts.db`) is
where a quiz round's questions come from first: classic pub-quiz
questions written in batches per category, area and level, each checked
once, de-duplicated, levelled 1-10, tagged with every category it fits
and used once per channel. A round from the bank has only its host's
lines written. It's topped up hourly until every category has its
rounds ready, within one total budget for the whole job, set on the Facts
page and checked before each batch (`facts.keep`, `facts.budget`), at
batch prices; a slot whose last few batches didn't fill it is rested
for a few days, and easy batches see how the rater judged the category's
own questions. See decisions [050](docs/decisions/050-question-bank.md)
[063](docs/decisions/063-background-calls-at-batch-prices.md) and
[064](docs/decisions/064-question-bank-total-budget.md).

**Imported questions** (`pipeline/facts/intake.py`, `pipeline/facts/sources/`):
the Open Trivia Database and pub-quiz websites are gathered into an
intake table, then processed within a budget: rewritten in our own words
(Haiku), fact-checked, rated and filed. See decision
[061](docs/decisions/061-imported-questions.md).

**Rounds made ahead** (`pipeline/facts/rounds.py`): each quiz channel keeps
3 ready rounds per category and difficulty, assembled locally from the
bank: within the level's band, or, when that runs short, from the
category's questions ranked by level (Easy the easiest sixth), with at
most two questions per theme. A thin category writing no longer feeds is
flagged dead and not written for
([065](docs/decisions/065-ranked-rounds-dead-categories-and-themes.md)). Planning another set takes ready rounds; a video takes its round
and writes only the host's lines; a category with none ready says it's
running dry rather than writing questions. See decision
[062](docs/decisions/062-rounds-made-ahead.md).

**Category scopes** (`pipeline/facts/scope.py`): each quiz category has a
scope, a sentence of what it covers and one of what it doesn't, written
once from pub-quiz convention and editable (Topic plan → What each
category covers). Areas and batches are written to it, and the bank is
sorted to it: Haiku files each question under the categories it fits,
then Sonnet checks each category's questions against its own definition.
A new, edited or renamed category is sorted again before its next round.
See decision [060](docs/decisions/060-category-scopes.md).

**Coming up** (`core/storyboard.py`, `web/blueprints/storyboard.py`, a channel
tab) shows the next three plan entries as storyboards: each one's stored
script, the lines with their shot briefs or a quiz's questions, written
ahead hourly at batch prices for channels that publish. They're pinned
on the plan (`coming_up`, honoured by `core.ordering` after "Make
next"), so the three shown are the three made. Approving, editing or
rewriting one is optional: one not looked at is made as it is
([073](docs/decisions/073-storyboards-ahead.md)).

**Question review** (`pipeline/quiz_review.py`, `web/blueprints/quiz_review.py`)
lays a round's questions out to judge one by one: fine, too easy, too
hard, wrong, reworded or in the wrong category. Too easy or too hard
moves the question in the bank to the channel's next level
(`owner_level`, which re-rating keeps); wrong rejects it, and the
reason is shown to the bank's writer for that category from then on
(`bank.owner_rejections`). The wrong category files it under the right
one, for good (`question_not_in`, enforced by a trigger on every tag
insert). Each of those swaps in a replacement from the bank, rewriting
only its host lines. A rewording is written from the owner's note,
fact-checked, and kept in the round and the bank in place of the old
wording ([071](docs/decisions/071-owner-verdicts-used.md)). It works on a round written ahead
(changed in place on its subtopic) and on a made short (a draft beside
it, `_script_draft.json`, then "Remake with these changes"). Made shorts
keep their script (`_script.json`); older ones are rebuilt from
`_meta.txt` and `_quiz.json`. A remake (`Seed.remake_of`) reuses the
voice of every unchanged line from `cache/voice_segments/` (`tts.segment_key`), and retrying a job whose voiceover failed partway
reuses every line it already got (the `voiced_segments` checkpoint). See decision
[055](docs/decisions/055-question-review-and-phone.md).

**The fact store** (`pipeline/facts/`, `facts/facts.db`) is the fallback
when the bank is short: facts gathered from Wikidata ahead of any
script. Entities,
facts (subject, property, value, each stored once), categories as sets of
member entities (a fact belongs to every category its subject is in), and
per-channel usage (a fact is asked once per channel). Levels are a fact's
fame-based hardness ranked within its category. A category is mapped onto
Wikidata once by a model (IDs checked), harvested a page deeper whenever
it runs short, and kept stocked hourly in the background
(`facts.keep`, a scheduler duty). A text round is built on unused facts
near its level, each answer checked against its fact, and falls back to
the writer's own knowledge when the store is short. The Facts page and
`tools/manage_facts.py` show and drive it. See decision
[049](docs/decisions/049-fact-store.md).

**Long quizzes** (`pipeline/longform.py`) are not a pipeline run. A job
with seed type `longform` recuts finished quiz shorts: each short saves
where its questions and answers are in its voice track (`_quiz.json`),
so only the host's joining lines are voiced. Only approved shorts are
rounds. Each is made in both formats (answers as you go, answers at the
end), each timed by its own settings, and both go to review. The long
video lives under `output/<channel>/longform/` (`gallery.is_long`),
publishes in its own slots, YouTube only, and always waits for review. A quiz night is
made as soon as enough categories have an approved round at one
difficulty, and a category's own quiz as soon as it has one at every
level, one waiting per series
([066](docs/decisions/066-long-quizzes-when-ready.md)).
See decisions [044](docs/decisions/044-long-quizzes.md),
[047](docs/decisions/047-formats-apart-and-the-quiz-hook.md) and
[048](docs/decisions/048-plain-hooks-and-honest-checks.md).

A channel without a syllabus keeps drawing from its flat `topics` list.
See decision [018](docs/decisions/018-topic-curriculum.md).

## Formats

`format` is `narrated` (a script over footage and graphics, everything
above) or `quiz` (`pipeline/quiz.py`). A quiz branches at two stages
only:

- `script_gen` writes a round: a hook (plain, kept apart from the
  channel's recent hooks, shown on its own screen word by word with the
  category stamped under it), intro, then question and answer segments,
  then a sign-off. Each short is numbered on the board
  (`quiz.next_number`). Each question segment carries
  `pause_after`, the countdown. The round is fact-checked by an
  independent call that must list every correct answer before judging.
  The host's lines are checked locally as the round becomes a script
  (`quiz.tidy_lines`, and `quiz.retidy` for one written ahead): a
  lead-in that corrects itself or misplaces a milestone becomes
  "Question eight.", and an answer that only says the question back is
  cut to the answer. The writer sees the channel's recent hooks, intros
  and sign-offs, to vary them
  ([070](docs/decisions/070-quiz-polish.md)).
- `visuals` films one board for the whole video.

Captions are off (`style.captions_enabled`), and the clock's ticks are
exempt from the effects limits; which tick and how loud is a setting
(`sound.clock_sound`, `pipeline.sound.CLOCK_SOUNDS`). Its topic plan is categories ×
difficulties, written by rule, and topped up a round at a time. A
category's rounds are written easiest first, each seeing the others
(`quiz.write_ladder_below`), and stored until their videos are made in
whatever order the ordering picks. See decisions
[041](docs/decisions/041-quiz-format.md) and
[042](docs/decisions/042-settings-that-apply-and-the-quiz-ladder.md).

## Documentaries

`format` `documentary` (decision
[074](docs/decisions/074-documentaries-in-stages.md)) makes long
widescreen videos, each from one plan entry, in six stages the owner
approves one at a time, or the channel's own autopilot does
(`core.production`, kept under `channels/<key>/productions/<entry>/`;
pages under the channel's Productions tab,
`web/blueprints/productions.py`). Each stage is a job of seed type
`production` (`pipeline.documentary.run.run_stage`), at batch prices
unless asked for now:

- `pitch` ("Angle", `pitch.py`, decision
  [086](docs/decisions/086-documentaries-built-to-be-watched.md)): six
  angles, each a title, thumbnail idea, promise, first line and open
  question, scored; the best chosen unless the owner picks another;
- `outline`: promise, open loops, through-line, visual concept, chapters
  (says, turn, shows, minutes), cast; checked for a short cold open and
  a turn in every chapter (`outline.problems`), written again once if not;
- `script`: scenes with a stage direction, framing, camera move, cast,
  caption, narration and a medium (drawn, a museum painting, or an
  animated card), written a chapter at a time, then read by the editor
  (`editor.py`), which rewrites the weakest chapters;
- `stills`: paintings and card previews (`media.py`, `cards.py`), and a
  keyframe for every other scene (`pipeline.animation.keyframes`) with
  the style sheet and the cast's sheets, vision-checked;
- `video`: voiced; each still cut into shots (`shots.py`: framings named
  by a vision model, cached) with camera moves (`finish.camera_shot`),
  each card filmed in the channel's theme; captions, music; a designed
  thumbnail (`thumbs.py`) and a scorecard (`core.scorecard`); into the
  long-video folder for review;
- `teasers`: vertical shorts written, then drawn and made, into review.

The video's production sidecar records each scene's start and end, so the
retention curve `core.audience` fetches for a documentary is put on the
scene that was playing (`core.retention`), and a week-old film adds up to
two lessons to the channel's list (`core.lessons`,
`channels/<key>/lessons.json`), which every writer reads. With
`documentary.auto_make` on, `core.auto_films` moves the next film on a
stage each scheduler tick, approving up to the storyboard; the finished
video always waits for a look.

Decision [087](docs/decisions/087-a-second-look-at-what-holds-people.md):
a channel's `documentary.voice_model` (v3/v4 perform the script's
`[delivery cues]`, stripped everywhere else by `tts.strip_tags`),
`documentary.dialogue` (a scene's `speaker` voiced by
`render.voices_for`), `documentary.atmosphere` (`atmosphere.py`: embers,
dust, rain or snow screened over a shot, and an exposure lift for dark
stills), cuts on sentence starts (`render.beats_in`), cards drawn over
the scene before (`media.backdrop_for`), and each chapter's `sound`, a
background bed from `ambience.py` (ElevenLabs sound effects, cached).

Decision [088](docs/decisions/088-pictures-kept-redrawn-and-given-depth.md):
each still records what it was drawn from (`still_keys`); a storyboard
drawn again keeps what still fits (`stills.reusable`) and draws the
rest; a shot's move gets depth parallax (`depth.py`, Depth Anything V2
Small in `cache/models/`), finished by `finish.camera_shot(moving=)`.

Decision [089](docs/decisions/089-explainers-gentler-depth-fitting-sound.md):
`documentary.kind` is "story" or "explainer"; `kinds.py` holds the
parts of the pitch, outline, script and critic prompts that differ.
Depth is used only where `depth.suits` (zooms; pans across a whole wide
picture); a chapter's bed plays only under scenes `ambience.fits`.

Decision [090](docs/decisions/090-pictures-drawn-once-checked-closely-labels-per-channel.md):
`stills.repeats` draws a repeated picture once (`stills_reused`);
`stills.flaws` is a close second look for limbs and faces;
`documentary.captions` picks a channel's label (corner, tag, none);
`production.packaging` is the angle a film's title and thumbnail words
come from, changed alone by `production.retitle`. Depth is off by default.

Decision [091](docs/decisions/091-one-channel-a-creator-look-hook-hold-payoff.md):
explainers are structured by `kinds.py` (proof, stakes, mystery, clues,
twist, payoff); `editor.explainer_checks` and `editor.fact_check` run on
explainer scripts only (corrections kept as `script.facts`).

Decision [092](docs/decisions/092-pictures-planned-as-a-set.md):
an outline has `settings` (each at a scale) and each cast member the
settings it exists in; scenes name a setting or "one-off".
`pictures.plan` (after `editor.final_line`) redirects misplaced pictures,
sets `same_as` for pictures shown again and balances settings, checked by
`pictures.audit`/`validate`; the storyboard draws only originals.
`shots.interleave` cuts between neighbours in one setting; the render holds
and fades the last picture (`END_HOLD`, `FADE_OUT`).

Decision [093](docs/decisions/093-repeated-points-brighter-days-real-chapter-titles.md):
`editor.restatements` rewrites lines that only repeat an earlier point,
before the fact check; an outline chapter left untitled is written again.

Decision [094](docs/decisions/094-overnight-batch-overseen-within-a-ceiling.md):
`images.draw_batch` draws a storyboard round as one OpenAI batch in batch
mode; `core.film_budget` caps a film's spend (cost records carry
`production`); `documentary.hours` and `documentary.overseen` let the
autopilot work overnight and leave the script and storyboard to
`core.overseer`, driven by the scheduled `film-overseer` task
(`docs/overseer.md`).

Decision [096](docs/decisions/096-one-reference-sheet-per-picture.md):
`keyframes.combine` sends a still's references as one sheet of numbered
panels (`documentary.combined_references`, on by default), about half the
picture cost.

Decision [097](docs/decisions/097-restarts-overnight.md): at startup
`production.recover_interrupted` fails any stage left working as
`interrupted`, which the autopilot starts again; `production.load` refuses
an unreadable record rather than returning a blank film.

**Settings and setup** (decision
[076](docs/decisions/076-long-form-settings-and-setup.md)). A long-form
channel (`ChannelConfig.long_form`) has its own settings page,
`_longform_form.html`, with only what a film reads: the writing brief,
opening and never-show; what fills the pictures (`documentary.pictures`,
drawn scenes, or diagrams, not built yet), length, seconds per picture
and teasers; voice; the look (the style builder in stills mode, offering
only the approaches its pictures can draw, previewed widescreen); music;
when films and teasers go out. The shorts page stays as it was.
`core.long_form.steps` lists what's done and what's next (shown on
Settings and on Productions until the first film starts; it's also the
channel's launch list in `core.launch`), and each film's page says what
to do now.

Changing a stage makes later ones `stale`. A channel-wide cast library
(`channels/<key>/cast_library.json`, `pipeline.documentary.cast`) keeps
each person's name, description and sheet across videos. The scheduler
pitches angles ahead for the next videos (`storyboard.outline_ahead`),
and makes a documentary itself only on a channel set to make its own
films.

## Thumbnails

A quiz short's thumbnail is its opening screen once the stamp has
settled (`pipeline/thumbnails.py`, `<stem>_cover.jpg`), set on YouTube as
it goes out (decision [082](docs/decisions/082-quiz-thumbnails-and-testing.md)).
With "Test thumbnails" on, a channel learns a thumbnail recipe
(`pipeline/thumbnail_variants.py`, `core/thumbnail_tests.py`): shorts rotate
three variants and are judged on click-through from the Reporting API
(`core/reach.py`); long quizzes use Studio's Test & Compare with the
winner ticked on the video's page
([083](docs/decisions/083-thumbnail-tests.md)).

## How long a video runs

`pacing.target_seconds` is the setting; the script's word budget is
derived from it at 2.5 words per second of finished video, measured
across this project's own output. For a quote channel the quote's own
words come out of the budget first, since they are not ours to write; for
a quiz, the fixed clock time does. Anything over 3:00 is held at the
publish gate: YouTube treats only videos up to three minutes as Shorts.

## Cards

The outro card and the opening title card sit on the channel's background
picture when it has one and a flat colour otherwise. Each can be switched
off: the title card is off by default — for short-form the scroll is
decided in the first seconds — and worth turning on for a channel whose
videos are a series; the outro is on by default, because it is where the
subscribe prompt lives. Both have their own text size and outline
thickness — the outro's subtext line used to have no outline at all,
which is why it disappeared into a busy background photo. The title card
is inserted into the narration, with matching silence spliced into the
audio at the same point; getting that wrong desynchronises every caption
in the video. See decision [020](docs/decisions/020-cards-and-backgrounds.md).

The Look settings preview shows a real composite of whichever card is on
screen, including the background picture's blur and dim exactly as
dragging those sliders would leave them — `core.backgrounds.preview_image`
re-derives the picture from its untouched original at the live slider
values, in memory, so the preview can never promise something the
picture's own Apply button wouldn't actually save. A real render never
passes an override and always reads the already-committed file.

## Publishing

Making a video and publishing it are separate events. A video moves:

    made → waiting (review) → approved → queued → out at its slot

Approval is by you in `/review`, or by the publish gate under autopilot;
both put it in the same queue (`core.publish_queue`), state kept in the
video's publish sidecar (`queued_at`, `approved_by`, `handoff`). Each
channel's **publishing plan** sets slot times, days and a buffer. The
scheduler publishes one queued video per slot (a missed slot is made up
once, within 20 hours, never in a burst) and starts a new video whenever
fewer than `buffer` are queued, pausing if `buffer` or more are waiting
for a look. No plan means "publish on the next check". In the last three days before the
voice allowance resets, what's left of it is spent on videos made ahead
for the slots nothing covers yet, filled in date order across every
channel so there are no gaps, one at a time and within a Claude reserve
(`core.spare_voice`, decision
[069](docs/decisions/069-spare-voice-and-credits.md)). Before any of it,
the narration still owed to documentaries in production is kept back
(`core.production.narration_still_to_voice`), and a documentary
channel's own slots are never filled with shorts (decision
[075](docs/decisions/075-long-form-pivot-and-frozen-channels.md)).

"Out" means a YouTube upload through the channel's connection and, for
channels that want it, a place on `/to-post` for TikTok and Instagram.
There, one click (`core.posting`) opens the channel's own browser
profile, where its accounts stay signed in, at the upload page, shows the
video selected in Explorer and puts the caption on the clipboard.
Neither platform lets an unreviewed app post publicly, and scripting
their upload forms breaks their terms; see decision
[033](docs/decisions/033-posting-from-this-pc.md). A video
handed off but not yet linked counts as out (`gallery.is_out`), so it
never returns to review. A failed upload unqueues the video and puts it
back in review with the reason.

The scheduler lives in `python -m web`, which the "Shorts Pipeline" logon
task starts windowless (`tools/start_web.pyw`, log in `cache/web.log`).

A finished video can also be uploaded to YouTube straight from the review
queue: file,
title, description, tags and category in one request. The OAuth client is
per installation, the tokens per channel, and a successful upload records
the returned watch URL through `gallery.save_publish_info` — the same
state transition the manual flow makes, so nothing downstream needs to
know how a video came to be published.

Google forces videos uploaded by an unaudited API project to private,
whatever privacy is requested. `upload()` therefore returns the privacy
that was granted as well as the one asked for, and the UI says when they
differ. See decision [017](docs/decisions/017-youtube-upload.md).

Publishing can also happen without a person. Every video gets two
automatic checks (script, and six frames of the finished picture) and a
verdict from `core.publish_gate`, which holds it for any pipeline flag,
any blocking problem either check reports, or any check that couldn't
run. On a channel set to publish itself, `core.autopilot` uploads a video
that passed, holds one clean video in every N as a spot check, and
otherwise writes why it's waiting into the report for the review queue.
The verdict is shown on every channel, whether it publishes itself or
not. See decision [028](docs/decisions/028-publishing-without-review.md).

## Costs

Every billable call appends a record to `config/cost_log.jsonl`. Each
finished video gets a `{stem}_cost.json` sidecar; the channel dashboard
shows a running total; `python main.py --costs` shows everything.

A video's cost is keyed by its job id, so a retried job includes its
interrupted first attempt and excludes anything the UI spent meanwhile.

`/apis` reads the same log the other way round — by provider rather than
by video — beside whether each provider's key is actually configured and
a link to its own billing page. For money it reports spend and never a
balance: no provider exposes one to an ordinary API key, and a figure
derived from this log would know nothing about the rest of the account.
The exception is ElevenLabs' character allowance, which its API does
report, and which on a small plan is what actually limits output — see
decision [025](docs/decisions/025-voice-quota.md).

## Conventions

- **Errors**: raise a `PipelineError` subclass with a `user_message`
  written for the person using the tool. The technical detail is for the
  log. Never `str(e)` into a response.
- **Logging**: `get_logger(__name__)`, never `print()`. The job runner
  routes records by contextvar; `print()` would bypass it.
- **Paths**: from `core.paths`. Never recompute `PROJECT_ROOT`, and
  always `safe_join` anything user-supplied.
- **Best-effort code** (checkpoints, cost logging) swallows its
  exceptions and says so in a comment. Nothing else does.
- **Model calls** go through `pipeline.llm`, which checks `stop_reason`
  before trusting `content`, retries a truncated response once with a
  larger budget, and never retries a refusal. Budgets cover thinking as
  well as output. Work nobody waits on runs inside `llm.batched()`,
  which sends the same requests through the Message Batches API at half
  price; independent calls there go through `llm.run_together`. That is
  the hourly run, and every video (`Job.ahead`, the default for
  `jobs.start_job`) unless the owner asked for it now. **Accelerate**
  (`jobs.accelerate`, on Activity and the progress view) moves a job to
  the front of the queue and makes its calls direct, and a running job
  stops batching once an accelerated one waits behind it
  ([072](docs/decisions/072-batch-by-default.md)).
- **Tests never reach a paid service**: `tests/conftest.py` blocks the
  Anthropic client and any non-local HTTP request. Mock `llm.call_json`,
  `llm.client` or the module's `requests`.
- **Frozen channels**: `tests/frozen/` runs Minute Pastor's and Pub Quiz
  Buzz's real pipelines end to end (a short each, and a long quiz recut
  from two shorts) with every outside service recorded, and compares
  the result with `tests/frozen/golden/`: every Claude and ElevenLabs
  request word for word, footage picks, the quiz board's page, frames,
  the sound, the files beside each video, settings and slots. Settings
  come from the snapshot in `tests/frozen/channels.json`, not the live
  config. The run may not touch the installation's own data: its paths
  are redirected and an audit hook refuses the rest. A failure means
  shared code changed what a frozen channel makes; make the change
  additive, or with the owner's agreement run
  `python -m tests.frozen.regenerate` and commit the goldens with it.
  The freeze point is the tag `shorts-freeze-2026-10-06`.

## Degrading rather than failing

Failure cost is kept proportional to what is recoverable. By the time
footage matching runs, a script and a voiceover exist and have been paid
for, so:

| When this fails | What happens instead |
|---|---|
| The footage scoring call | Recency-ordered picks from the same shortlist; `footage_degraded` set |
| A clip file missing from disk | Substituted before the render starts; `footage_degraded` set |
| The local transcript check | Reports a pass; reported unavailable once, not per segment |
| One channel's output directory | Skipped; the review queue still lists every other channel |
| The footage database | The home page still loads and says the library is unreadable |
| Reading the ElevenLabs quota | Treated as unknown; nothing is refused on a number that couldn't be read |
| An automatic script or picture check | Recorded as not run; the gate holds the video for a person |
| An automatic upload | The video waits in review with the reason; it is not marked published |
| An animated shot the video model can't make | Its checked keyframe, held and pushed in; noted |
| Animation beyond the per-video budget | Those segments use other pictures, from the end; noted |
| The whole animation stage | Its segments use footage; `scenes_fell_back` counts them |

Anything that degrades sets a flag carried into the render report, the
job warnings and the review queue, so a degraded video is never published
as though it had the usual treatment.

Decision [107](docs/decisions/107-outlook-teasers-with-their-film.md): `core.outlook`
projects a channel's audience, Partner Programme date and payback from
YouTube's day-by-day figures (`/money/outlook`); a teaser's report names
its film (`teaser_of_video`), so it is published after the film and
counted with it on Insights.
