# UGC Shorts pipeline

Seed (quote or topic) → script → voiceover+captions → video, per channel,
on repeat. Format-agnostic: quote channels (Bible, Shakespeare) and
topic-driven channels (jokes, explainers) both run through the same
pipeline — see `config/channels.py` and CLAUDE.md's "Format-agnostic
architecture" for how a new channel/format gets added without code
changes.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here
export ELEVENLABS_API_KEY=your-key-here
```
Voiceover is ElevenLabs (`tts_captions.py`) — sign up at
[elevenlabs.io](https://elevenlabs.io/) for a key. It's paid (free tier
~10k characters/month, then subscription tiers) — this replaced edge-tts,
which was free but sounded noticeably robotic and had occasional
streaming glitches (duplicated audio) that couldn't be fixed on our end
since it's a reverse-engineered wrapper around a free consumer feature,
not a supported API. `config/channels.py`'s `"voice"` per channel is an
ElevenLabs voice ID — the ones checked in are ElevenLabs' own stable
premade voices used as placeholders; swap in your own picks from
[elevenlabs.io/app/voice-library](https://elevenlabs.io/app/voice-library).

Captions and the outro card are rendered with Pillow directly, not
moviepy's ImageMagick-backed TextClip — no ImageMagick install needed.

Narration audio used to have a persistent, deterministic stutter — every
video, not an occasional glitch. It was never ElevenLabs: `audio_utils.py`
was decoding the synthesized mp3s through moviepy's `AudioFileClip`/
`iter_chunks`, whose internal rolling-buffer reader has an off-by-one that
duplicates a sample almost every time the buffer recenters (roughly every
~2 seconds of audio) — dozens of tiny insertions per narration track,
100% reproducible, and untouched by retrying synthesis since the bug was
in decoding our own output, not in generating it. Fixed by decoding via
one direct linear ffmpeg call instead (`decode_audio_file`) — no
seeking/buffering internals left to get wrong; verified two independent
decodes of the same file are now bit-identical.

On top of that fix, every synthesized segment is also independently
double-checked: the actual rendered audio is transcribed locally with
`faster-whisper` (no extra API key/cost) and diffed against the intended
text, retrying synthesis if they don't match closely enough. This is a
safety net for ElevenLabs occasionally mis-speaking a word — a different,
low-probability failure mode, not a stand-in for fixing a deterministic
bug. The Whisper model (`small.en`, ~500MB) downloads automatically the
first time you run the pipeline — that first run will take noticeably
longer.

## One-time setup per source

- **Bible**: no setup — `bible-api.com` is queried live per video.
- **Shakespeare**: build the local quote cache once:
  ```bash
  python -c "from quote_source import build_shakespeare_cache; build_shakespeare_cache()"
  ```

## Footage library

Footage is shared across all channels, not per-channel — a script is
broken into segments (the quote, then a few analysis points; or, for a
topic-driven channel, however many segments the format calls for), each
split into several shots (capped at the channel's `pacing.max_shot_seconds`)
so no single piece of footage runs too long, and every shot gets its own
clip — never the same clip twice in one video. Matching is semantic: each
clip in `footage/manifest.json` has a natural-language description (not
hand-picked tags), and one Claude call per video matches every segment
against every description by meaning — "golden sunlight" matches a
segment about "sunshine" even without exact word overlap, and works
identically for concepts like "coffee" or "SpaceX", not just mood
imagery. See `footage_library.py` for the matching logic.

When a segment doesn't have enough genuinely good matches in the library
to cover all its shots, the same matching call also asks Claude for a
stock-footage search phrase for it (no extra request). If
`PEXELS_API_KEY`/`PIXABAY_API_KEY` is set, that phrase is used to fetch,
normalize, and describe as many real clips as are needed automatically —
fully unattended, no prompts. Without a key set, it falls back to asking
whether to pause and add footage now (then retries the whole match) or
continue with a
fallback for just that segment:
```bash
python footage/manage_library.py add raw_clip.mp4
python footage/manage_library.py list   # see what's already in the library
```
`add` normalizes the clip (crop/scale to 1080x1920, strips audio) and
auto-generates its description from a few extracted frames via Claude's
vision API — no tags to invent by hand. Add `--notes "..."` for context
Claude can't infer from static frames (e.g. camera motion).

For a batch of new downloads, use the crop-review intake tool instead of
`add` directly — naive center-cropping is wrong whenever the subject in a
source clip isn't centered on the axis that gets cropped:
```bash
# drop raw clips into footage/new_downloads/, then:
python footage/review_new_downloads.py
```
It's two phases so you're not stuck babysitting one clip at a time: first
it shows every clip's contact sheet (5 candidate crop positions each) and
collects all your picks, *then* runs the slow part (encoding + captioning)
unattended for the whole batch. Each clip normalizes into
`footage/normalized/`, the original archives into `footage/old_downloads/`,
and it chains straight into the same description step `add` uses.

### Duplicate clips

Before describing a clip (the expensive step — a Claude vision API call),
`add`/`review_new_downloads.py`/the auto-fetch path all perceptual-hash
every sampled frame and compare against every clip already in the
library. A clip only counts as a duplicate if *every* sampled frame
matches closely AND the durations are close — a single-frame check
turned out to false-positive on completely unrelated clips that just
happened to share a similar bright/dark layout at one moment, so this
requires agreement across multiple frames plus duration before treating
anything as already-added: no API call, no new file kept, the existing
manifest entry is reused — this is also what stops the same physical
clip getting assigned to two different shots in one video. Audit the
existing library anytime with:
```bash
python footage/manage_library.py find-duplicates
python footage/manage_library.py find-duplicates --delete   # actually remove them
```
By default it only reports what it found. `--delete` removes duplicates,
but only within a group where every clip matches every other clip
directly (not just chained through a middle clip) — a group that's
connected but ambiguous (some pairs match, others don't) is reported but
never auto-deleted, since that chained-but-not-mutual shape is exactly
what caused the original false-positive incident.

### Bulk-sourcing footage

To fill `footage/new_downloads/` in bulk instead of downloading clips by
hand, `footage/bulk_download.py` pulls from Pexels' and Pixabay's official
free search APIs (not scraping — register your own key at
[pexels.com/api](https://www.pexels.com/api/) and/or
[pixabay.com/api/docs](https://pixabay.com/api/docs/)):
```bash
export PEXELS_API_KEY=your-key-here
export PIXABAY_API_KEY=your-key-here

