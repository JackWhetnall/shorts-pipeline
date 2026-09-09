# 023 — Scripts as their own thing, ahead of any video

**Status:** active

## The problem

Two complaints about the same root cause. A channel whose videos are
meant to build on each other got videos that didn't know what came
before, because each script was generated in total isolation — one call,
one video, no view of anything else. And a script didn't exist as a
thing you could read, fix, or try again without spending a full render:
it was generated, immediately consumed by TTS and assembly, and survived
only as a text sidecar next to a finished video.

## Batched, not incremental

The alternative to batching was incremental: keep one call per video, but
feed each one a growing "story so far" built from earlier videos in the
same topic. Rejected in discussion — a batch call is simpler, and it
buys something incremental context can't: genuine consistency across a
topic's videos, decided together rather than converged on video by video.

The objection to batching is that it seems to force committing to a
topic's whole arc before any of it has been watched. It doesn't, once
scripts are their own thing: `core.curriculum` gained a `script` field on
a subtopic row, written by `pipeline.script_gen.write_scripts` — one
call, several subtopics of one topic, sharing a context window so no two
open the same way and nothing repeats an example or a phrasing habit.
Nothing about writing a script claims the subtopic or commits to a video.
That still happens at render time, exactly as before.

## Three ways to write one

The batch writer is the first pass, not the only path to a script.
`pipeline.script_gen.regenerate_script` covers the other two: a blind
retry (no instruction) or a prompted one ("also mention X"), both fed the
topic's other already-written scripts as context so a touch-up doesn't
drift from its siblings. `web/blueprints/curriculum.py`'s `edit_script`
covers the third — a script edited by hand is saved through the exact
same `curriculum.set_script` the other two use, so nothing downstream
needs to know which of the three produced it.

## Reading them: a notebook, not a form

`curriculum_scripts.html` is a tab per subtopic and one panel, arrow keys
to flip through — the same "one array and an index" shape the review
queue already uses, because it's the same task: a repeated judgement call
that benefits from being fast. No formal approval gate. You read, and fix
what's wrong; nothing blocks a render on a script having been looked at.

Its edit form's markup carries no dynamic text at all — every input
starts empty and is filled in afterward via `.value`. Not a style choice:
the previous notebook-adjacent feature (the style-tone picker, decision
022) shipped a bug where generated text containing a double quote broke
out of an inline `onclick="..."` attribute and silently truncated the
handler. `.value` assignment never round-trips through HTML parsing, so
the same class of bug has no way to occur here, on a form whose whole
job is holding freely-written text.

## Rendering: free when there's something to use

`script_gen.run` now checks for a stored script before generating one.
Present, it's used with no API call at all — visible in a job's own log
as `[1/5] Using the pre-written script for this subtopic.` — and this is
verified against a real render, not just mocked: `pipeline.run.generate`
on a real subtopic with a batch-written script logged exactly that line
and produced a finished video with the pre-written text, spending nothing
on script generation. Absent, it generates inline exactly as it always
has. A channel that never touches this feature is unaffected by it.

Discarding a video and discarding a script are different decisions, kept
that way in the data: `curriculum.release()` (a bad take) and
`release_unattached()` (a run that never produced a video) both only
ever touch `status`/`video_stem`/`used_at` — never `script`. Fixing a
script that was wrong at the writing stage is: discard the video, fix
the script through the notebook, render again.

## A crash this surfaced

The first version of the batch call requested `max_tokens` scaled to
`MAX_SCRIPTS_PER_CALL` (8) at a flat 3,000 each — 24,000. The Anthropic
SDK refuses a non-streaming call above roughly 21,300 (`max_tokens` is
treated as a worst-case duration estimate, and past ten minutes' worth it
requires streaming), so the very first real batch call failed before
sending anything, with a bare `ValueError` carrying no `status_code` —
which meant `pipeline.llm._as_service_error` didn't recognise it either,
and it would have escaped as a raw exception with no `user_message`,
the exact thing this project's error convention exists to prevent.

Fixed in two places, not one. `pipeline.script_gen`'s batch budget now
scales with the actual number of subtopics in the call rather than a
flat worst case, and `MAX_SCRIPTS_PER_CALL` dropped to 6. And
`pipeline.llm.call_json` now clamps every budget — the caller's own and
a truncation retry's 3x multiple of it — under the SDK's ceiling, and
`_as_service_error`'s fallback wraps *any* unrecognised exception rather
than only ones carrying an HTTP status. The second fix is the one that
actually closes the gap: the first only makes this particular call
unlikely to reach the ceiling again, but nothing stopped some other
large budget from hitting the same wall the same unhandled way.

## Where it doesn't apply

Curriculum-only. A quote channel has no topic to batch scripts across —
one quote, one script, same as today — and a topic channel with no
syllabus (a flat `topics` list) has nowhere to store a script ahead of a
video either. Both are untouched by any of this.
