# 009 — A typed RenderPlan through the pipeline

**Status:** active

## Decision

One `RenderPlan` object accumulates through the pipeline. Every stage is
`fn(plan) -> plan`.

## Why

Each stage previously had its own ad-hoc shape: a seed dict whose keys
depended on its `"type"`, a script dict of dicts, a five-tuple back from
the voiceover stage, two parallel lists-of-lists (spans in one, clip
paths in another) that the assembler zipped back together, and thirteen
parameters into `build_video` — five of which were just the channel
config, unpacked field by field.

The cost was not that this was ugly. It was that every new capability had
to be threaded through every signature. Adding a background music track
would have meant a new parameter in three functions and a sixth element
in the tuple. That is a tax on exactly the thing the project needs to do
next: scheduling, uploads, thumbnails.

## Consequences

- A `Shot` knows its own clip path, so the assembler no longer re-zips
  parallel lists.
- Stages take the whole channel rather than unpacked fields, so a new
  channel-level setting does not change any signature.
- The plan doubles as a record of how far a job got — a field is `None`
  until the stage that fills it has run.
- Everything is JSON round-trippable, because checkpoints persist partial
  plans so an interrupted job resumes without re-paying for completed
  work. The exception is the raw audio array, checkpointed as an mp3:
  decoding a saved file is more reliable than serialising float samples,
  the same reasoning as [002](002-audio-decoding.md).

## Related

The `interactive` boolean that used to be threaded through three layers
to suppress one `input()` call went away with this. The footage matcher
never prompts now; it returns shortfalls and the caller decides. A
library should not need to know whether a terminal exists.