python footage/bulk_download.py                        # default theme pack, both sources
python footage/bulk_download.py "heaven, storm, dawn"   # your own themes
python footage/bulk_download.py "prayer" --count 10 --source pexels
```
Only the key for the source(s) you use is required. Downloaded clips land
in `footage/new_downloads/`, ready for `review_new_downloads.py`.

## Directory layout

All footage-related content lives under `footage/` — raw intake, staging,
archive, and the final described library. `output/` is finished renders.
`channels/` is per-channel brand assets (logos, merch photos) — not
finished videos and not stock footage, so it gets its own top-level home
rather than living under either:
```
footage/
  manifest.json          # filename, description, duration, source, license, use stats
  library/                # final clips referenced by the manifest
  new_downloads/           # drop raw clips here for review_new_downloads.py
  old_downloads/             # originals, archived after processing
  normalized/                 # crop-reviewed clips before/alongside the library copy
  manage_library.py
  review_new_downloads.py
output/<channel>/<date>/    # finished videos + _meta.txt + _description.txt per video, dated
channels/<channel>/
  logo/                        # logo.png + variant_line/geometric/badge.png + variant_monochrome.png
  merch/                        # uploaded product photos
```

Good footage sources: Pexels, Pixabay, Coverr — all free for commercial
use, no attribution required (double-check each clip's license page, and
record it via `--source`/`--license`).

## Run it

```bash
python main.py bible_daily --count 5
python main.py shakespeare_lines --count 5
python main.py topic_demo --count 1     # throwaway topic-driven example, see below
```

Outputs land in `output/<channel>/<YYYY-MM-DD>/`, one dated folder per
day so you can see what was generated when. Each video's filename is a
sensible slug — the reference for a quote (`john_3_16.mp4`), the topic
for topic-driven content — instead of a random hash, so repeats are
visible at a glance; a genuine repeat within the same day gets `_2`,
`_3`, etc. appended. Each video sits alongside a `_meta.txt` with the
citation (if any) and full script text — handy for writing titles/
descriptions without re-watching the video.

Citations are expanded for speech (and captions, since they reflect
whatever's actually said) — `"John 3:16"` is spoken as *"John, chapter 3,
verse 16"*, not read as a raw number/colon; `"Genesis 2:8-9"` becomes
*"verses 8 to 9"*. See `_expand_citation_for_speech` in
`tts_captions.py`.

A full run has no fast steps (script generation, several TTS calls,
footage matching, encoding a 1080x1920 video), so it prints progress the
whole way: numbered stage headers, which TTS segment is being
synthesized, footage-matching/shot-prep status, and — for the video
encode itself, usually the slowest step — a real frame-by-frame progress
bar with an ETA instead of silence.

## Web GUI

```bash
python webapp/app.py
```
Then open [http://127.0.0.1:5000/](http://127.0.0.1:5000/). A local
Flask app for everything above without touching the CLI or hand-editing
`config/channels.py`: browse channels, edit a channel's settings (voice,
style prompt, pacing, caption/outro style, avoid-imagery list — all the
same fields described below), create a new channel through a form,
generate a video with a live progress log, and browse/play finished
videos. Settings/new-channel saves write straight into
`config/channels.json` — the CLI picks up any GUI edit immediately, no
restart, since both read the same file. Only one generation job runs at
a time; starting a second while one's in progress is rejected.

### Voice Lab

A `/voice-lab` page (linked from the top nav) for auditioning voice ×
cadence × speed combinations before committing one to a channel, without
repeatedly spending ElevenLabs quota. Each voice's row plays ElevenLabs'
own official preview clip for free; picking a voice, a cadence preset
(Tight/Natural/Relaxed/Dramatic pauses), and a speed and clicking "Test
this combo" generates a short real snippet through the actual pipeline —
cached per exact combination, so testing the same one again is instant
and doesn't hit the API a second time. Once you find something you like,
copy the voice ID, cadence values, and speed into the channel's settings
page (which now has a "Speed" field alongside voice/pacing).

The voice list needs your ElevenLabs API key to have the `voices_read`
permission scope — a key restricted to text-to-speech-only will show a
clear permissions error on this page even though normal video generation
still works fine. Add that scope in your ElevenLabs dashboard's API key
settings if you see this.

### Channel logos

```bash
export OPENAI_API_KEY=your-key-here
```
Each channel's card (on the home page) shows its logo once it has one, or
a "Create logo" link into `/channels/<key>/logo` otherwise. Generating one
costs real money (OpenAI's Images API, `gpt-image-1`) — describe what the
channel is about in a few words (the "professional, no text, vector-
style, merch-ready" framing is applied automatically, you don't write
that part), and it generates 10 candidates in one request. Pick the one
you like; that also auto-generates two merch-ready variants — a
"minimalist" restyle (another real generation call) and a "monochrome"
single-ink-color version (free, done locally, good for one-color screen
printing). All of it lands under `channels/<key>/logo/`. Not happy with
any of the 10? Tweak the description and generate again — each attempt
is a fresh paid batch.

### Channel setup wizard

Each channel's dashboard has a **Channel setup** link that walks you
through a guided wizard rather than a bare form: create a logo → get a
dedicated email (Outlook) → link your socials → Patreon → merch-ready
logo versions → a merch store (Printify's popup store, using the logo
you made) → Amazon Associates. Each step explains what you're actually
doing and links straight to the right signup page; Back/Next moves
between them, and the relevant field (a URL, or — for the merch store —
a URL plus product photo uploads) saves the moment you hit Next. The
Amazon step spells out how their program actually works, since it's not
obvious: you get one reusable tracking ID (like `yourtag-20`), which you
append to any product URL yourself (`?tag=yourtag-20`) or generate via
their SiteStripe tool — paste 2-3 tagged evergreen links into the box,
that's it.

You can skip the wizard and edit these fields directly on the settings
page too — a Patreon URL, a merch storefront URL, a small list of Amazon
affiliate links (`Label | https://...` per line). All of it is plain
config either way; nothing here is auto-created on your behalf.

