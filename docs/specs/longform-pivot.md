# Long-form pivot

*Plan of 6 Oct 2026. The readable version, with the cost model, is the
artifact <https://claude.ai/artifact/4pTMj19UuRP7y6ThQ9NQCu>. This file
is the working copy later sessions build from. Decisions made while
carrying it out go in `docs/decisions/` as usual.*

## The direction

Shorts are no longer the earner: from 1 Feb 2027 Shorts revenue sharing
needs 10M Shorts views per 90 days, and new Partner Programme applicants
need 8,000 watch hours (Shorts views don't count). The project moves to
long-form widescreen videos, 10-15 minutes, 1-2 a week per channel.

**Minute Pastor and Pub Quiz Buzz are maintained in their current
state**: same settings, schedules and output; bug fixes and credential
upkeep only. Shared code (tts, llm, assemble, sound, publishing) changes
only additively, behind defaults that leave their videos unchanged.

## Measured baseline (6 Oct)

- Spend through the app: $61.70 (Claude $38.77, of which >$21 stocking
  the question bank; ElevenLabs $18.01 at list price, prepaid; OpenAI
  images $4.92). 78 videos made, 8 published, 3 subscribers per live
  channel.
- Voice: 0.2 credits a character (`cache/voice_credit_ratio.json`).
  Minute Pastor's median short is 574 characters, Pub Quiz Buzz's 1,586.
  The two live channels use about 12,500 of Starter's 30,000 credits a
  month.
- Stills: GPT Image 2.5 Flare keyframes with references cost $0.0245
  each (21 measured). Already cheaper than Seedream 5.0 Lite ($0.035) or
  Nano Banana 2 ($0.067).
- Footage matching: $0.045 a call. The library (562 clips, 7.9 GB) is
  all portrait; none of it fills a widescreen frame.
- The documentary format (decision 074) has never run end to end.

## The recipe: an illustrated documentary

About **$1.90 cash per 12-minute video** plus **~2,330 voice credits**
(2,090 for the narration at 870 characters a minute, 240 for two
teasers):

| Part | Cash |
|---|---|
| Research, outline, script by chapter (cached), fact-check, checks; Sonnet 5 at batch prices, Haiku for checks | ~$0.45 |
| ~35 drawn stills, each filmed 2-3 times | ~$0.88 |
| Three thumbnails | ~$0.18 |
| Two teaser shorts | ~$0.40 |
| Motion cold open (optional, Phase 4) | +$1-2.50 |

Pictures follow a ladder, cheapest rung that fits each shot:
1. archival, public domain (Met, AIC built; add Wikimedia Commons,
   Library of Congress, Smithsonian Open Access), licence-filtered,
   attributed, vision-checked; real portraits where they exist;
2. compositor graphics: maps (Natural Earth), timelines, family trees,
   quote/statistic/document cards, diagrams;
3. drawn stills from the style sheet and cast sheets;
4. generated motion, cold open only, only on a channel that earned it.

Rejected as the main approach: stock footage plus narration (the pattern
YouTube's January 2026 wave targeted; B-roll only), generated video for
every shot ($36-58 per 12 minutes), hour-long sleep narrations (not now).
Second-channel candidate: compositor-only explainers (~$0.50 + packaging).

Voice stays on ElevenLabs (prepaid; a channel's voice can't change once
viewers know it). Creator (~$22/month, ~121k credits) once more than ~7
long films a month are wanted. Revisit cheaper TTS above ~30 a month.

## Quality bar

- First 30 s: concrete stakes, picture changes at least every 5 s, the
  question stated by 0:30.
- A cut every 4-8 s; no picture repeated in a film.
- Chapters every 2-3 minutes, each with a re-hook; marks in the
  description.
- Every claim traceable to the research sheet; no invented quotes.
- Voice verified; loudness -14 LUFS; music ducked.
- One style; no garbled text; people match their sheets.
- Thumbnail readable at ~160 px; title under ~60 characters.
- 1080p; 12 minutes or more; last 20 s clear for an end screen.

Policy defences: research per film with sources listed, each film's
structure different from the channel's others, 1-2 a week, the owner
decides packaging and outline, originality check and no-repeat rule
visible in Review, `containsSyntheticMedia` when a picture is realistic.

## Production line

0. Packaging (owner, 2 min): three title + thumbnail ideas; pick or drop.
1. Research (auto): cited fact sheet, cached per topic.
2. Outline (owner, 3 min).
3. Script (auto): by chapter, fact-checked, originality-checked.
4. Shot plan (auto): each scene 2-3 shots, ladder, per-video budget.
5. Pictures (auto): archival, graphics, stills, contact-sheet checks.
6. Voice (auto).
7. Film (auto): camera moves, inserts, music, chapters, SRT.
8. Final look (owner, 10 min): chapter strip; approve or send a chapter back.
9. Out (auto): scheduled upload, captions, thumbnail, playlist; teasers.
10. Learn (auto): retention per chapter, CTR at 7/28 days, into notes.

Stages 0, 1 and 4 are new; the rest extend decision 074. During Phase 1
every stage waits for approval, as 074 does now.

## Freeze or retire

- Frozen (bug fixes only): narrated shorts (Minute Pastor), quiz format,
  question bank, fact store, long quizzes (Pub Quiz Buzz), TikTok and
  Instagram posting, the shorts settings page and launch pipeline.
- ~~Retire `pipeline/scenes/` and `pipeline/templates/`~~ Kept (decision
  075): the audit found Pub Quiz Buzz's board and long quizzes need
  `scenes.render`, `scenes.art` and `templates.page/theme/tex`, and the
  compositor needs `scenes.render` and `scenes.props`. Only the
  per-segment scene and template features are unused; removing them can
  wait, now the frozen check makes it safe.
- Off by default: generated motion for whole videos.
- Archive (owner's OK): curiosity_leak, wrens_guide_to_witchcraft,
  shakespeare_lines, maths_demo.

## Phases

- **0. Protect the live channels. Built 6 Oct (decision 075).**
  `tests/frozen/` holds both channels to golden fingerprints of their
  real pipelines; tag `shorts-freeze-2026-10-06`; reachability measured
  (see above); spare voice keeps what documentaries in production need
  and never fills a documentary channel's slots with shorts; test
  channels archived. Owner's part is TASKS step 0.
- **1. One documentary end to end (weeks 1-2, ~$3).** Run History
  Unmystified through the five stages as built; fix what breaks; measure
  cash, credits, minutes per stage, render time, owner time.
- **2. Good and cheap (weeks 2-5).** In order: scenes as 2-3 shots and
  the shot ladder with a budget; compositor graphics kit; archival
  sources; research stage and fact-check; packaging first and three
  thumbnails; retention structure in script checks; upload extras
  (captions, thumbnail, playlist, publishAt, A/S flag); Haiku checks and
  a cached chapter prefix. Done when three films in a row meet the bar at
  <= $2.50 and <= 15 owner minutes each.
- **3. Pilot (weeks 5-13).** 16 films at two a week (or one). Chapter-
  strip review, retention per chapter, cost per finished minute and YPP
  hours on Money. Gate at film 12-16: CTR ~4%+, average watched ~35%+,
  views rising. Otherwise change topics/packaging, then format; stop the
  channel with no traction by film 24.
- **4. Scale (month 3+).** Middle stages unapproved once owner verdicts
  and checks agree 9 in 10; motion cold open A/B; series compilations;
  second channel (compositor explainer); Creator voice plan.
- **5. Structure, only when it pays.** Settings per format first, then
  one database, stable channel ids, formats as plugins (5 Oct review).

## Budget

| Scenario | Long films/month | Cash/month |
|---|---|---|
| Maintenance only | 0 | ~$4 |
| Lean pilot (10 min, one teaser) | 4 | ~$10 |
| Pilot (Starter covers 7 at 12 min, 8 at 10 min) | 8 | ~$20 |
| Scale (Creator) | 16 | ~$57 |
| Two channels (Creator) | 24 | ~$65 |

Nothing earns before the Partner Programme. 8,000 hours is 100 films at
1,000 views, 12 minutes, 40% watched; views per film matter more than
volume. The stop rule at film 24 caps a failed channel at about $50.

## Owner decisions (all agreed as recommended, 6 Oct)

1. Pilot channel: History Unmystified, one person per film.
2. Look: illustrated stills + archival + graphics.
3. 12 minutes, two a week.
4. Approve every stage in Phase 1; then packaging + outline and the final cut.
5. Up to ~$25/month of Claude and images through the pilot.
6. Archive the four test channels.
7. Motion off until Phase 4.
