# Shorts Pipeline

Turns a seed — a quote, or a topic — into a finished vertical video:
script, AI voiceover, word-synced captions, and matched stock footage.
One channel or several, from a web UI or the command line.

Format-agnostic: quote channels and topic channels (jokes, explainers,
anything) run through the same pipeline and differ only in configuration.

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — how the system is put together.
- **[docs/decisions/](docs/decisions/)** — why it is put together that way.

## Setup

```bash
pip install -r requirements.txt
```

Then set the keys you need:

| Variable | Needed for | Get one at |
|---|---|---|
| `ANTHROPIC_API_KEY` | Scripts and footage matching | [console.anthropic.com](https://console.anthropic.com/) |
| `ELEVENLABS_API_KEY` | Voiceover | [elevenlabs.io](https://elevenlabs.io/) |
| `PEXELS_API_KEY` | Fetching footage automatically | [pexels.com/api](https://www.pexels.com/api/) |
| `PIXABAY_API_KEY` | Fetching footage automatically | [pixabay.com/api/docs](https://pixabay.com/api/docs/) |
| `OPENAI_API_KEY` | Generating channel logos | [platform.openai.com](https://platform.openai.com/) |

Only the first two are required to make a video. Without the footage
keys, generation falls back to clips already in the library.

The first run downloads a Whisper model (~500 MB) used to verify each
synthesized segment locally — expect that run to take longer.

## Run it

```bash
python -m web
```

Then open <http://127.0.0.1:5000/>. Browse channels, edit settings,
create a channel, generate a video with live progress, review and publish
what it made.

Or from the command line:

```bash
python main.py                          # list channels
python main.py minute_pastor            # make one video
python main.py minute_pastor --count 5  # make five
python main.py minute_pastor --yes      # don't review each quote
python main.py --costs                  # what everything has cost
```

Output lands in `output/<channel>/<YYYY-MM-DD>/`, named after the quote
reference or topic (`john_3_16.mp4`) rather than a hash, so a repeat is
visible at a glance. Each video sits beside a `_meta.txt` (the script), a
`_description.txt` (paste-ready), and a `_cost.json`.

## The daily loop

**`/review`** is one cross-channel queue of everything awaiting a
decision, oldest first. Watch it, edit the title and description, then
Publish (`P`), Discard (`D`, with a reason) or Skip (`→`). Nothing
navigates; the queue drains under the cursor.

Each video arrives with a generated title (plus alternatives), a real
description, and the two "looks mass-produced" flags — whether footage
had to repeat, and whether the wording is drifting toward an earlier
script.

**`/insights`** answers "how is this going": discard rate, *why* videos
get discarded, render-quality rates, and cost per published video as
opposed to cost per video made. The gap between those two is what
discarding actually costs you.

**`/footage`** is the library as a browsable grid — search it with the
same index the matcher uses, watch a clip on hover, re-describe one whose
description is wrong, confirm a licence, or delete it.

## Uploading to YouTube

`/youtube/setup` walks through making a Google Cloud OAuth client and
connecting each channel to its own YouTube account. After that the review
queue gains an **Upload to YouTube** button that sends the file, the
title you just edited, the description and the tags, and records the
resulting link as the publish.

One thing to know before relying on it: Google restricts uploads from API
projects that have not passed a compliance audit to **private**, whatever
privacy you ask for. Until yours is audited this replaces the whole
manual upload with one switch in Studio, rather than removing it
entirely. The setup page says so, and the app tells you at the moment it
happens rather than leaving you to find a private video days later.

TikTok and Instagram are not built. Both need a reviewed developer app
rather than just credentials, which is a different order of effort and
not worth starting before YouTube is earning.

## Housekeeping

Discarding a video is reversible on purpose — the files stay, a flag
flips — which is right in the review queue and wrong forever. Nothing
removed one until this existed, and a crashed run leaves its per-segment
audio behind where no listing looks.

```bash
python tools/clean_output.py                  # report
python tools/clean_output.py --delete         # act
python tools/clean_output.py --older-than 30  # keep recent discards
```

The gallery's **Discarded** section has the same thing as a button.

Deleting a discarded video does not delete the fact that it was
discarded: a line goes to `config/discard_history.jsonl` first, so the
discard rate and its reasons on `/insights` survive the cleanup. Without
that, a habit of clearing up after each review would drive the keep rate
to 100% precisely by throwing away everything that wasn't kept.

## Footage

One shared library across every channel, in `footage/library.db` with the
clips in `footage/library/`. Matching is two-step: a local text index
shortlists ~50 plausible clips, then one AI call scores those by meaning
and picks. Every shot in a video gets a different clip.

When a segment has no good match and the footage keys are set, the
pipeline searches, downloads, crops, describes and adds real clips
automatically, then re-scores everything — up to three rounds.

Consecutive shots never share a subject or look alike, so a video doesn't
cut between two clips that read as the same shot. And discarding a video
for its footage nudges the clips it used down the rankings, so the
library learns what you keep rejecting.

```bash
python tools/manage_library.py stats             # health, including licences
python tools/manage_library.py enrich            # sharpen matching (~$0.22)
python tools/manage_library.py compact           # --apply to reclaim disk
python tools/manage_library.py prune             # --delete to remove staging files
python tools/manage_library.py find-duplicates   # --delete to act
python tools/manage_library.py add clip.mp4      # add one by hand
python tools/manage_library.py list
python tools/bulk_download.py "storm, dawn"      # fill new_downloads/
python tools/review_downloads.py                 # choose crops, then add
```

**`enrich`** gives every clip a subject, setting, motion and palette,
distilled from the description it already has. Matching weights `subject`
eight times the prose, so a brief asking for prayer beads stops ranking
clips that merely have some on a table. It reads the descriptions rather
than the videos, so the whole library costs about 22 cents — it tells you
the figure and asks before spending it.

**`compact`** trims clips to 15 seconds and re-encodes them. Clips average
20 seconds while a shot is capped at 5, and run at 6.5 Mbps for material
that sits behind captions — on this project's own library that is a 71%
reduction with no visible difference. Fifteen seconds keeps three
distinct windows, so a clip reused across videos still looks different.
Reports by default; `--apply` rewrites, and re-encoding cannot be undone.

**`prune`** removes what the old intake flow left behind. It used to write
every clip three times — raw download, cropped copy, library copy — and
clean up neither of the first two. New fetches keep one copy; `prune`
clears the backlog, and reports by default.

### Licences

`manage_library.py stats` lists any clip whose licence is not confirmed,
and the home page shows the count. Clips fetched from Pexels or Pixabay
record those sites' published terms automatically. For anything added by
hand, confirm it yourself and record it:

```bash
python tools/manage_library.py set-license clip.mp4 "Pexels License - free for commercial use"
```

Do this before monetizing. It is the one thing here that can cost real
money to get wrong.

### Prompt iteration

The style prompt is the highest-leverage setting in the system. Its
settings page has a **Preview a script** button that runs script
generation alone — a few seconds, about a penny, no render — so you can
tune it without committing a whole video to find out what changed.

### The Look tab

Font, size, outline and colours, previewed as you change them. The
preview is a real frame drawn by the same code that renders the video,
over the brightest clip in your own library — so "is 68px readable over
bright footage with a 4px outline" is a question you answer by looking
rather than by rendering a video to find out.

Thirteen caption faces are offered, chosen for holding a stroke outline
and staying legible at a glance. A channel stores which face it wants,
not a font path, so it still renders on a machine that has a different
set installed.

## Channels

Add one through the web UI's **+ New channel**, or by hand in
`config/channels.json`. Every channel needs a display name, an ElevenLabs
voice ID, a style prompt, and a content mode:

- `static_corpus` — a fixed source is fetched and read aloud. Set
  `source` to a key in `pipeline/quote_source.py` (`bible`,
  `shakespeare`).
- `topic` — nothing is fixed. Set `topics` to a list; every segment is
  generated from one of them plus your style prompt, which is where the
  actual format lives ("write dad jokes about…", "explain one scientific
  idea about…").

Optionally override `pacing` (pause lengths, shot length, crossfade,
caption grouping, segment count) and `style` (caption and outro colours).
Both default to values that make an unmodified channel render exactly
like the existing ones.

**Set `avoid_imagery`.** The footage library is shared, so a clip can be
a strong thematic match and completely wrong for one channel's audience.
`minute_pastor` excludes other religions' imagery, because a clip of
prayer is just as likely to be the wrong religion's prayer. A science
channel would exclude `["church", "mosque", "prayer", "worship"]`.

Only the fields you actually change are stored, so a partial save can
never blank something you set elsewhere.

### One-time source setup

- **Bible** — nothing to do; `bible-api.com` is queried per video.
- **Shakespeare** — `python tools/build_shakespeare_cache.py`

## Scheduling

Each channel's dashboard has an **Automatic generation** section: a
cadence in days plus an optional hour. A scheduled run is skipped
whenever the channel still has an unpublished video waiting, so this
cannot build a backlog of unreviewed takes.

The scheduler runs inside `python -m web`. Disable it with
`--no-scheduler`.

## Voice Lab

`/voice-lab` auditions voice × cadence × speed without burning quota.
Each voice row plays ElevenLabs' own preview for free; "Test this combo"
generates a short real sample through the actual pipeline and caches it
per exact combination, so trying the same one twice never hits the API
again.

The voice list needs your key to have the `voices_read` scope — a key
restricted to text-to-speech will synthesize fine but show a permissions
error here.

## Costs

Every billable call is recorded. A finished video shows what it cost on
its own page; a channel's dashboard shows its running total;
`python main.py --costs` shows everything, broken down by operation.

## Monetization and the setup wizard

Each channel's dashboard links to a guided wizard: logo → dedicated email
→ socials → Patreon → merch-ready logo versions → merch store → Amazon
Associates. Each step explains what you are doing and links to where it
actually happens. Nothing is created on your behalf; it is all plain
config you paste in.

An optional **end screen** adds a second card after the branding outro.
Each CTA toggles independently and only appears if it is switched on
*and* its URL is filled in. One CTA is picked at random per video; the
generated description lists them all, plus the FTC disclosure whenever an
affiliate link is included.

## Originality

Every generated script is compared against that channel's own history —
phrase overlap and wording overlap, both — and flagged if it is drifting
toward a reworded copy of something already published. It reports; it
never blocks. This matters because the whole monetization case rests on
the output being genuinely original, and a pipeline generating from one
style prompt forever will converge on its own house phrasing long before
anyone watching one video at a time would notice.

A video that had to reuse a footage clip is flagged the same way, for the
same reason.

## Tests

```bash
python -m pytest                    # everything
python -m pytest -m "not slow"      # skip the real video render
```

## Layout

```
core/       domain: config, jobs, gallery, costs, scheduling, assets
pipeline/   generation: script, tts, footage, assemble
web/        Flask app, blueprints, templates
tools/      operator CLIs
tests/
footage/    library.db + library/ (clips), plus intake staging
output/     finished videos, by channel and date
channels/   per-channel logos and merch photos
config/     channels.json, cost log, script history, schedule
```
