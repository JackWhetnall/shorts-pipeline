# Shorts Pipeline — Project Context

## What this is
An automated pipeline that produces short-form videos (starting on YouTube Shorts).
Format-agnostic by design: the first two channels are book-quote channels (Bible,
Shakespeare — a quote, original spoken analysis, matched stock footage), but the
pipeline itself doesn't know or care what content format it's running — quotes,
dad jokes, a "one scientific thing" explainer, and future formats not yet decided
all go through the same Stage 1 → Stage 2 contract (see "Format-agnostic
architecture" below). Deliberately not over-optimized for the quote+analysis shape
specifically — quotes are just the first channels built, not necessarily the
long-term core format. Every video: narrated with AI voiceover, matched stock
footage, synced captions.

## Environment
- Windows machine, project lives at `C:\Users\JackW\Documents\YT\`
- Git Bash (MINGW64), Python 3.10 (`python.exe`)

## Platform decision
Considered YouTube Shorts, Instagram, and TikTok. Decided to focus on **YouTube
only** for now — YouTube's Partner Program is the most mature/reliable direct
monetization path (1,000 subs + either 4,000 watch hours/12mo or 10M Shorts
views/90 days). TikTok Creator Rewards requires videos over 1 minute and leans
toward "original" content; Instagram monetization tools are regional/invite-based
and treated as secondary. Revisit TikTok/Instagram later for reach/cross-posting
once the YouTube pipeline is solid — cheap to add once the pipeline exists.

## Central risk: YouTube's reused/repetitious content policy
YouTube can deem monetization-ineligible: "content that exclusively features
readings of other materials you did not originally create," and "AI-generated
content made with generic or unoriginal templates giving the impression of mass
production." Since this pipeline is (quote + AI voiceover + stock footage) run at
scale across multiple channels, this is a real risk, not a hypothetical one.

What YouTube says makes reused material acceptable: "viewers can tell that
there's a meaningful difference between the original video and your video" —
via genuine commentary, substantive modification, or added educational/
entertainment value.

**Ranked by how much each addresses the actual policy risk:**
1. **Original, specific analysis text is the primary lever.** Not a generic
   "here's what this verse means" template — grounded in specifics of that exact
   passage (who said it, surrounding context, historical moment, a concrete
   modern parallel). This is what pulls the video out of "exclusively features
   readings of other materials."
2. **Precise footage-to-content matching** (heaven imagery during a heaven line,
   not one generic loop) is a real secondary signal of production effort, but
   doesn't substitute for weak analysis.
3. **Reusing footage assets across channels/videos is fine** — that's not what
   the policy is checking. What matters is not visibly looping the same clips
   too often within/near each other on one channel.
4. **The two-stage automated architecture itself is a non-issue** — plenty of
   legitimately monetized channels run semi-automated toolchains. Reviewers
   look at the output.
5. **Watch for cross-channel sameness at volume.** If every channel has
   identical structure/pacing/beat-count and you're publishing at high
   frequency across many channels, that pattern itself reads as "mass
   production," independent of any single video's quality. Give each channel
   its own visual identity and format rhythm, not just a different footage tag
   set.

No workflow guarantees passing review — there's inherent human/algorithmic
judgment involved. The goal is moving decisively from "clearly generic
template" toward "clearly original production," with analysis quality getting
at least as much attention as footage polish.

## Format-agnostic architecture
Two-stage pipeline; the interface between them is a standardized,
format-agnostic contract so everything downstream of script generation
(TTS, caption sync, footage matching, video assembly) works identically
regardless of what fed Stage 1 — quotes, jokes, or a future format.

- **Segments, not a single text blob**: `script_gen.generate_script` always
  returns `{"citation": str|None, "segments": [{"text":, "keywords":}, ...]}`.
  A quote video's segment 0 is the quote itself (text given, not generated);
  a jokes video's segments are each generated fresh. No `"role"` field —
  segments are uniform regardless of format. `"citation"` is optional,
  generic metadata (a reference read aloud right after segment 0, e.g. a
  Bible verse) — present for quote-type seeds, absent otherwise.
- **Two seed types** (`config/channels.py`'s `"content_mode"`):
  `"static_corpus"` (a fixed source is fetched — `quote_source.py`'s
  `SOURCES` dict, e.g. `"bible"` — the citation-bearing case) and `"topic"`
  (no source text — `script_gen` generates every segment from a topic in
  `"topics"` and the channel's `style_prompt`, which carries the actual
  format instructions, e.g. "write dad jokes about..."). No code anywhere
  needs to know what a "dad joke" is — that's entirely config.
- **Pacing and style are per-channel config**, not hardcoded: pause
  lengths, max shot length, crossfade duration, caption grouping, and
  segment count live in `"pacing"`; caption/outro visuals (font, colors)
  live in `"style"` — both in `config/channels.py`, both default to
  `DEFAULT_PACING`/`DEFAULT_STYLE`. This is what lets a reflective-quote
  channel keep slow, lingering shots while a jokes channel gets a
  tighter setup/pause/punchline beat — a config difference, not a code
  change.
- **Footage keyword tagging is concept-based, not mood/imagery-only** —
  already true (see Footage library below): matching is semantic
  description-matching, so "coffee", "SpaceX", "dog" already work today,
  not just Bible-style imagery themes.
- **Deliberately deferred**: live/current-events content (news) with
  fact-checking. This is a different kind of risk (editorial/factual
  liability) than anything else here, and building it speculatively
  without a concrete format to test the contract against means guessing
  at what a "verified news segment" actually needs. Topic-driven
  generation (jokes, science explainers) needed no such deferral — it's
  the same "no source text, Claude generates it" shape already built.
- `topic_demo` in `config/channels.py` is a throwaway smoke-test channel
  proving the topic-driven path end to end — not a real channel, safe to
  delete once a real topic-driven channel replaces it.

### Stage 1 — "Create Quote"
Generates the structured segments above. Footage needs to change at
sentence/clause level, not once per video — hence per-segment keywords,
not one keyword set for the whole video. Prompt the analysis generation
to reference specifics of that passage (quote formats) or the topic
(topic formats), not a fill-in-the-blank template. Still open: a
similarity/embedding check against past scripts to flag when generated
text is drifting toward a reworded copy of earlier output — matters more
the longer the pipeline runs unattended.

### Stage 2 — "Compile Video"
Solves the pacing problem by deriving timing from the **real generated audio**,
not by predicting duration from word counts (word-count estimates are
unreliable — punctuation pauses, TTS quirks, etc.):

1. Generate narration audio for the script (per-segment, stitched with
   real pauses from the channel's pacing config).
2. Run word-level timestamp alignment on that audio. If the TTS engine doesn't
   give timestamps natively, run the finished audio through Whisper
   (word-level mode) — this decouples timing logic from whichever TTS engine
   is used, useful since the voice/engine may change over time.
3. Map each segment's text to its start/end time using those real timestamps
   — exact in/out points per segment, driven by what was actually spoken.
4. For each segment: split its real spoken duration into shots (capped at
   pacing's `max_shot_seconds` — a segment longer than that shown as one
   continuous clip reads as static), pull a distinct matching clip per
   shot from the footage library by meaning — never the same clip twice
   in one video — trim or loop each to fit, cut at the shot boundary
   (crossfade reads better than hard cuts). Cut at sentence/clause
   boundaries, not word-by-word — avoids a choppy, obviously-automated
   feel and also looks like how a person would edit.
5. Overlay captions synced to the same word timestamps — each word's
   highlight holds until the NEXT word actually starts, not just until its
   own end, so the caption doesn't blink off during the small natural gap
   between spoken words (it only disappears at a real pause, between
   caption groups, which is intentional — see `_group_words`). Branding is
   an outro card only (channel display name + "subscribe for more") —
   deliberately no title card; for Shorts, viewers should land straight in
   the content. A lower third was considered and dropped for now (redundant
   with captions).
6. Quick human review pass before publish — mainly to catch generated
   text that's degenerated into boilerplate, and footage pairing that
   looks robotic/too-literal rather than intentional.

Citations are expanded before being spoken (and, since captions must
match what's actually said, before being captioned too) — `"John 3:16"`
becomes *"John, chapter 3, verse 16"* instead of being read as a raw
number/colon; a verse range becomes *"verses 8 to 9"*. See
`_expand_citation_for_speech` in `tts_captions.py`.

Output lands in `output/<channel>/<YYYY-MM-DD>/` — one dated folder per
day so it's visible what was generated when. Each video's filename is a
sensible slug (the reference for a quote, the topic for topic-driven
content) instead of a random hash, specifically so repeats are visible
at a glance; a same-day repeat gets `_2`/`_3` appended (`main.py`'s
`_title_for_seed`/`_unique_stem`).

A full run has no fast steps — script generation, several TTS calls,
footage matching, and encoding a 1080x1920 video can together take
minutes with nothing to look at otherwise. `main.py` prints numbered
stage headers ([1/4]..[4/4]); `tts_captions.py` prints which segment
it's synthesizing; `video_assemble.py` prints footage-matching/shot-prep
status and — for the video encode specifically, the slowest single
step — re-enables moviepy's own `logger="bar"` (previously silenced
everywhere with `logger=None`) so there's a real frame-by-frame progress
bar with an ETA instead of total silence.

## Footage library
One shared library across all channels, grown on demand rather than
bulk-sourced upfront: when a segment has no good match, the same matching
call also has Claude produce a stock-footage search phrase for it (no
extra request). With `PEXELS_API_KEY`/`PIXABAY_API_KEY` set, that phrase
drives an automatic fetch-normalize-describe-add — fully unattended.
Without a key, it falls back to asking whether to pause and add footage
now or continue with a fallback.

Matching is **semantic, not tag-lookup** — tag overlap was tried first and
dropped: it's a controlled-vocabulary guessing game (predicting every tag
a future quote might search for) and silently fails on synonyms ("sunshine"
tagged vs. "sunlight" searched for = zero matches, no signal they're the
same thing). Instead, each clip gets a natural-language **description**
(2-4 sentences: subject, setting, mood, lighting, motion), and matching is
one Claude call per video that reads every segment's text alongside every
clip's description and picks by meaning — this is already concept-based,
not mood/imagery-only, so "coffee" or "SpaceX" match exactly as well as
"heaven" or "storm" without any schema change.

**Per-channel imagery to avoid**: a shared, non-curated library means a
clip can be a good thematic match while being the wrong content entirely
for a specific channel's audience — the real incident this was built for:
a clip literally described as an outdoor Islamic prayer service scored
well against Bible-verse segments about "prayer"/"devotion" on theme
alone, which is not imagery a Christian-audience channel should show.
`config/channels.py`'s per-channel `"avoid_imagery"` (a list of words/
phrases, e.g. `bible_daily`'s Islamic-imagery terms) is enforced two ways
in `footage_library.py`: candidate clips matching it (case-insensitive,
against description + filename) are dropped from the pool before the
matching call even runs (`_clip_violates_avoid_list`), and the prompt
itself states the list as a hard disqualifier regardless of thematic fit
— the deterministic filter catches the literal case, the prompt instruction
is the semantic backstop for imagery a keyword search wouldn't catch. The
same filter is applied to fallback selection and to freshly auto-fetched
clips before they're used for the current video (a violating clip still
gets added to the shared library for other channels, just not used here).
Empty by default — every new channel should set a sensible list (a
science channel, for instance: `["church", "mosque", "prayer", "worship",
"religious ceremony"]`).

- `footage/manifest.json` — filename, description, duration, source,
  license, use_count, last_used per clip.
- `footage/library/*.mp4` — the normalized (1080x1920, no audio) clip
  files themselves.
- `footage/manage_library.py add <file>` — normalizes a clip and
  auto-generates its description from a few extracted frames via Claude's
  vision API (no hand-written tags/keywords needed).
- `footage/review_new_downloads.py` — batch intake for
  `footage/new_downloads/`: naive center-cropping is wrong whenever a
  source clip's subject isn't centered on the axis that gets cropped, so
  this shows 5 candidate crop positions (whichever axis has slack —
  usually horizontal, for landscape source footage) as one contact-sheet
  image, lets you pick one, encodes the real clip into
  `footage/normalized/`, archives the original into
  `footage/old_downloads/`, then chains straight into `manage_library`'s
  description step.
- Everything footage-related lives under `footage/` (intake, staging,
  archive, and the described library) — `output/` is the only other
  directory holding video content, kept separate since it's finished
  deliverables, not source material.
- `footage/bulk_download.py` — pulls clips from Pexels'/Pixabay's official
  free search APIs (not scraping) into `footage/new_downloads/`, either a
  built-in generic theme pack or your own query list.
- `footage_library.py` — `pick_clips_for_shots()` (the batched semantic
  match — one clip per shot, never repeated within a video, with a
  recency flag so a clip used in roughly the last 2 days gets
  deprioritized, and the automatic stock-footage fallback described
  above) and `mark_used()`.
- **Match confidence and fetch diversity**: the matcher scores every
  candidate clip 1-10 and anything below `MATCH_CONFIDENCE_THRESHOLD`
  (7) is treated as no match at all — added after real use showed it
  calling loosely-related clips "good enough" on theme alone (e.g. a
  generic crowd shot offered up for a segment specifically about doubt).
  Separately, the auto-fetch step asks Claude for several SHORT, DISTINCT
  search phrases per segment (e.g. "open hands", "hoping", "asking") and
  queries each one independently at a small per-query count, instead of
  one broad phrase fetched at a high count — the old one-phrase approach
  is what caused "20 videos of calm water" for a single shortfall, since
  any one query, however broad, collapses into near-duplicates of itself
  once fetched at volume. Both fixes live in `_build_prompt` (the JSON
  schema now returns `"matches": [{"filename", "confidence"}]` and
  `"search_queries": [...]` instead of a single filename list and a
  single phrase) and `_auto_fetch_and_add` (now takes a list of queries).
- **Fetch-and-recheck iteration**: auto-fetch used to trust whatever it
  downloaded unconditionally — filtered against `avoid_imagery`, but never
  actually re-scored for relevance — and stopped after one round
  regardless of whether the fetch helped. `pick_clips_for_shots` now loops
  back through the SAME matching/scoring call after a fetch (up to
  `MAX_FETCH_ATTEMPTS` = 3 rounds total), so a freshly fetched clip only
  gets used if it's genuinely rated a good match, exactly like an
  already-owned clip. `tried_queries_by_segment` tracks what's already
  been searched per segment and gets folded into the next round's prompt
  (`_build_prompt`'s "already searched without finding enough good
  matches... try different angles" note) so a retry pushes toward
  different search terms instead of repeating a query that already
  didn't work. Once attempts are exhausted, falls back to `_pick_fallback`
  same as before.
- **Duplicate clips**: before describing a new clip (the expensive step —
  a Claude vision call), `manage_library.py` perceptual-hashes every
  sampled frame (the same frames used for description — 8x8 average hash
  each) and compares against every clip already in the library; a clip
  only counts as a duplicate if *every* sampled frame matches (Hamming
  distance ≤6/64 each) AND the durations are close. A single-frame check
  was tried first and caused a real false-positive incident — two
  completely unrelated clips (a crowd photo, a wave photo) can share a
  similar coarse bright/dark layout at one sampled moment purely by
  chance; requiring agreement across every sampled frame plus duration
  makes that essentially impossible while still catching genuine
  duplicates (the same source re-encoded/re-exported). Skips the describe
  call entirely on a match and reuses the existing manifest entry instead
  of adding a near-identical one — this is also what stops the same
  physical clip getting assigned to two shots in one video.
  `python footage/manage_library.py find-duplicates` audits the whole
  existing library the same way; `--delete` removes them, but only within
  a *full clique* (every clip in a group matches every other clip
  directly, not just chained through a middle clip) — a group that's
  connected but not a full clique is reported as "ambiguous" and never
  auto-deleted, since a chain-only connection is exactly the shape that
  caused the false-positive incident.

The library has grown past the original 8 Bible-book clips (now also
includes generic reaction/stock footage plus auto-fetched additions from
real runs) but coverage is still uneven — expect early segments in a new
format to fall back to a generic pick or trigger auto-fetch until more
themed footage accumulates for that format. None of the source clips'
licenses are verified yet (recorded as "unverified" per clip) — confirm
before scaling up or monetizing.

## Web GUI
`webapp/` — a local Flask app (`python webapp/app.py`, then
http://127.0.0.1:5000/) replacing hand-editing `config/channels.py` and
running `main.py` blind: browse channels, edit a channel's settings,
create a new channel through a form, trigger a video with live progress,
and browse/play finished videos. Built as a thin layer over the existing
pipeline modules — no pipeline logic is duplicated in `webapp/`.

- **Config storage**: channel *data* now lives in `config/channels.json`,
  not a Python literal — `config/channels.py` is a loader/merge layer
  (`load_channels()`) that applies `DEFAULT_PACING`/`DEFAULT_STYLE`/
  `DEFAULT_AVOID_IMAGERY` on top of whatever's in the JSON, exactly as it
  always merged the in-code defaults. `CHANNELS`'s shape — and therefore
  every downstream consumer — is unchanged. The webapp always calls
  `load_channels()` fresh (never the module-level `CHANNELS` name), so a
  settings save is visible immediately, no restart, and the CLI picks up
  GUI edits for free since it's reading the same file. One gotcha this
  surfaced: `channels.json` can only hold lists, but PIL wants a tuple for
  `style["outro_bg_color"]` — `_channel()` converts list→tuple on load.
- **Non-interactive generation**: `main.py`'s seed selection is split into
  `fetch_candidate_seed(cfg)` (no `input()`) and `pick_seed(cfg)` (the
  CLI's interactive reroll loop built on top of it); the web app drives
  accept/reroll from UI buttons instead of stdin. `main.py`'s
  `generate_video_from_seed(channel_key, seed, cfg, interactive=True)` is
  the shared core (script → voiceover → footage/video → metadata) both
  the CLI and the web app call — `interactive=False` threads through
  `video_assemble.build_video` to `footage_library.pick_clips_for_shots`,
  skipping its "pause here to add footage" stdin prompt (a hard blocker
  with no TTY to read from on a background thread) in favor of going
  straight to fallback clips.
- **Background jobs**: `webapp/jobs.py` runs one generation at a time on
  a `threading.Thread` (a second attempt gets `409`) — not a limitation
  worth solving for a single local user, and a real constraint anyway:
  progress capture works by temporarily redirecting `sys.stdout` *and*
  `sys.stderr` (moviepy's `logger="bar"` tqdm output goes to stderr by
  default, confirmed against the installed `proglog`/`tqdm`, not
  assumed), which patches them process-wide — two concurrent jobs would
  corrupt each other's captured output. Ordinary `print()` calls are
  newline-terminated and become scrollback log lines; the tqdm bar's
  carriage-return-terminated updates overwrite a single "current
  progress" field instead, so a live percentage/ETA doesn't spam the log
  with hundreds of bar-redraw lines. The frontend (`webapp/static/app.js`,
  plain vanilla JS, no build step) polls `GET /api/jobs/<id>` about once
  a second.
- **Gallery**: lists `output/<channel>/**/*.mp4` — `Path.rglob` handles
  the current dated-folder layout and older flat files from before that
  convention existed uniformly, no special-casing needed. Reads each
  video's paired `_meta.txt` with a UTF-8-first, cp1252-fallback read —
  older meta files predate a UTF-8 encoding fix and would otherwise crash
  the whole gallery page over one stray curly quote or em dash in a
  single old file.
- **Voice Lab** (`/voice-lab`, `webapp/voice_lab.py`): auditions voice ×
  cadence × speed combinations without hand-editing channel config or
  repeatedly burning ElevenLabs quota. Each voice row plays ElevenLabs'
  own official `preview_url` (free, no synthesis) for a first-pass
  listen; a "Test this combo" button generates a short snippet with the
  chosen cadence preset + speed applied via the real pipeline
  (`tts_captions.generate_voiceover`, so it gets the same stutter fix and
  transcript-verification safety net a real video does) and caches it —
  `cache/voice_lab_samples/<voice_id>_<preset>_<speed>.mp3`, keyed on the
  exact combination, so testing the same combo twice never re-hits the
  API (verified: ~9s for a fresh combo vs ~2s and a byte-identical file
  for a repeat). Cadence is 4 named presets (tight/natural/relaxed/
  dramatic), not raw pause-value sliders — "natural" matches
  `DEFAULT_PACING`'s current values exactly. Speed is ElevenLabs' real
  `voice_settings.speed` field (confirmed via their docs and a live test:
  0.8 vs 1.2 produced 6.27s vs 4.32s for identical text) — now a
  first-class per-channel setting (`config/channels.json`'s `"speed"`,
  default 1.0, wired through `generate_voiceover`/`_synthesize`/
  `_tts_segment`), with a matching field on the channel settings form so
  a combo you like in the Lab can be copied straight in. The voice list
  itself needs the ElevenLabs API key's `voices_read` permission scope —
  a key restricted to text-to-speech-only will 401 on `/v2/voices` even
  though synthesis works fine; the page surfaces ElevenLabs' actual error
  detail (not just the HTTP status) so this is diagnosable from the UI.
- **Monetization** (`config/channels.py`'s `monetization`/`end_screen`,
  `description_gen.py`): plain per-channel config, pasted in manually —
  Patreon URL, merch URL, a small per-channel list of affiliate
  `{label, url}` links. Never auto-created — a guided
  `/channels/<key>/setup/<step>` wizard (`webapp/app.py`'s `setup_step`,
  `step` ∈ logo → email → socials → patreon → merch_logo → merch_store →
  amazon, Back/Next between them) links out to where each actually gets
  created (Outlook for a dedicated inbox, Patreon's creator signup,
  Printify's popup store for merch, Amazon Associates — the Amazon step's
  instructions explain the
  reusable `?tag=yourtag-20` tracking-ID mechanic, since it's not
  obvious), saving that step's field(s) immediately on Next. Each CTA's
  own `enabled` flag (not `end_screen.enabled`, which only gates whether
  the extra video segment renders) is the single source of truth for
  "this is actively promoted," shared by the video, the description, AND
  now the merch photo, via `config.channels.resolve_active_ctas` — one
  function every consumer calls, so none of them can disagree about
  which CTAs are live. A CTA only ever renders anywhere if its flag is
  true AND the underlying URL/link list is non-empty. A single generated
  video's end screen shows **one CTA, chosen at random** each time (not
  every active one stacked in one card) — description_gen.py's
  `_description.txt` still lists all of them, only the on-screen card is
  randomized. The merch CTA additionally composites a random uploaded
  product photo (`merch_assets.py`, `channels/<key>/merch/`, collected
  during the wizard's `merch_store` step) above its text if any have been
  uploaded, falling back to text-only like the others otherwise. The
  wizard's field saves write to the RAW stored entry (`channel_store.
  get_raw_entries()`), not the DEFAULT_*-merged `channel` dict — merging
  onto an already-merged dict and saving it back would re-apply
  `_channel()`'s list-concatenating defaults (e.g. `avoid_imagery`) a
  second time on next load. Settings-form saves still write the complete
  merged entry as before (see channel_store.py's docstring) — only the
  wizard's narrower per-step saves needed this distinction. Because
  settings-form saves rewrite the complete entry, any field the wizard can
  set (like `socials`, added below) also has to exist on `_channel_form.html`
  and be rebuilt by `_parse_channel_form` — otherwise a settings save made
  after a wizard step would silently wipe that step's data, since there'd
  be nothing in the submitted form to repopulate it from.
- **Socials** (`config/channels.py`'s `DEFAULT_SOCIALS`): the channel's own
  YouTube/TikTok/Instagram profile links — purely informational (no
  video-assembly or description-generation code reads these), just a
  place to track where the channel actually lives. Set via the wizard's
  `setup/socials` step, or via the settings form's own "Socials"
  fieldset — both write-paths use the same full-entry-vs-raw-mutation
  split described above.
- **Channel setup wizard order** (`webapp/app.py`'s `SETUP_STEPS`):
  `logo → email → socials → patreon → merch_logo → merch_store → amazon`.
  Logo is first since every later step benefits from having one already
  (a profile picture for socials, a mark for merch); "merch" is two
  separate steps, not one — `merch_logo` (generating the merch-ready
  minimalist logo variants, see "Channel logos" below) has to come before
  `merch_store` (the actual storefront URL + product photos) since the
  latter's instructions assume you already have print-ready art. Every
  step template lives at `webapp/templates/setup_<step>.html` (`logo` and
  `merch_logo` have no `step_fields` block — nothing to save, they're
  just guided checkpoints pointing at the logo page / the
  variant-generation button respectively, same as `email` always was).
  `_wizard_shell.html`'s step-dots loop over a `steps` variable passed
  from the route rather than a hardcoded list, so this order only needs
  to change in one place (`SETUP_STEPS`) — every step's own `<h1>` reads
  its number from `step_index` rather than a hardcoded digit, for the
  same reason.
- **Channel dashboard** (`/channels/<key>`, `webapp/templates/
  channel_dashboard.html`): a per-channel home page that used to not
  exist — previously the only per-channel destinations were reached
  individually from the global channel-list card (Settings/Gallery/Create
  Video/etc.), with no single place showing overall channel state. Shows:
  video count + most-recent-video date (`gallery.count_videos` +
  the new `gallery.latest_video_mtime`, the latter added specifically so
  this didn't need to call `list_videos` — which builds full metadata for
  every video, including reading each paired `_meta.txt` — just to read
  one timestamp); a **launch checklist** built fresh on every load from
  real state (no stored "is this done" flag anywhere — `logo_gen.has_logo`/
  `has_merch_variants`, each `socials`/`monetization` field's presence,
  video count), in the same order as `SETUP_STEPS`, each unchecked item
  linking straight to where it gets fixed — collapsed by default (native
  `<details>`, no `open` attribute) with a `.badge` on the summary showing
  how many items are left (omitted once nothing's left), and repositioned
  by a `{% macro launch_checklist() %}` called from two different spots in
  the template: right after "Quick actions" while `checklist_remaining` is
  nonzero, or after the "Your links" card (effectively the bottom of the
  page) once everything's done — the macro avoids duplicating the
  checklist markup between those two call sites; and a "Your links" card
  showing socials/monetization URLs as a **tiled board** (`.tile-row`/
  `.link-tile`, visually distinct from the plain pill-style `.links-row`
  buttons used for external signup links elsewhere in the wizard) — one
  row of tiles for socials, one row for monetization. Every other
  per-channel page's back-link now points here instead of straight to
  Settings or the global channel list — index → dashboard →
  {settings, logo, gallery, create video, setup wizard} is the intended
  navigation shape now, with the global channel list's card actions kept
  as direct shortcuts for anyone who wants to skip the dashboard.
- **Channel rename** (`channel_store.rename_channel`, `/channels/<key>/
  rename` behind a small pencil `.icon-btn` next to the channel name on
  the dashboard, not a section of its own — a `<details>` whose `summary`
  IS the icon button; renaming is rare enough that it shouldn't occupy
  permanent page space, and it's specifically tied to the name it edits
  rather than living lower on the page as a generic "channel actions"
  control): renames by DISPLAY NAME, not a raw key — the user types "Minute
  Pastor", `channel_store.slugify` derives the key ("minute_pastor")
  automatically, and both `channel_display_name` and the config key are
  updated together. The first version of this only re-keyed the config
  and moved directories, silently leaving `channel_display_name`
  untouched — a real channel got renamed this way and kept showing its
  old display name everywhere despite the URL/key having changed; fixed
  by making display name the actual input and deriving the key from it,
  never the other way around. If the derived key happens to match the
  channel's current key (a purely cosmetic display-name edit, e.g. fixing
  capitalization), it's treated as a display-name-only update — no
  re-keying, no directory moves, no collision check against itself.
  Otherwise it moves everything on disk that's built directly from the
  key string: `channels/<key>/` (covers both `logo/` and `merch/` in one
  move, since `logo_gen.py`'s `_logo_dir` and `merch_assets.py`'s
  `merch_dir` both derive that path from the key at call time — no code
  changes needed in either module, the directory move alone is
  sufficient) and `output/<key>/`, but ONLY the latter if `output_dir` is
  still the unmodified `output/<key>` default; a channel with a
  customized `output_dir` (it's a plain editable string field, not
  derived at runtime) is left untouched rather than guessing where to
  move it. Every check (derived key non-empty, uniqueness, target
  directories not already occupied) runs before anything is written or
  moved, so a rejected rename never leaves partial state. Not handled:
  renaming a channel while a generation job is in flight for it
  (`webapp/jobs.py`'s single-job model) — accepted as an edge case for a
  local single-user tool. Re-keying itself has to rebuild the raw dict via
  `{(new_key if k == old_key else k): v for k, v in raw.items()}` rather
  than the obvious `raw[new_key] = raw.pop(old_key)` — a pop+reinsert
  always re-appends at the END of a Python dict, which is exactly what
  `channels.json`'s key order drives (see "Channel sections" below), so
  the naive version silently sent every renamed channel to the bottom of
  the home page — a real regression a user hit directly.
- **Channel sections and lifecycle** (`webapp/app.py`'s `CHANNEL_SECTIONS`,
  `_section_for()`, `index()`): channels are grouped into four collapsible
  sections on the home page — Live and Setting up open by default, Future
  ideas and Archived closed. Only **archived** is an actual stored field
  (`config/channels.py`'s `DEFAULT_ARCHIVED = False`) — live/setup/future
  are COMPUTED at display time from real state, never hand-set: live
  needs the launch checklist complete AND at least one video actually
  *published* (`gallery.video_state_counts`'s `"published"` count,
  stricter than the checklist's own "created a video" item), setup is
  any checklist
  progress at all, future is none. This replaced an earlier manual
  `status` dropdown per card — moving a channel between Live/Setup/Future
  was busywork for something that should just follow from what's
  actually true; only Archive/Unarchive stayed manual (a channel doesn't
  "flop" its way there on its own), and moved to the settings page's
  Danger zone (see below) since it's a rare, deliberate action, not
  something to expose on every card. `_build_checklist()` (the launch
  checklist's one definition, used by both `index()` — just the
  remaining-count, for every channel — and `channel_dashboard()` — the
  full labeled list) keeps the two pages from ever disagreeing about
  what's actually done. Once the checklist's complete but nothing's
  published yet, the dashboard shows a plain sentence instead of a
  button — going live isn't a click anymore, it happens the moment a
  video is published from the gallery.
- **Channel ordering / drag-reorder**: display order within a section is
  just `channels.json`'s own key order filtered into that section —
  Python dicts (and `json.dump`/`load`) already preserve insertion order,
  so no separate numeric order field was needed, only
  `channel_store.reorder_channels(ordered_keys)` (puts the given keys
  first in that order, leaves every other key's relative position alone
  — sufficient since display always re-filters into sections anyway, so
  interleaving between different sections' keys in the raw file is never
  visible). Dragging is off by default behind a "Reorder" toggle button
  (`app.js`'s `toggleReorderMode`, a hand-rolled six-dot grip icon
  matching every other icon in this app) so a stray drag can't silently
  reorder channels; native HTML5 drag-and-drop, with `_closestCard`
  comparing the cursor against every sibling card's center point (not
  just Y position) since `.channel-grid` is a multi-column CSS grid, not
  a vertical list — always within one section's grid only, cross-section
  moves are never a drag, that's what Archive/Unarchive and the
  automatic live/setup/future computation are for.
- **Archive / Delete** (`channel_store.delete_channel`, settings page's
  "Danger zone"): two deliberately DIFFERENT confirmation mechanisms, not
  the same dialog twice — Archive is reversible and low-stakes (a plain
  form with `onsubmit="return confirm(...)"`); Delete is real, permanent
  data loss (config entry + the ENTIRE `output/<key>/` and
  `channels/<key>/` trees — every generated video, logo, merch photo) so
  it gets its own confirmation PAGE (`delete_channel_confirm.html`)
  requiring you to type the channel's key before the submit button even
  enables (client-side for immediate feedback, but the POST handler
  re-validates `confirm_key == key` server-side too — the disabled
  attribute alone is never trusted). Before deleting anything,
  `delete_channel()` writes a zip backup to
  `deleted_channels/<key>_<timestamp>.zip` (stdlib `zipfile`, no new
  dependency) containing the raw config entry as `channel.json` plus both
  directories' full contents — real API cost went into that logo and
  those videos, so a misclick shouldn't be able to destroy it with
  actually no way back. `deleted_channels/` is gitignored alongside
  `output/`/`channels/`.
- **Video publish tracking** (`webapp/gallery.py`'s `{stem}_publish.json`
  sidecar, `/channels/<key>/videos/<path:relpath>`): finished videos had
  no record of whether or where they'd actually been posted. Each video
  gets a sidecar JSON — same naming shape and directory as the
  `{stem}_meta.txt` sidecar `main.py` already writes — holding
  `youtube_url`/`tiktok_url`/`instagram_url` plus `published_at`, an ISO
  timestamp stamped the moment the video FIRST goes from no links to any
  link set (later edits to an already-published video don't reset it;
  clearing every link back out clears it too) — genuinely different from
  the video file's own mtime (when it was rendered, not when it went
  out), which is what "time since published" on the home page's Live
  section actually needs. A video counts as **published** iff any link
  is set, derived rather than a separate stored flag (same idiom
  `config.channels.resolve_active_ctas` already uses for monetization
  CTAs — a real URL's presence IS the source of truth, so there's no
  boolean that could drift out of sync with the actual links). The
  Gallery page splits into Unpublished/Published/**Discarded** sections
  (Discarded new — see below), each card now a cropped thumbnail
  (`gallery.get_or_create_thumbnail` — one `moviepy.VideoFileClip.
  save_frame` call, cached as a `{stem}_thumb.jpg` sidecar the first time
  it's requested rather than regenerated on every gallery load, served
  via its own route so the gallery listing itself stays cheap) + title
  (the filename slug with underscores swapped for spaces — `main.py`'s
  filenames are already sensible, no separate title field needed) + a
  publish/creation date, no inline video player and no script text (that
  clutter belonged on the video's own page, not a list view). Published
  cards are one plain `<a>` straight to `video_detail`; Unpublished and
  Discarded cards are a `<div>` with a stretched-link `<a class="card-
  link-overlay">` sibling instead (same pattern as the home page's
  channel cards, below) since they each need a second independently-
  clickable control on top — the multi-select checkbox and the Restore
  button respectively — which can't live nested inside a single wrapping
  `<a>`. `video_detail.html` itself is two columns: a scrollable info
  panel (script, dates, the publish-links
  form) on the left, and the actual video on the right in a `position:
  sticky` column capped at `max-height: 80vh` so it can't blow out past a
  laptop screen regardless of aspect ratio — reading and watching can
  happen at the same time. Platform links render as `.btn.btn-ghost`
  pills at the top once published (text-label, matching every other
  external link in this app rather than inventing brand-logo icon
  buttons); unpublished, a "Publish video" button jumps down to the same
  links form instead.