An **End screen** section on the settings page turns on an optional
second outro segment (after the usual channel-branding card). Each CTA
— Patreon, merch, affiliate — toggles on/off independently with its own
editable copy (leave the text blank to use its default), and only shows
up if it's switched on *and* the matching URL/link is actually filled
in. A single video's end screen shows **one CTA, picked at random** each
time you generate — not every active one crammed onto one card — and if
it lands on merch, it shows a random one of your uploaded product photos
alongside the text.

Every generated video also gets a `_description.txt` alongside its
`_meta.txt` — a ready-to-paste YouTube description listing *every*
active CTA (not just the one the end screen happened to show), plus the
FTC-required disclosure line whenever an affiliate link is included. A
CTA's "on" switch controls both the end screen and the description
together, so you can promote a link in the description without
necessarily spending extra video seconds on it (leave the end screen
itself off), or the other way around.

## Adding a channel

The web GUI's "+ New channel" form (above) is the easier way to do this
now — the notes below describe the underlying fields it's setting.
Every channel needs a voice, style prompt, display name/outro subtext,
and output folder, plus a `"content_mode"`:
- `"static_corpus"` — a fixed source is fetched and read aloud; add
  `"source"` (a key in `quote_source.SOURCES`, e.g. `"bible"`). The
  reference/citation is per-quote metadata, not something you configure.
