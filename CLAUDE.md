# Shorts Pipeline — working notes

An automated pipeline producing short-form vertical videos: a seed (quote
or topic) becomes a script, narration with word-level timings, matched
stock footage and burned-in captions.

**Read these first, not this file:**

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — what the system is, layer by
  layer, kept current.
- **[docs/decisions/](docs/decisions/)** — why each significant decision
  was made, including what was tried and rejected. Append-only.
- **[README.md](README.md)** — how to run and operate it.

This file used to be ~500 lines of accumulated change history loaded into
context every session. Much of it described behaviour that had since
changed. It was a good decision log wearing a specification's clothes;
splitting the two is decision
[011](docs/decisions/011-sparse-channel-config.md)'s sibling in spirit —
the same instinct that a fact and the reason for it rot at different
rates and belong in different places.

## Environment

Windows, project at `C:\Users\JackW\Documents\YT\`, Python 3.10, Git Bash.

## Conventions worth knowing before editing

- **Errors** — raise a `PipelineError` subclass from `core.errors` with a
  `user_message` written for the person using the tool. Never put
  `str(exc)` in a response; the technical detail belongs in the log.
- **Logging** — `get_logger(__name__)`, never `print()`. The job runner
  routes log records to the right job by contextvar; a `print()` bypasses
  that and vanishes from the UI.
- **Paths** — from `core.paths`. Don't recompute `PROJECT_ROOT`, don't
  write another `slugify`, and put anything user-supplied through
  `safe_join`.
- **Layers** — `web` → `core` → `pipeline`, one direction only. Nothing
  in `pipeline` imports Flask.
- **Silent failures** — only checkpointing and cost logging swallow
  exceptions, and each says why in a comment. Everything else surfaces.
- **Model calls** — go through `pipeline.llm`. Thinking is billed out of
  `max_tokens`, so every budget must cover reasoning AND the answer;
  never check `response.content` without checking `stop_reason` first.
  See decision [013](docs/decisions/013-failing-safely.md).
- **Failure cost** — should be proportional to what is recoverable. By
  the footage stage a script and a voiceover are already paid for, so a
  scoring failure degrades to unscored picks rather than losing them.
  Anything that degrades sets a flag the UI shows.
- **Tests** — `python -m pytest -m "not slow"` before and after a change.
  Every documented bug has a regression test; keep it that way.

## Where the risk actually is

Two things drive most of the judgement calls in this codebase, and both
are worth holding in mind when changing it.

**Cost concentrates in one place.** Footage matching, not script
generation, is where the money goes — see decision
[007](docs/decisions/007-shortlist-before-matching.md). Anything that
puts more text into that prompt, or calls it more often, is expensive in
a way that isn't visible until the bill arrives. `python main.py --costs`
is the check.

**The monetization case rests on originality.** YouTube's reused-content
rules single out "AI-generated content made with generic or unoriginal
templates giving the impression of mass production", and this pipeline is
exactly the shape that description is aimed at. The defences are: genuine
per-passage analysis rather than a template, footage that actually
matches what is being said, and never shipping a video that repeats a
clip or reuses an earlier script's wording. The similarity check and the
`footage_repeated` flag exist for that reason and should stay visible in
the UI rather than becoming log noise.

## Open

- **YouTube upload** is not built. It needs an OAuth client the account
  owner has to create; the pipeline has a natural place for it as a
  post-render stage.
- **Cross-channel sameness** — per-channel pacing helps, but there is no
  measurement of whether two channels are converging on the same
  structure. Worth building once more than one channel publishes
  regularly.
- **Clip description length** — descriptions average ~685 characters of
  prose. Shorter structured descriptions would retrieve better, but
  mixing two formats in one library would hurt matching more than the
  saving is worth. Do it as a full re-describe, or not at all.
