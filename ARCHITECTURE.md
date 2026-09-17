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
  services      Which external APIs are configured, what each has cost, and
                where its billing page is. Spend, never a balance — see the
                module docstring for why that distinction is load-bearing.
  insights      Aggregate quality and spend — the improvement loop.
  scheduler     Recurring generation.
  youtube       OAuth and resumable upload to YouTube.
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
  tts           Script -> narration + word timings + real segment spans.
  assemble      Footage + narration + captions -> the video file.
  description   The paste-ready description and the meta sidecar.
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

web/          Flask only.
  __init__      App factory: CSRF, error handling, blueprint registration.
  blueprints/   backgrounds, channels, curriculum, footage, gallery, jobs
                (incl. the Activity page), logos, review, services,
                setup, style_setup, voice_lab, youtube.
  checklist     The launch checklist — one definition, no Flask import.
  forms, helpers

tools/        Operator CLIs (footage library, downloads, caches).
tests/        pytest. `-m "not slow"` skips the real render.
```

## The three loops

The app is organised around what you actually do, at three different
frequencies:

- **Setting up a channel** (once each) — a name creates it, then a wizard
  walks content → voice → logo → socials → monetization, and the launch
  checklist tracks what is left. Channel-scoped, because that genuinely
  is a per-channel job. A channel is deliberately creatable while
  incomplete; `channel_progress` refuses to generate until `validate()`
  passes and says why. See decision
  [019](docs/decisions/019-channel-setup.md).
- **Producing and publishing** (daily) — generate, then `/review`: one
  cross-channel queue, oldest first, keyboard-driven. The unit of work
  here is a video, not a channel, so the queue is not channel-scoped and
  its actions address videos by path alone.
- **Working out why the output is not good enough** (continuous) —
  `/insights` and `/footage`. Discard reasons, render quality, cost per
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
                                 script written by the script studio
tts.run(plan)                -> plan.voiceover, and each Segment's real start/end
assemble.run(plan)           -> plan.shots, the video file
_finish(plan)                -> meta, description, originality report, cost, render report
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
rounds.

The rubric scores one question — *would a competent editor cut to this
clip here?* — and penalises contradiction and inertness rather than
abstraction. Selection then skips any candidate that shares the previous
shot's subject or looks like it perceptually, so a video never cuts
between two shots that read as the same one.

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
subscribe prompt lives. The title card is inserted into the narration,
with matching silence spliced into the audio at the same point; getting
that wrong desynchronises every caption in the video. See decision
[020](docs/decisions/020-cards-and-backgrounds.md).

## Publishing

A finished video can be uploaded to YouTube from the review queue: file,
title, description, tags and category in one request. The OAuth client is
per installation, the tokens per channel, and a successful upload records
the returned watch URL through `gallery.save_publish_info` — the same
state transition the manual flow makes, so nothing downstream needs to
know how a video came to be published.

Google forces videos uploaded by an unaudited API project to private,
whatever privacy is requested. `upload()` therefore returns the privacy
that was granted as well as the one asked for, and the UI says when they
differ. See decision [017](docs/decisions/017-youtube-upload.md).

## Costs

Every billable call appends a record to `config/cost_log.jsonl`. Each
finished video gets a `{stem}_cost.json` sidecar; the channel dashboard
shows a running total; `python main.py --costs` shows everything.

`/apis` reads the same log the other way round — by provider rather than
by video — beside whether each provider's key is actually configured and
a link to its own billing page. It reports spend and never a balance: no
provider exposes one to an ordinary API key, and a figure derived from
this log would know nothing about the rest of the account.

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

Anything that degrades sets a flag carried into the render report, the
job warnings and the review queue, so a degraded video is never published
as though it had the usual treatment.