- `"topic"` — no fixed source text; add `"topics"` (a list to rotate/pick
  from). Every segment is generated fresh from the topic and your
  `style_prompt`, which carries the actual format ("write dad jokes
  about...", "explain one scientific concept about..."). See the
  `topic_demo` entry in `config/channels.json` for a minimal working
  example — it's a smoke-test channel, safe to delete once you build a
  real topic-driven one.

To add a channel by hand instead of the GUI, add an entry directly to
`config/channels.json` (not `config/channels.py`, which is now just the
loader — see CLAUDE.md's "Web GUI" section). Optionally override
`"pacing"` (pause lengths, max shot length, crossfade, caption grouping,
segment count) and/or `"style"` (caption/outro colors and font size) —
both default to `DEFAULT_PACING`/`DEFAULT_STYLE` in `config/channels.py`,
so omitting them just matches the existing channels' feel. `main.py`
(and the web GUI) pick up any new channel automatically — no code changes
needed either way. New channels draw from the same shared
footage library as everyone else — which is exactly why you should also
set `"avoid_imagery"`: a list of words/phrases (checked against each
candidate clip's description) that this channel should never show, even
if a clip is otherwise a good thematic match. `bible_daily` sets Islamic-
imagery terms, since the shared library isn't curated per-channel and a
"prayer" clip can just as easily be the wrong religion's prayer. Empty by
default — pick terms for whatever imagery would be wrong for your
channel's audience (a science channel might avoid `["church", "mosque",
"prayer", "worship"]`, for instance).

## Notes on scaling this up

- **Voices**: browse [elevenlabs.io/app/voice-library](https://elevenlabs.io/app/voice-library)
  for voice IDs — giving each channel a distinct voice helps them not feel
  like clones of each other.
- **Cost**: ElevenLabs charges per character generated (see their pricing
  page for current tiers) — the main ongoing cost now, alongside the
  Claude API call per script (a few hundred tokens each — cheap even at
  volume).
- **Rate limits**: bible-api.com is an unauthenticated public service —
  if you're generating dozens of videos in a tight loop, add a short
  `time.sleep()` between requests to stay polite. ElevenLabs enforces
  its own rate limits per plan tier.
- **Avoiding duplicate quotes**: if you want to guarantee no repeats
  across a channel's history, keep a simple `used_quotes.json` per
  channel and re-roll on a match — not built in yet, easy to add.
- **YouTube policy**: YouTube's Shorts monetization rules require videos
  to have meaningful added value beyond the raw source material —
  reused/generic backgrounds are fine, but keep the reflections genuinely
  substantive (not just quote + repeat) to stay clearly on the right
  side of the "reused content" guidelines. Worth rereading their current
  policy before you scale up channel count.
