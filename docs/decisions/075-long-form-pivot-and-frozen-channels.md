# 075 — Long-form first; Minute Pastor and Pub Quiz Buzz frozen

**Status:** active. Phase 0 of the plan in
[`docs/specs/longform-pivot.md`](../specs/longform-pivot.md).

## What happened

On 6 October the owner set a new direction:

> "This project has developed beyond its original scope. it was
> originally to create shorts content for youtube. however, this has
> been deemed unprofitable. The current projects (minutepastor and
> pubquizbuzz) need to be maintined in their current state. We are now
> changing to be focussed on long form videos"

The reasons are in the plan: from 1 Feb 2027 Shorts revenue sharing
needs 10M Shorts views in 90 days, and new Partner Programme applicants
need 8,000 watch hours, which Shorts views don't count toward. The owner
agreed every recommendation in the plan (illustrated documentaries,
History Unmystified as the pilot, about $25 a month through the pilot,
archive the test channels, no generated motion until later) and asked
for Phase 0: protect the two live channels before anything else changes.

## Decisions

**"Maintained in their current state" is taken literally.** Minute
Pastor and Pub Quiz Buzz keep their settings, schedules and output. Their
code gets bug fixes and credential upkeep only. Shared code (writing,
voice, rendering, sound, publishing) changes only by adding behind
defaults those two channels keep.

**A frozen-channel check enforces it** (`tests/frozen/`). Each channel's
real pipeline, `pipeline.run.generate`, runs end to end with every
outside service replaced by a recorder, and what comes out must match a
golden copy:

- every request to Claude (model, budget, effort, system prompt, user
  message, schema) and to ElevenLabs (text, voice, speed, model,
  neighbouring lines), word for word;
- the footage chosen per shot, the quiz board's page, and the long quiz
  Pub Quiz Buzz recuts from two of its shorts (both variants, chapters,
  titles, thumbnails);
- five frames of the finished picture, hashed (captions, cards and the
  hook are drawn by the code being checked);
- the final sound, hashed, and the music mix;
- the files written beside each video, minus times and paths;
- the settings each channel resolves to, and its next publishing slots.

The settings are a snapshot taken at the freeze (`channels.json`), not
the live config: what's pinned is the code, and the owner stays free to
change a setting in the app. Fakes stand in for the outside world: a
tone as long as each line for the voice, canned answers per operation
for Claude, a flat video for footage. The check catches what it should:
tried against a caption colour, an encoder preset, a model and a music
level, each failed it with the exact difference.

It runs with the rest of the fast suite (about 30 seconds) and on its
own with `-m frozen`. When it fails, the change is made additive, or the
owner agrees and `python -m tests.frozen.regenerate` writes new goldens,
committed with the change that caused them.

**Isolation is enforced, not hoped for.** The first trial run wrote a
test video into Minute Pastor's real output folder: the channel's output
path was relative to the project. It was removed within a minute. Now
every module-level path into the installation's data (config, channels,
cache, output, footage, facts, music) is redirected to a temporary
folder, and a Python audit hook refuses any file access under those
folders during a frozen run and fails the check.

**The freeze point is tagged**: `shorts-freeze-2026-10-06`, the commit
before any Phase 0 change.

**The scenes engine and the HTML templates stay.** The plan proposed
retiring `pipeline/scenes/` and `pipeline/templates/` once an audit
showed no live channel reached them. Measured during the frozen runs
(every function called, recorded):

| Reached by a frozen channel | Imported, never run | Not loaded |
|---|---|---|
| `scenes.art` (art direction), `scenes.render` (the page filmed in Chrome: Pub Quiz Buzz's board, the long quiz and its thumbnail), `templates.page`, `templates.theme`, `templates.tex` | `scenes.stage`, `scenes.writer`, `scenes.props`, `templates.fill`, `templates.library` | `scenes.iconlib`, `templates.gallery`, `templates.samples`; all of `pipeline/animation/` and `pipeline/documentary/` |

So the two folders are shared infrastructure as much as features: the
quiz board and the long quizzes depend on them, and so does the
long-form compositor (`scenes.render`, `scenes.props`). Only the
per-segment scene and template features are unused by the live
channels, and removing them means changing the imports of
`pipeline.visuals` and `pipeline.director`, which Minute Pastor's run
loads. Not worth it now; the frozen check makes it safe to do later.
`channels/maths_demo` isn't a channel: it's the scenes engine's demo
props, left alone.

**Spare voice puts long-form first.** In the last three days before the
voice allowance resets, the spare is spent on shorts made ahead
(decision 069). It now first keeps back what documentaries in production
still need (`core.production.narration_still_to_voice`):

- a film's narration, exactly, once its script is written, until its
  video stage has been made;
- an estimate from the outline's minutes when only an approved outline
  exists (2.4 words a second, 6 characters a word);
- teasers written and waiting to be made.

An outline written ahead by the scheduler and never approved owes
nothing, and a production untouched for 14 days isn't counted: credits
kept for a film nobody is making would only be lost at the reset.

**A documentary channel never gets shorts made ahead.** Found while
doing this: spare voice planned for every channel with publishing slots,
documentary channels included, so turning on History Unmystified's
publishing plan would have had it start ordinary short videos for it.
The scheduler already refused those (decision 074); spare voice now does
too.

**The test channels are archived**: Curiosity Leak, Wren's Guide to
Witchcraft and Shakespeare Lines. Their data is kept and they can be
restored from the Channels page.

## Not done

- The scheduler's background duties for the frozen channels (question
  bank stocking, plan top-ups, autopilot, publishing) aren't in the
  fingerprint; their own unit tests cover them, as before.
- The owner's Phase 0 steps are in TASKS.md: credit top-up, Minute
  Pastor's YouTube connection and consent screen, the second long-quiz
  slot, and checking an upload went out public.