- **Discard workflow**: a generated video that just isn't good enough to
  publish needed somewhere to go besides sitting in Unpublished forever
  or being deleted outright (losing the real generation cost for no
  reason if it turns out to be usable after all). The publish sidecar
  gains a `discarded` bool (`gallery.set_discarded`, preserves whatever
  links/`published_at` are already there — discarding doesn't touch
  publish state, restoring doesn't invent any); `gallery.
  video_state_counts(output_dir)` replaced separate `count_videos`/
  `count_published_videos` calls with ONE `rglob` pass reading each
  sidecar once (`{"total", "active" (= total - discarded), "published",
  "unpublished", "discarded"}`) since the home page now wants several of
  these numbers per channel on every load — `active` is what "video
  count"/the checklist's "created a video" item mean now, a discarded
  take was never a real deliverable. Discarding is one mechanism for
  both a single bad take and true bulk cleanup: the gallery's Unpublished
  section has a "Select" toggle (off by default, same interaction
  pattern as the home page's "Reorder" toggle) that turns each card's
  link-overlay click into a selection toggle instead of navigation
  (`app.js`'s `gallerySelectMode`/`selectedRelpaths`), revealing a
  "Discard selected (N)" button that POSTs the whole relpath list to
  `POST /channels/<key>/videos/discard` in one call — no separate
  single-video discard route to keep in sync with the bulk one. Restore
  is the safety net (same instinct as Archive/Unarchive) — a plain
  single-video `POST .../restore`, available both on a Discarded card and
  on that video's own detail page.
- **Parallel video generation** (`webapp/jobs.py`): generation is slow
  (minutes, multi-stage), so triggering one and walking away needed to
  actually work — which meant fixing the real reason only one job could
  ever run at a time. The old design captured a job's output by
  temporarily swapping `sys.stdout`/`stderr` process-wide
  (`contextlib.redirect_stdout`) for the job's duration — fine for
  exactly one job, actively wrong for two, since `sys.stdout` is one
  global object every thread's `print()` reads, not something each
  thread gets its own copy of; two concurrent jobs would interleave and
  corrupt each other's captured logs. Fixed with a **thread-local
  dispatch stream** instead of swapping anything per-job: a single
  `_DispatchStream` is installed ONCE as the real `sys.stdout`/`stderr`
  (idempotent — `start_job` only installs it if it isn't already there).
  Each job thread stamps its own job id into `threading.local()` the
  moment it starts (`_run_job`); the dispatcher's `write()` reads THAT to
  route into that job's own buffer, falling back to the real original
  stream for anything running outside a tracked job thread (the Flask
  main thread, etc). Verified live: two jobs started back to back for
  different channels, each printing/reporting progress on its own
  timer, produced completely isolated captured logs with zero cross-
  contamination — the actual constraint the old single-job design was
  built around no longer applies. `start_job`'s "already running" check
  is now per-channel (`get_running_job_for_channel`), not global — a
  different channel can start a job while another's still running, the
  SAME channel still can't run two at once. `current_progress` (moviepy's
  tqdm encode line) gets a small regex (`r"(\d{1,3})\s*%"`) pulled into a
  `progress_percent` field on the job dict — `None` whenever the current
  line doesn't carry one (most pipeline stages just print status text,
  only the final encode step reports a real percentage).
- **Intra-job parallelism, video-page reuse, and a real stage tracker**:
  three real problems with actually using the generate flow — generation
  was slow beyond what a single unattended run needs to be, the finished
  video showed in an oversized unstyled inline `<video>` instead of the
  real per-video page, and the only progress signal was a scrolling wall
  of text. `tts_captions.py`'s `_synthesize` used to call ElevenLabs (+
  local Whisper verification) for each script segment ONE AT A TIME in a
  loop, even though each segment's synthesis is fully independent of the
  others — only the final stitching (offsets, fades, concatenation)
  genuinely needs order, since each segment's start time depends on the
  cumulative duration of everything before it. Same shape in
  `footage_library.py`'s `_auto_fetch_and_add`: every candidate stock-
  footage URL was downloaded-then-normalized ONE AT A TIME, though one
  clip's download+normalize doesn't depend on any other clip. Both now
  run their slow, independent part concurrently and only the
  correctness-sensitive part sequentially afterward (`_synthesize`'s
  offset/fade bookkeeping; `_auto_fetch_and_add`'s
  `add_normalized_clip`, which reads and mutates the SHARED manifest —
  parallelizing that risks two threads both missing each other's
  just-added entry and creating duplicate clips from the same batch).
  `video_assemble.py`'s composition/encode step is deliberately NOT
  touched — it's inherently one sequential ffmpeg pass over one timeline
  (libx264 already threads the encode itself internally), with no
  independent-units-of-work shape the way "N API calls" or "N downloads"
  has.

  The correctness catch this ran into: the prior round's per-job output
  capture (above) keys off `threading.local()` set once per JOB thread —
  a job spawning its OWN worker threads (a `ThreadPoolExecutor` for
  parallel TTS/downloads) gets workers with their OWN empty
  `threading.local()`, so without fixing this, their `print()` calls
  would silently leak onto the real stdout instead of the job's visible
  log. Fixed by extracting the thread-local tracking into a new shared
  module, **`job_context.py`** (project root, not `webapp/` — so plain
  CLI usage of the pipeline never needs to import Flask). Its
  `parallel_map(fn, items, max_workers=8)` captures the CALLING thread's
  job id, propagates it into each spawned worker before running `fn`,
  and returns results in the SAME ORDER as `items` (via `pool.map`, not
  `as_completed`) — not completion order — so callers can stitch results
  back together positionally, which is exactly what `_synthesize` needs
  for segment offsets. `webapp/jobs.py` was refactored to use this SAME
  module instead of its own private `_THREAD_STATE`, so there's one
  source of truth for "which job is the current thread working on."
  Verified live: two jobs' worker-thread output stayed in completely
  separate captured logs with zero cross-contamination even though the
  worker lines themselves completed out of order (proving real
  concurrency), while `parallel_map`'s returned results still matched
  input order exactly.

  The finished-video view now redirects to the real page instead of
  showing a second, worse one: `create_video.html`'s bare `#job-result`
  block is gone; `app.js`'s `pollJob`, on `job.status === "done"`, does
  `window.location.href = \`/channels/${job.channel_key}/videos/${job.result_path_rel}\``
  — the exact same `video_detail` route (sized player, sticky layout)
  the gallery already links to, no second video-display implementation
  to keep in sync.

  The progress wall-of-text is now a 5-card **stage tracker** (Script /
  Voiceover / Footage / Assembling / Finishing) above a collapsed-by-
  default `<details>` holding the full log — piggybacking on print
  statements the pipeline ALREADY makes (`main.py`'s `[1/4]`..`[4/4]`
  headers, `video_assemble.py`'s own `"  [video] matching footage"`/
  `"  [video] rendering video"` lines) rather than adding new
  instrumentation. `webapp/jobs.py`'s `_JobCaptureStream._append_log`
  matches each completed line against an ordered `_STAGE_MARKERS` list
  and sets `job["stage"] = max(job.get("stage", 0), matched_index)` —
  monotonic, so an unrelated line in between two markers never moves it
  backward; `stage`/`stage_total` ride along in `/api/jobs/<id>`'s
  existing JSON for free (`api_job` already spreads the whole job dict).
  Each stage card is pending (dim) / active (accent-colored + a CSS
  `@keyframes` pulse-ring on the icon, conveying "actively working"
  without a GIF) / done (checkmark) — visually the same connecting-line
  language as the setup wizard's `.wizard-step-dot`/`.wizard-step-line`,
  so it reads as consistent with the rest of the app. The Assembling
  card additionally reuses the existing `.job-progress-bar` component
  (built for home-page cards) once a real `progress_percent` is
  available — indeterminate fill before that, since only the final
  encode step reports a real percentage.
- **Global job queue, granular progress, and never-silently-hang polling**:
  a real production incident drove this round — an in-flight job's dev
  server process got killed and restarted (during unrelated verification
  work), which wiped its in-memory `_JOBS` state; the browser kept
  polling the now-nonexistent job id, got `404` every second, and
  `pollJob`'s old code did `if (!res.ok) return;` — silently doing
  nothing forever, no error shown, indistinguishable from a genuinely
  stuck job. `pollJob` now treats a `404` as definitive (the job is gone,
  never worth retrying) and shows an error banner (`#job-banner`)
  immediately; a network error or non-2xx gets a few retries first
  (`MAX_POLL_FAILURES`) in case it's a momentary blip, then also banners
  instead of hanging. The home page's per-card poller
  (`initHomeJobPolling`) got the same `404` → `location.reload()` fix.
  All the pipeline's real HTTP calls (ElevenLabs, Pexels, Pixabay) already
  had `timeout=` set, so a hung socket wasn't the mechanism here — this
  was purely the frontend silently swallowing a failed poll.

  **Jobs now queue instead of running across channels in parallel.**
  Previously different channels' jobs ran fully concurrently — but each
  job already fans out several parallel ElevenLabs calls and stock-
  footage downloads internally (see below), so two channels generating
  at once multiplies that fan-out and risks hammering the same external
  APIs harder than intended. `webapp/jobs.py` now runs only ONE job at a
  time, globally: `start_job` either starts a job immediately (nothing
  else running) or gives it `status: "queued"` and appends it to `_QUEUE`
  (FIFO); `_advance_queue`, called from `_run_job`'s `finally` block,
  pops and starts the next queued job the moment the running one finishes
  (done or error). A channel still can't queue a second job behind its
  own first one. `get_running_job_for_channel`/`list_active_jobs`/
  `get_job` were broadened from `status == "running"` to `status in
  ("running", "queued")` so queued jobs are visible everywhere a running
  one used to be (resuming the create-video page while queued, the home
  page's per-card state) — each also gets a computed `queue_position`
  (1-indexed position in `_QUEUE`) for "position 2 in the queue" copy.
  `create_video.html` shows a "Queued…" heading + note instead of
  "Generating…" while `status == "queued"`; the home page's progress bar
  renders dimmed and empty (`.job-progress-bar-queued`, explicit
  `width: 0%` — the first version left the fill with no width at all,
  which defaults a block-level div to 100%, i.e. looked exactly like a
  FINISHED bar for a job that hadn't started; caught by a Flask-test-
  client render check before it shipped). No app.py changes were needed
  for this — `_channel_progress`'s `can_generate` already keyed off
  `active_job is None`, so broadening what counts as "active" was
  sufficient to make `generate-all` correctly queue every eligible
  channel instead of skipping all but one.

  **A granular "Details" panel** sits between the 5-card stage tracker
  and the collapsed raw log — more specific than "Voiceover is active"
  but far less noisy than the full text dump. Fed by a new structured
  side-channel through `job_context.py`: `report_detail(section,
  item_index, patch)` looks up the calling thread's job id and, if
  `webapp/jobs.py` has registered itself as the sink (`set_detail_sink`,
  at import time — a plain CLI run never imports `webapp.jobs`, so this
  stays a safe no-op there, same pattern as `parallel_map`), merges
  `patch` into `job["detail"][section]` (`item_index=None`) or
  `job["detail"][section]["items"][item_index]` (growing the list as
  needed) under `webapp/jobs.py`'s own `_LOCK` — safe to call from
  several `parallel_map` worker threads at once. `tts_captions.py`'s
  `_synth_one` reports each segment's preview text and
  pending/active/done/error status; `footage_library.py` reports the
  **exact** total shot count the moment it's known
  (`pick_clips_for_shots` already computed `sum(shot_counts)` for its own
  log line — now also reported as `detail.footage.total_shots`) and,
  once a fetch round starts, the **exact** number of download calls about
  to be made (`len(candidates)`, gathered from every query's search
  results before any download starts) plus a per-clip row with two
  independent statuses — `status_download` (the raw fetch) and
  `status_process` (normalize's center-crop + the perceptual-duplicate
  check + the Claude vision describe call + the manifest write, lumped
  together since visually they're one "processing" step even though
  normalize runs in the parallel phase and the rest runs in the
  sequential phase after). The frontend (`updateDetailPanel` in
  `app.js`) redraws this from scratch every poll tick — cheap at this
  size — as a voiceover checklist and a scrollable "tower" of clip rows,
  each with two small status dots (pending/active/done/error, `.detail-
  dot`), reusing the stage tracker's own pulse-ring animation for
  "active" so the whole page reads as one visual language.

  **The "batching" the user could see in the download step turned out to
  be two separate causes, not one.** First, `job_context.parallel_map`'s
  default `max_workers=8` (sized for generic use, not specifically for
  network-bound work) meant any round with more than 8 candidate clips
  visibly finished in groups of 8 — `footage_library.py`'s fetch call now
  passes an explicit `FETCH_MAX_WORKERS = 16`, wide enough to matter for
  I/O-bound downloads while still bounded (an unbounded burst risks
  tripping Pexels'/Pixabay's own free-tier rate limiting, which would
  surface as failures, not speed). Second, and the bigger effect:
  `pick_clips_for_shots`'s shortfall loop used to call
  `_auto_fetch_and_add` ONCE PER SEGMENT that needed more footage — each
  call already parallelized its OWN downloads, but two segments both
  needing footage meant two full sequential search-then-download round-
  trips, which is what actually looked like hard batching from outside.
  Fixed by collecting every shortfalled segment's search queries into ONE
  combined list and making a SINGLE `_auto_fetch_and_add` call per fetch-
  and-recheck round — safe because the next matching call re-scores the
  WHOLE library against every segment fresh regardless of which
  segment's shortfall originally triggered which query, so there was
  never a real reason to keep the fetches segment-scoped.

  **`MATCH_CONFIDENCE_THRESHOLD` lowered from 7 to 6** (`footage_
  library.py`) — real runs showed it behaving as "assume nothing is
  relevant," triggering far more auto-fetch/fallback than the library's
  actual coverage justified. `_build_prompt`'s scoring rubric was edited
  to match rather than just lowering the code-side cutoff in isolation:
  a new explicit "6" band ("a real depiction of the specific subject, but
  weaker/more incidental than 7-8 — a genuine pass, just not a generous
  one") replaces the old undefined gap where 6 fell inside a band
  explicitly labeled a MISS — keeping what the model is told consistent
  with what the code actually accepts, rather than quietly overruling the
  prompt's own rubric from outside it. Bands 1-5 are still an explicit
  miss, so this is deliberately a small lean, not a loosening of the bar.
- **TTS parallelization vs. ElevenLabs rate limits**: parallelizing per-
  segment synthesis (above) surfaced a real regression — several segments
  now hit ElevenLabs at the same instant, and a `429 Too Many Requests`
  used to propagate straight through `response.raise_for_status()` and
  kill the whole video generation on the FIRST occurrence, since
  `_tts_segment`'s existing retry loop (`max_attempts`) only covers
  synthesis-quality problems (a garbled result, a transcript mismatch),
  never the request itself failing to complete. Fixed with two
  independent changes: `tts_captions.py`'s `_post_with_backoff` now wraps
  the actual POST, retrying a `429` or any `5xx` with exponential backoff
  (`TTS_RATE_LIMIT_MAX_RETRIES = 5`, `2s → 4s → 8s → 16s → 32s`,
  honoring a `Retry-After` header when ElevenLabs sends one) before
  finally raising — this is the real safety net and matters regardless of
  concurrency level, since even sequential requests can hit a transient
  429 under load. Separately, `_synthesize`'s `job_context.parallel_map`
  call now passes an explicit `TTS_MAX_WORKERS = 3` instead of the
  generic default of 8 — ElevenLabs' concurrent-request limit is tied to
  account tier and can be as low as 2-3 on lower tiers, so a lower cap
  makes tripping the limit at all less likely in the first place, while
  still meaningfully parallelizing most videos' handful of segments.
- **Job persistence, checkpointing, and retry — "why isn't this
  recoverable"**: a real incident (a job died when its process was
  restarted mid-generation, then the browser polled a now-nonexistent id
  forever with no error) exposed two separate problems: the job registry
  was purely in-memory, so a restart didn't just interrupt one video, it
  erased all record that generation had ever been attempted; and even
  setting that aside, a fresh retry re-paid for every stage from scratch
  — including the ones (script, voiceover) that had already completed
  and cost real API calls. Both are fixed now, not just papered over with
  a friendlier error message.

  **Persistence**: `job_context.py` gained a `job_state/<job_id>/`
  checkpoint directory per job (project root, gitignored like `output/`)
  holding `job.json` (the full job record) plus per-stage checkpoint
  files. `webapp/jobs.py`'s `_persist(job_id)` writes `job.json` after
  every meaningful state change (log line, detail update, status/stage
  change) — always called OUTSIDE any `_LOCK` block it's nested in
  (`_persist` briefly takes its own lock just to snapshot the dict, and
  `threading.Lock` isn't reentrant, so nesting would deadlock).
  `load_persisted_jobs()`, called once at startup
  (`if __name__ == "__main__":` in `webapp/app.py`, not at import time,
  so test scripts importing `webapp.app` don't have this side effect),
  reloads every `job.json` into `_JOBS`. A job whose persisted status was
  still `"running"` or `"queued"` — meaning the process that would have
  finished it is gone — becomes a NEW status, `"interrupted"` (never
  silently resumed), with a specific message built from `job["stage"]`
  via `_STAGE_LABELS` ("...interrupted while matching footage", not a
  generic "something went wrong").

  **Checkpointing**: the three genuinely expensive stages each check for
  a prior checkpoint before doing their real work, and save one after —
  `main.py`'s `generate_video_from_seed` for the script (a real Claude
  call) AND the output paths together (`stem`/`out_dir`, under
  `"progress"` — checkpointing the script alone isn't enough, since a
  freshly recomputed stem would orphan the already-written audio/video
  files from the interrupted attempt); `tts_captions.py`'s `_synthesize`
  for the finished voiceover (copies the actual mp3 into the checkpoint
  dir, since decoding a saved copy is more reliable than trying to
  serialize raw sample arrays — same reasoning as the rest of this file's
  audio handling); `footage_library.py`'s `pick_clips_for_shots` for the
  matched clip list (only reused if `shot_counts` matches exactly AND
  every referenced clip still exists in the library — a stale or
  invalidated checkpoint is silently ignored rather than trusted). All
  three checkpoint functions (`job_context.save_json_checkpoint`/
  `load_json_checkpoint`/`checkpoint_artifact_path`) key off
  `job_context.get_job_id()` implicitly, so no function signature needed
  to change to thread a job id through — they're no-ops outside a job
  (plain CLI use), consistent with how `report_detail`/`parallel_map`
  already worked. A SUCCESSFUL job's checkpoints are deleted
  (`job_context.clear_checkpoints`, called right after the final
  `status="done"` update) — nothing in them is needed once the real
  output exists; a failed/interrupted job keeps its checkpoints
  specifically so a retry has something to resume from.

  **Retry**: `webapp/jobs.py`'s `retry_job(job_id)` re-runs an
  `"error"`/`"interrupted"` job under the SAME job id (unlike `start_job`,
  which always mints a fresh one) — checkpoints are keyed by job id, so
  reusing it is what makes the pipeline's checkpoint checks actually find
  anything. `POST /api/jobs/<id>/retry`; the create-video page's
  `#job-banner` grows a Retry button (`retryCurrentJob()` in `app.js`)
  whenever a job is in a retryable state. Since nothing else exposes a
  job id, `get_latest_terminal_job_for_channel` + a new
  `GET /api/channels/<key>/last-failed-job` route lets the page
  proactively surface "your last attempt was interrupted while X — retry?"
  on load (`resumeRunningJob`, extended past its original running/queued
  check) even though the user never navigated there with a job id in
  hand.

  **Friendly errors**: `job["error"]` used to be a raw
  `traceback.format_exc()` dumped straight into the log — exactly the
  "404 from some server" technical noise a user without this code open
  shouldn't have to parse. `_run_job` now calls `_friendly_error(exc)`
  to build a short, specific, plain-English `job["error"]` (shown
  prominently in the banner) and keeps the real traceback in a separate
  `job["error_traceback"]` field (only surfaced in the collapsed log, for
  actual debugging) — a 429 becomes "the voice service (ElevenLabs) is
  temporarily rate-limiting requests, this usually resolves on its own",
  a connection failure becomes "check your internet connection", and
  only a genuinely-unrecognized exception falls back to naming its
  Python type. `_guess_service` reads the failed request's URL to name
  which external service was involved, since "an external service failed"
  alone isn't specific enough to act on.

  Verified end-to-end (not just each piece in isolation): a fabricated
  "crashed mid-footage-matching" job, persisted to disk, survives having
  its in-memory state wiped (simulating a real restart), reloads as
  `"interrupted"` with the correct stage-specific message, and a
  `retry_job` call on it reuses the on-disk checkpoint and completes —
  proving the checkpoint directory genuinely survives the full cycle, not
  just that each function individually returns the right shape.
- **Footage matching: still too strict, and one big fetch round instead
  of many small ones**: two follow-up problems from real use after the
  round above. First, `MATCH_CONFIDENCE_THRESHOLD` (7, then 6) was STILL
  behaving as "almost nothing matches" — lowered again to 5, with
  `_build_prompt`'s rubric edited alongside it (a new "5" band describing
  a real-but-indirect connection to the subject, e.g. rain footage for a
  segment about a storm) so the threshold and what the model is actually
  told to score against stay in sync; bands 1-4 are still an explicit
  MISS, so this is a real bar, not "anything goes." Second, and the
  bigger UX problem: combining every shortfalled segment's queries into
  ONE fetch call per round (a prior round's fix for sequential
  "batching") had an unintended side effect — a video with several weak
  segments could queue up dozens of simultaneous downloads at once (a
  real run hit 36), far more than is a reasonable single round of work or
  fits comfortably in the UI. `_auto_fetch_and_add` now caps a round at
  `MAX_CANDIDATES_PER_ROUND = 12`, selected via ROUND-ROBIN across
  queries (one candidate from each query, then a second pass, etc.) so
  the cap doesn't just let whichever segment's queries were searched
  first eat the entire round — verified with a unit test that an 18-query
  scenario spreads one clip per query in the first pass, and a 2-query
  scenario still splits evenly (6/6) across passes. The existing
  fetch-and-recheck loop (`MAX_FETCH_ATTEMPTS`) already means a capped
  round that's still short just tries again with different search terms
  next round, rather than needing to fetch everything in one shot.
- **Footage progress: a real multi-step bar per clip, not two flashing
  dots**: `status_download`/`status_process` (two coarse booleans, both
  rendered as the same gold dot whether active or done — indistinguishable
  at a glance, which is exactly what was reported) are replaced by a
  single ordered `step` field per clip
  (`"queued" → "downloading" → "normalizing" → "analyzing" → "done"`,
  or `"failed"`) reported at each real transition in
  `_auto_fetch_and_add`/`_fetch_one` — "analyzing" covers the perceptual-
  duplicate check + Claude vision describe call + manifest write (the
  sequential, manifest-mutating phase), matching what's actually
  happening instead of a vague "processing." `app.js`'s
  `footageStepInfo(step)` maps a step to a fill percentage
  (`index / (steps.length - 1)`) and a text label, rendered as a real
  `.job-progress-bar`-style bar per clip instead of dots. Done is
  `var(--success)` (new token, green) and failed is `var(--danger)`
  (red) — previously both active and done used the same accent gold,
  which was the actual "why doesn't this go green" complaint; a failed
  clip's row is labeled "Failed" in red with explanatory copy above the
  tower ("a failed clip is skipped automatically, nothing to do") since
  a single bad download is expected and handled, not something the user
  needs to act on. The tower's `max-height` grew from 260px to 420px to
  comfortably fit a full capped round (12 rows) without feeling cramped.
  Separately, `updateDetailPanel`'s full `innerHTML` replace every poll
  tick was resetting the tower's scroll position to the top on every
  tick — reported as "scrolling down jumps back to the top" — fixed by
  capturing `.detail-tower`'s `scrollTop` before the replace and
  restoring it on the newly-created element after; verified in the
  browser that a manually-scrolled position survives a re-render even
  though the DOM node itself is provably a different object each time
  (`innerHTML` always fully replaces, never patches).
- **Home page: progress bars, quick-generate, generate-all**: each
  channel card became a **stretched link** (`.card-link-overlay`, an
  absolutely-positioned `<a>` covering the whole card as a SIBLING of the
  visible content, not a wrapper around it) instead of the card itself
  being one `<a>` — needed the moment the card had to host a second real
  interactive element (the Generate button, a progress bar), which can't
  nest inside a single wrapping link (invalid HTML, and clicking the
  button would also fire the link); any element that needs to stay
  independently clickable on top of the overlay just needs `position:
  relative` + a higher `z-index` (`.card-action`, reused by the gallery's
  Restore button too). A card shows exactly one of: a **progress bar**
  (`.job-progress-bar`, real width once `progress_percent` is known, an
  animated indeterminate fill while it's `None`) if
  `jobs.get_running_job_for_channel` finds one running — polled by ONE
  shared `setInterval` in `app.js` that walks every
  `.job-progress-bar[data-job-id]` on the page each tick (not one
  interval per card), and on that job finishing just does
  `location.reload()` (simplest correct way to reset the card AND pick up
  any section change); or a **"Generate video"** button, only for
  `status == 'live'` channels with zero unpublished videos and no job
  already running (`_channel_progress`'s `can_generate`, the single
  definition both the per-card check and "Generate all" use so they can
  never disagree) — calls `POST /channels/<key>/generate-now`
  (`main_module.fetch_candidate_seed` + `jobs.start_job` in one call,
  deliberately skipping `create_video.html`'s manual seed-preview step,
  which is useful when you're watching but pointless for something
  you're about to walk away from); or nothing. A toolbar "Generate all"
  button (`POST /api/channels/generate-all`) runs that same eligibility
  check across every channel and starts all the genuinely-eligible ones
  at once, returning which started and which were skipped and why.
  `create_video.html` also gained `GET /api/channels/<key>/current-job` +
  a small on-load check (`resumeRunningJob`) so navigating back to a
  channel's create-video page while its job is still running resumes the
  progress view instead of showing the idle "get a candidate" state —
  the job itself never stopped (it's a daemon thread independent of any
  request), only the page's earlier connection to it was lost by
  navigating away. **Not a goal**: surviving an actual server restart —
  job state is in-memory (`webapp/jobs.py`'s `_JOBS`), so restarting the
  dev process (an explicit action) still loses whatever was running, same
  as before this round.
- **Manual checklist override**: some launch-checklist steps (Patreon's
  signup flow, say) are genuinely annoying enough that "note I'm skipping
  this one" beats leaving it permanently unchecked forever. Every
  checklist item now has a stable id (`webapp/app.py`'s
  `CHECKLIST_ITEM_IDS`, independent of its label text) and can be toggled
  into `channel["manual_checklist_overrides"]`
  (`config/channels.py`'s `DEFAULT_MANUAL_CHECKLIST_OVERRIDES`, a plain
  list) via `POST /channels/<key>/checklist/<item_id>/toggle-manual`. An
  item in that list counts as done for section/progress purposes exactly
  like the real thing, but renders with a neutral "−" (`.todo-item.manual
  .todo-check`, overriding the accent checkmark by appearing later in the
  stylesheet at equal specificity) instead of a checkmark, so it stays
  visibly different from something actually completed — an "Unmark" link
  replaces "Fix →" for a manually-done item.
- **Channel logos** (`webapp/logo_gen.py`, `/channels/<key>/logo`): AI-
  generated via OpenAI's Images API (`gpt-image-1`, `n=CANDIDATE_COUNT` in
  one call — the reason OpenAI was picked over Recraft, which needs one
  call per image; Recraft's actual vector output would otherwise have
  been the better fit for merch-ready art; if that request gets 429'd by
  the account's per-minute image-generation quota — a real, observed
  limit — `_generate_images` falls back to batches of
  `MAX_IMAGES_PER_MINUTE` with a minute's wait between them). The user
  only edits a short "what's this channel about" fragment — the
  professional/no-text framing is a fixed template (`logo_gen.build_prompt`)
  they never see or edit directly. This channel isn't YouTube-exclusive
  (also posted to TikTok/Instagram), and the prompt used to say "YouTube
  channel" — a real generated batch came back with YouTube play-button
  imagery baked into the mark itself, so `PROMPT_TEMPLATE` now says
  "content creator's channel" and explicitly rules out platform/app/brand
  symbols, without naming any platform by name even in the negative
  instruction (naming a brand token at all, even to say "not this," can
  still bias a text-to-image model toward that brand's imagery).
  Candidates and merch variants deliberately use DIFFERENT prompt framing,
  not one "minimalist" style for everything: the primary candidates ask
  for a bold, detailed, colorful logo that reads well as a profile
  picture (early versions were coming back too minimalist to be
  impactful on their own). Cost is a real concern here (`gpt-image-1`
  isn't cheap — a real batch of 20 images cost ~$3), addressed two ways:
  `CANDIDATE_COUNT` is 5, not 10, and candidates generate at
  `IMAGE_QUALITY_CANDIDATES` ("medium" — good enough to pick a direction
  from) while the handful of merch variants use `IMAGE_QUALITY_FINAL`
  ("high" — worth it since there are only a few and they're the actual
  printable assets). Picking a candidate (`logo_gen.select_logo`) ONLY
  copies it to `logo.png` — no API calls. This used to also generate the
  merch variants automatically, which meant clicking a candidate silently
  kicked off 1-3 more slow paid requests with zero UI feedback,
  indistinguishable from the click having done nothing; merch-variant
  generation (`logo_gen.generate_merch_variants`) is now a separate,
  explicit action triggered from the setup wizard's `merch_logo` step,
  never called automatically. It also fixed a real correctness
  bug, not just a UX one: variants were originally generated via the
  **generations** endpoint from text alone (topic fragment + "redraw the
  same subject as...") — the model was never shown the actual chosen
  logo, so "the same subject" was an unfulfillable instruction and every
  variant came back as an unrelated fresh interpretation of the topic,
  not a restyle of the real logo. `generate_merch_variants` now uses
  OpenAI's **images/edits** endpoint instead (`_call_openai_image_edit`,
  multipart/form-data, unlike the JSON-only generations endpoint),
  passing the real `logo.png` bytes as the input image, so each variant
  is a genuine restyle of the specific chosen logo — and no longer needs
  the topic fragment at all, since the source image supplies the subject.
  One real edit call per `VARIANT_STYLES` entry, each a genuinely
  different minimalist treatment (currently line art, flat geometric,
  badge/emblem — not the same "make it minimal" style three times, so
  there's real stylistic choice for print), plus a "monochrome" variant
  derived **locally via Pillow** (grayscale + threshold to one ink color)
  from the flat-geometric variant specifically — its bold solid shapes
  threshold to a clean single color
  far better than the detailed primary logo would, and it costs no second
  API call since flattening to one print color is a deterministic
  transform, not a creative one. Stored under `channels/<key>/logo/`,
  parallel to `channels/<key>/merch/` — both live outside `output/`
  (brand assets, not finished videos) and outside `footage/` (not stock
  video). The channel list shows the logo if `channels/<key>/logo/
  logo.png` exists (a plain filesystem check, no config field needed —
  same pattern `webapp/gallery.py` already uses for videos) or a
  "Create logo" link into the generator otherwise.
- **Visual design**: a dark "studio" theme (`webapp/static/style.css`) —
  CSS custom-property design tokens (spacing scale, two surface tones,
  the same gold accent (`#FFD400`) already used in generated captions/
  outro cards, so the tool visually matches what it produces), card
  elevation with hover lift, hand-rolled inline SVG icons (no external
  icon font/CDN — stays local/dependency-free), real empty states, and a
  loading-spinner helper (`app.js`'s `withButtonLoading`) used everywhere
  a button kicks off an async call.

## Open/unsolved
- **Decided**: TTS engine is ElevenLabs (paid — replaced edge-tts, which
  was free but sounded robotic and had occasional streaming glitches
  traceable to it being a reverse-engineered wrapper around a free
  consumer feature, not a supported API). Gives native character-level
  timestamps via the `with-timestamps` endpoint — words are grouped from
  character alignment (punctuation stays attached automatically), no
  Whisper alignment step needed, same as the edge-tts-era design goal.
- **Fixed (root cause, not a retry)**: narration audio had a persistent,
  deterministic stutter — not an occasional ElevenLabs hiccup. Traced to
  `audio_utils.py` decoding synthesized mp3s via moviepy's
  `AudioFileClip`/`iter_chunks`, which streams a large clip through
  `FFMPEG_AudioReader.buffer_around`'s internal rolling buffer; that
  buffer's recentering logic has an off-by-one in how it recycles its old
  tail, duplicating one sample almost every time it recenters (confirmed
  by diffing moviepy's decode of a real narration file against a plain
  ffmpeg decode of the same file — they matched exactly up to a point,
  then moviepy's version had 1 extra sample, shifting everything after by
  one). Across a full track that's dozens of small insertions spaced every
  ~2 seconds — a real, 100%-reproducible defect in decoding our own
  output, invisible to retrying synthesis since the corruption never
  touched ElevenLabs' side. Fixed by replacing `read_soundarray` with
  `decode_audio_file` (`audio_utils.py`) — one direct linear ffmpeg
  subprocess call, no seeking/buffering to get wrong. Verified: two
  independent decodes of the same file are now bit-identical.
- **Decided**: on top of the fix above, every synthesized segment is also
  independently re-verified by transcribing the actual rendered audio with
  a local Whisper model (`faster-whisper`, `small.en`) and diffing it
  word-for-word against the intended text, retrying synthesis on a
  mismatch (`tts_captions.py`'s `_transcript_match_ratio`, wired into
  `_tts_segment`). This is a safety net for a different failure mode —
  ElevenLabs itself occasionally mis-speaking a word — not a substitute
  for fixing a deterministic bug in our own code; it only catches
  low-probability synthesis issues that are worth retrying, not a bug that
  reproduces every time no matter how many times you retry. Local rather
  than a cloud ASR API so this doesn't add a third paid vendor just for a
  QA check. Uses `small.en`, not `base.en` — the smaller model
  mis-transcribed uncommon proper nouns (heard "Aesop" as "Asop"), which
  matters a lot for a Bible/Shakespeare pipeline where
  names and citations are core content, not edge cases. Word comparison
  strips hyphens/apostrophes before splitting rather than treating them as
  separators, since Whisper sometimes hyphenates a compound word it's
  unsure of ("pangram" → "pan-gram"), which would otherwise look like two
  wrong words instead of zero. **Bug fixed**: the "Job"→"Jobe"
  pronunciation-override revert (`_revert_pronunciation_overrides`) did a
  case-sensitive `startswith("Jobe")` check, but the transcript-match
  path lowercases everything first — the revert silently never fired
  there, so a real live test confirmed Whisper "correcting" the respelled
  "Jobe" back to "Job" in its transcript would have read as a genuine
  mismatch and triggered a pointless retry (real ElevenLabs cost) on
  perfectly good audio. Now case-insensitive (case-preserving output);
  verified with live audio that match ratio is 1.0 for "Jobe, chapter 1,
  verse 8" even though Whisper's raw transcript says "Job chapter 1
  verse 8."
- **Decided**: footage-matching is one batched Claude call reasoning over
  natural-language descriptions (not tag overlap, not a separate embedding
  index — no new API key/service needed since Claude's already in the
  loop for script generation). This scales fine to tens/low-hundreds of
  clips (prompt size, cost); if the library grows into the thousands,
  revisit with real embeddings.
- **Decided**: the pipeline is format-agnostic (segments/citation contract,
  per-channel pacing/style config, pluggable static-corpus vs. topic-driven
  sourcing) — see "Format-agnostic architecture" above. Live-news-with-
  fact-checking is explicitly deferred, not forgotten — a different risk
  profile (editorial/factual liability) that deserves its own design pass
  once there's an actual concrete need for it.
- **Decided**: footage duplicate detection is perceptual-hash-based (mid-
  clip frame, average hash), checked before the vision-API describe call
  — see Footage library above. Catches the common case for free; won't
  catch a duplicate whose middle frame happens to differ (e.g. a very
  different camera position at that moment).
- Still open: similarity/embedding check on generated text to catch drift
  toward reworded-copy output over time — not built yet.
- Still open: cross-channel sameness at volume (structure/pacing/segment-
  count looking identical across channels) — worth a look once publishing
  at real frequency, not before. Per-channel pacing config helps here but
  doesn't fully solve it on its own.
