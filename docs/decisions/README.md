# Decision record

Append-only. Each entry says what was decided, why, and — where it
matters — what was tried first and didn't work. Entries are never edited
to stay current; when a decision is superseded, a later entry says so and
links back.

The counterpart to this is [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
which describes only what is true now. The split exists because the two
documents answer different questions and rot at different rates: a fact
about today's system goes stale the moment the system changes, while the
reason for a change stays true forever.

| # | Decision | Status |
|---|----------|--------|
| [001](001-elevenlabs-tts.md) | ElevenLabs for text-to-speech | Active |
| [002](002-audio-decoding.md) | Decode audio with a direct ffmpeg call | Active |
| [003](003-transcript-verification.md) | Verify every synthesized segment locally | Active |
| [004](004-semantic-footage-matching.md) | Match footage by meaning, not tags | Active |
| [005](005-perceptual-duplicate-detection.md) | Multi-frame perceptual duplicate detection | Active |
| [006](006-format-agnostic-pipeline.md) | Keep the pipeline format-agnostic | Active |
| [007](007-shortlist-before-matching.md) | Shortlist footage before the matching call | Active |
| [008](008-sqlite-clip-store.md) | SQLite for the clip library | Supersedes the JSON manifest |
| [009](009-render-plan.md) | A typed RenderPlan through the pipeline | Active |
| [010](010-logging-not-stdout-capture.md) | Logging instead of stdout capture | Supersedes the dispatch stream |
| [011](011-sparse-channel-config.md) | Sparse, validated channel config | Supersedes full-entry writes |
| [012](012-shot-briefs.md) | Shot briefs, and a rubric that scores editing | Supersedes 004's scoring bands |
| [013](013-failing-safely.md) | Failing safely | Active |
| [014](014-matching-precision.md) | Matching on what a clip is, not what is in it | Extends 012 |
| [015](015-library-storage.md) | Three copies of everything | Active |
| [016](016-caption-preview.md) | Showing the captions instead of describing them | Active |
| [017](017-youtube-upload.md) | Uploading to YouTube, and what that cannot mean | Active |
| [018](018-topic-curriculum.md) | A syllabus, not a bag of topics | Supersedes the random topic list |
| [019](019-channel-setup.md) | Creating a channel | Supersedes the single create form |
| [020](020-cards-and-backgrounds.md) | Title cards, and a picture behind them | Active |
| [021](021-elevenlabs-error-messages.md) | "Check your API key" was a guess, and usually the wrong one | Active |
| [022](022-style-tone-picker.md) | Selecting a voice instead of inventing one | Active |
| [023](023-script-studio.md) | Scripts as their own thing, ahead of any video | Active |
| [024](024-ordering-and-title-cards.md) | Ordering as policy, and two things the title card can say | Active |
| [025](025-voice-quota.md) | The voice allowance is the limit, so read it | Active |
| [026](026-originality-gate.md) | Check originality before the voiceover, and rewrite once | Active |
| [027](027-no-cache-on-footage-match.md) | The footage-match cache never hit | Reverses 007's caching |
