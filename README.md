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

**`/apis`** shows which of these are actually set, what this installation
has spent through each, and a link to each provider's billing page. It
reports spend, not balance — no provider gives a balance to an ordinary
API key, so the number on the account lives behind the link. The one
exception is ElevenLabs' character allowance, which is shown (and warned
about on the home page when it runs low) if the key has the `user_read`
permission. A video that won't fit in what's left is stopped before its
voiceover, and a scheduled run waits for the reset.

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
decision, oldest first, filterable by channel and by what the automatic
checks thought (*Needs a look* / *Passed checks*). Watch it, edit the
title and description, then **Approve** (`A`: queue it for the channel's
next publishing slot), Discard (`D`, with a reason), Back (`←`) or Skip
(`→`). *Queued* shows what's lined up and when it goes out; `U` takes one
back out. **Mark published** (`P`) is for something you've already
posted yourself.

Each video arrives with a generated title (plus alternatives), a real
description, and the two "looks mass-produced" flags — whether footage
had to repeat, and whether the wording is drifting toward an earlier
script.

**`/insights`** answers "how is this going". It starts with the audience:
views, the average percentage of each video people watched, and
subscribers gained, read back from YouTube twice a day for videos
published through a connected channel. It also shows discard rate, *why*
videos get discarded, render-quality rates, and cost per published video
as opposed to cost per video made. The gap between those two is what
discarding actually costs you.

**`/footage`** is the library as a browsable grid — search it with the
same index the matcher uses, watch a clip on hover, re-describe one whose
description is wrong, confirm a licence, or delete it.

**`/activity`** is everything being made right now, in the order it will
happen: the one running job with its stage and an estimate of how much
longer it has, the queue behind it with estimates of their own, and what
just finished or failed. One video is made at a time, so the queue *is*
the estimate. The times come from this installation's own finished
videos, per stage and per channel, so they are a measurement rather than
a guess as soon as one video has completed.

## Topic plans

A random list of topics repeats itself, has no sense of easy before hard,
and runs out in a fortnight at two videos a day. A **topic plan** fixes
all three: an ordered syllabus, each topic used once, running from what
anyone could follow to what only an enthusiast would search for.

Each channel's dashboard links to **Topic plan**, or:

```bash
python tools/curriculum.py outline my_channel --units 25 --topics 1000
python tools/curriculum.py fill my_channel --units 5
python tools/curriculum.py status my_channel
python tools/curriculum.py list my_channel --pending -v
```

It is built in two steps. First an **outline** — one call, under a penny
— giving 25 units in teaching order. You read those 25 titles and decide
whether the arc is right, which is a thing a person can do; a thousand
topics is not. Then **topics are written a unit at a time**, as you
approach needing them, at about a penny each.

A real eight-unit maths outline came out as: numbers we already use →
shapes and space → patterns and puzzles → chance and data → algebra and
functions → structures in mathematics → calculus and change → deep
mathematical ideas. Fractions first, topology last.

Topics are used in order by default, can be skipped or pulled to the
front, and a **discarded video puts its topic back in the queue** — a
take that did not work is not a topic that has been covered. The
dashboard shows how many are left and roughly how many days that is.

