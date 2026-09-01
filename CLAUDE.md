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
  `step` ∈ socials → email → patreon → merch → amazon, Back/Next
  between them) links out to where each actually gets created (Outlook
  for a dedicated inbox, Patreon's creator signup, Printful/Spring for
  merch, Amazon Associates — the Amazon step's instructions explain the
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
  during the wizard's merch step) above its text if any have been
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
  new first step, `setup/socials` (ahead of monetization — a channel's
  social presence is the natural thing to set up before accounts that
  often depend on the channel already existing publicly), or via the
  settings form's own "Socials" fieldset — both write-paths use the same
  full-entry-vs-raw-mutation split described above.
- **Channel dashboard** (`/channels/<key>`, `webapp/templates/
  channel_dashboard.html`): a per-channel home page that used to not
  exist — previously the only per-channel destinations were reached
  individually from the global channel-list card (Settings/Gallery/Create
  Video/etc.), with no single place showing overall channel state. Shows:
  video count + most-recent-video date (`gallery.count_videos` +
  the new `gallery.latest_video_mtime`, the latter added specifically so
  this didn't need to call `list_videos` — which builds full metadata for
  every video, including reading each paired `_meta.txt` — just to read
  one timestamp); a **todo checklist** built fresh on every load from
  real state (no stored "is this done" flag anywhere — `logo_gen.has_logo`/
  `has_merch_variants`, each `socials`/`monetization` field's presence,
  video count), each unchecked item linking straight to where it gets
  fixed; and a "Your links" card surfacing whichever socials/monetization
  URLs are actually set, as external link buttons. Every other per-channel
  page's back-link now points here instead of straight to Settings or the
  global channel list — index → dashboard → {settings, logo, gallery,
  create video, setup wizard} is the intended navigation shape now, with
  the global channel list's card actions kept as direct shortcuts for
  anyone who wants to skip the dashboard.
- **Channel rename** (`channel_store.rename_channel`,
  `/channels/<key>/rename` on the dashboard): a channel's `key` used to be
  permanent once created — this matters because the pipeline started
  naming test/early channels loosely before their real branding was
  settled. Re-keys the `channels.json` entry AND moves everything on disk
  that's built directly from the key string: `channels/<key>/` (covers
  both `logo/` and `merch/` in one move, since `logo_gen.py`'s `_logo_dir`
  and `merch_assets.py`'s `merch_dir` both derive that path from the key
  at call time — no code changes needed in either module, the directory
  move alone is sufficient) and `output/<key>/`, but ONLY the latter if
  `output_dir` is still the unmodified `output/<key>` default; a channel
  with a customized `output_dir` (it's a plain editable string field, not
  derived at runtime) is left untouched rather than guessing where to
  move it. Every check (new key format/uniqueness, target directories not
  already occupied) runs before anything is written or moved, so a
  rejected rename never leaves partial state. Not handled: renaming a
  channel while a generation job is in flight for it (`webapp/jobs.py`'s
  single-job model) — accepted as an edge case for a local single-user
  tool.
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
  explicit action triggered from the merch step of the monetization
  wizard, never called automatically. It also fixed a real correctness
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
