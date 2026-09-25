# Architecture

What this system is, as it stands today. For *why* a given decision was
made — including approaches that were tried and rejected — see
[`docs/decisions/`](docs/decisions/). This file is kept current; that
directory is append-only history.

## What it does

Produces short-form vertical videos: a seed (a quote, or a topic) becomes
a script, which becomes narration with word-level timings, which drives
matched stock footage and burned-in captions.

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
  voice_quota   The ElevenLabs character allowance: read, shown, and checked
                before a voiceover or a scheduled run — see decision 025.
  backup        A dated zip of the state nothing else can rebuild.
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
  posting       Posting to TikTok/Instagram from this PC: the channel's own
                browser profile at the upload page, the video in Explorer.
  launch        Each channel's launch pipeline: ordered stages from idea to
                publishing on its own, computed from real state.
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
                usage recording.
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
  description   The paste-ready description and the meta sidecar.
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
  __init__      App factory: CSRF, error handling, blueprint registration.
  blueprints/   backgrounds, channels, curriculum, footage, gallery, jobs
                (incl. the Activity page), logos, review, services,
                setup, style_setup, voice_lab, youtube.
  forms, helpers

tools/        Operator CLIs (footage library, downloads, caches).
tests/        pytest. `-m "not slow"` skips the real render.
```

## The three loops

The app is organised around what you actually do, at three different
frequencies:

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
artwork.run(plan)            -> a painting under the passage, when switched on
scenes.stage.run(plan)       -> plan.scene_clips: animated scenes for the
                                 stretches of segments the channel's
                                 `scenes.share` asks for (none at 0)
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

A channel without a syllabus keeps drawing from its flat `topics` list.
See decision [018](docs/decisions/018-topic-curriculum.md).

## How long a video runs

`pacing.target_seconds` is the setting; the script's word budget is
derived from it at 2.5 words per second of finished video, measured
across this project's own output. For a quote channel the quote's own
words come out of the budget first, since they are not ours to write.

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
for a look. No plan means "publish on the next check".

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
  well as output.

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

Anything that degrades sets a flag carried into the render report, the
job warnings and the review queue, so a degraded video is never published
as though it had the usual treatment.