**Ordering** (in Settings, once there's a plan) is a channel policy, not
a per-click choice: sequential or random topics, sequential or random
subtopics, finish a topic before the next or round-robin across them —
or a qualitatively different **natural** mode, one "stickiness" number
for how often the next video continues whatever topic is already in
progress versus branching to one that's had less attention.

A channel whose "videos build on each other" (Settings → Channel) can
also say **how far back** that reaches: this topic only, this topic plus
a handful before it, or the whole channel so far.

A full 25-unit, 1000-topic plan costs well under a dollar in total, and
you only pay for units as you reach them.

### Script studio

Once a topic has its subtopics, its scripts can be written ahead of any
video — from the topic plan, **Write scripts**. Several subtopics of one
topic are written together, in one call, so they share a real context
window: no two open the same way, nothing repeats an example. **Read
scripts** opens a notebook — a tab per subtopic, arrow keys to flip
through — where each one can be regenerated (blind, or with an added
instruction like "also mention X") or edited by hand. Nothing needs
approving; a video just uses whatever script is sitting on its subtopic
when it renders, generating one on the spot if there isn't one, exactly
as before this existed.

Discarding a video never touches its script — that's a "the take was
wrong" decision (voice, pacing, footage), not a writing one. Fixing the
writing is: discard the video, fix the script in the notebook, render
again.

## How things look

Settings is one form with a sidebar that switches between its sections:
**Channel** (what it's about, style prompt, where the words come from),
**Voice & timing**, **Look**, **Publishing**, **Money**. One Save button
covering all of them, and nothing is written until you press it. Settings
that only apply while something else is switched on are hidden until it
is, rather than sitting there editable and inert.

**Length** is a slider in Voice & timing. The script's word budget comes
from it, at 2.5 words per second of finished video — measured on this
project's own output rather than guessed.

**Look** carries the captions (font, size, outline, colours), the
**background picture** that sits behind both cards, the **title card**
and the **outro card** — in that order, which is the order the video uses
them. One preview panel shows a real rendered frame of whichever of the
three you are working on.

Both cards can be switched off, and both have their own text size and
outline thickness — the outro's subtext line used to have no outline at
all, which is why it tended to vanish into a busy background photo. The
title card names the channel and the video, and — for a channel with a
topic plan — can optionally add the syllabus topic as a third line. It is
off by default: seconds before the content starts are watch time spent
on nothing, and short-form is decided in the first of them. Worth turning
on for a channel whose videos are a series someone works through, and can
play either before the narration (the original behaviour) or after the
first line, so a channel whose opening line is its own hook doesn't have
to delay it.

The background picture is searched from Pexels and Pixabay, chosen once
per channel, and sits behind the title and outro cards instead of a flat
colour. Blur and dim sliders show their effect live in the title/outro
preview as you drag them — re-derived from the stored original each time,
so moving one back actually undoes rather than compounding — and Apply
saves that as the picture itself. Its licence is recorded the same way a
footage clip's is.

## Writing a channel's style prompt for you

The style prompt used to mean inventing, from a blank textarea, the exact
paragraph of English that reliably produces the voice you want. From
Settings' Channel section, **"Let AI help you write this"** replaces that
with a picker: format, register and personality (required), plus five
optional axes — delivery, how certain it sounds, humour, English variant,
whether it needs a scroll-stopping opener.

It drafts several genuinely different style prompts consistent with your
choices, and shows a real short sample of each — generated through the
same code a real video uses, not a one-line guess — so you pick based on
actual output. An optional "Listen" per candidate reads the sample aloud
in the channel's chosen voice. Picking one saves it as the plain-text
`style_prompt`, still fully editable in Settings afterward.

A channel that already has a real prompt gets "Rewrite this from
scratch" instead, behind a warning: finishing the flow **replaces** the
prompt entirely rather than blending with it. For a small wording change,
edit the textarea directly.

## Uploading to YouTube

`/youtube/setup` walks through making a Google Cloud OAuth client and
connecting each channel to its own YouTube account. After that the review
queue gains an **Upload to YouTube** button that sends the file, the
title you just edited, the description and the tags, and records the
resulting link as the publish.

Connecting also grants read-only access to the channel's statistics,
which is what fills the audience numbers on `/insights`. For retention,
also enable the **YouTube Analytics API** in the same Cloud project;
without it you still get views. A channel connected before this existed
needs reconnecting once; `/insights` says which.

One thing to know before relying on it: Google restricts uploads from API
projects that have not passed a compliance audit to **private**, whatever
privacy you ask for. Until yours is audited this replaces the whole
manual upload with one switch in Studio, rather than removing it
entirely. The setup page says so, and the app tells you at the moment it
happens rather than leaving you to find a private video days later.

### Publishing automatically

Every video now gets two quick automatic checks as it finishes. One reads
the script against the channel's own style prompt, for wrong facts,
advice stated as fact, broken rules and leftover notes. The other looks
at six frames of the finished video, for pictures that contradict the
line, imagery the channel avoids, technical faults and unreadable
captions. Together they cost under a cent. The review queue shows what
they found, and whether the video "could have published itself".

Settings → Publishing → **Publish automatically** turns that into action
for one channel: a video that passes everything approves itself into the
publishing queue, and one that doesn't waits in review with the reason. One clean video in
every five (adjustable) still waits anyway, as a spot check on the checks
themselves. It's off by default. Leave it off until the review queue has
shown you a week or two of verdicts you agree with.

### TikTok and Instagram

Neither lets an unreviewed app post publicly, so they're a hand-off: turn
it on in a channel's publishing plan and, as each video goes out, it and
a caption file land in **`OneDrive\Shorts to post\<channel>`**. On your
phone, open that folder in OneDrive, share the video to TikTok or
Instagram, paste the caption and post. **To post** in the top bar lists
what's waiting; mark each one posted (a link is optional) and the phone
copy is cleaned up. Set `SHORTS_HANDOFF_DIR` to use a different folder.

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

### Backups

```bash
python tools/backup.py "C:/Users/you/OneDrive/ShortsBackups"
```

One dated zip per run, newest 14 kept: settings, topic plans, script
history, cost and discard logs, logos, video sidecars and the footage
database. Not the clips (re-fetchable from their recorded sources) and
not the videos. YouTube credentials are left out unless you pass
`--include-secrets`; reconnecting recreates them. Point it at a synced
folder and run it daily from Windows Task Scheduler.

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
pipeline searches, downloads, crops, describes, enriches and adds real
clips automatically, then re-scores everything — up to three rounds. If a
segment is still short after that, it gets the closest thing available
(the matcher's runner-up, then the best text match), and the review
screen says how many shots were filled that way.

Consecutive shots never share a subject or look alike, so a video doesn't
cut between two clips that read as the same shot. A clip belongs to the
first channel that uses it, so two of your channels never show the same
footage. And discarding a video
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
the figure and asks before spending it. Newly fetched clips are enriched
automatically; this is for clips added by hand, or ones whose enrichment
failed.

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

The style prompt is the highest-leverage setting in the system. Right
under it, a **Preview a script** button runs script generation alone — a
few seconds, about a penny, no render — so you can tune it without
committing a whole video to find out what changed.

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

Add one through the web UI's **+ New channel**. It asks for a name, then
walks you through what the channel makes, whose voice reads it, a logo,
and the monetization steps — you can stop after any of them and come
back. Its dashboard then shows the **launch pipeline**: seven steps from
"say what the channel makes" through a sample video, logo, YouTube
connection, publishing plan and a short trial of the automatic checks,
to "switch on automatic publishing", with the next one and its button at
the top. After launch, **Grow** lists cross-posting, Google's audit and
the money links, for whenever each is worth doing.

Every channel ends up with a display name, an ElevenLabs voice, a style
prompt, and an answer to where its words come from:

- **Existing text, read aloud** — either a built-in library (`bible`,
  `shakespeare`, both public domain) or your own list of quotes, pasted
  in during setup and stored in `config/corpora/<key>.txt`. One entry per
  line, attribution after a dash or a bar:

  ```
  The unexamined life is not worth living. — Socrates
  Nothing is at last sacred but the integrity of your own mind. | Emerson
  ```

  This text is read verbatim in the video, so anything you paste is yours
  to have the rights to.
- `topic` — nothing is fixed. Every segment is generated from a topic
  plus your style prompt, which is where the actual format lives ("write
  dad jokes about…", "explain one scientific idea about…"). Either set
  `topics` to a list to draw from at random, or give the channel a
  **topic plan** (below), which is better in every way that matters.

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

## Publishing plan and scheduling

Each channel's dashboard has a **Publishing plan**: times to publish
(e.g. `18:00`, or several), which days, and how many videos to keep
ready. Approved videos go out one per slot; the app makes new ones in the
background to keep that many queued, and stops if as many are waiting
for your look, so it never buries the review queue. It also shows what
that plan costs in ElevenLabs characters a month, and exactly what it's
waiting for right now.

The scheduler runs inside `python -m web`. On this machine a logon task
("Shorts Pipeline") starts it windowless at login, logging to
`cache/web.log`; remove it from Task Scheduler to stop that. Disable the
scheduler for a manual run with `--no-scheduler`.

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
its own page; a channel's dashboard shows its running total; **`/apis`**
shows it by provider alongside where to top each one up;
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
phrase overlap and wording overlap, both — before it is voiced. A script
drifting toward a reworded copy of something already published is
rewritten once, told what the earlier one said, and the more original of
the two is kept. If it's still close it goes ahead with a flag for
review; it never blocks. A script written ahead of time in the script
studio is flagged but never rewritten, since it may carry your edits. This matters because the whole monetization case rests on
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

`tools/hooks/pre-commit` runs the fast suite before each commit that
touches code. Enable it once per clone with
`git config core.hooksPath tools/hooks`.

Dependencies in `requirements.txt` are pinned to the versions the suite
last passed against. Upgrade one at a time and re-run the tests.

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
