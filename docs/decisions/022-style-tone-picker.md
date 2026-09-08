# 022 — Selecting a voice instead of inventing one

**Status:** active

## The problem

Setting up a channel's `style_prompt` meant writing a paragraph of English
that reliably steers a script generator toward a specific voice —
wanting something like *"So today we're going to learn how to use incense
when manifesting..."* and having to invent, from a blank textarea, the
instructions that would actually produce it. `preview_script` already
made it cheap to *test* a guess; nothing made it easier to *have* one.

## What this is not

The first draft of this design included a free-text field: describe the
channel, optionally give an example line. Rejected in discussion, for a
reason worth keeping in mind if this is ever extended — the whole point
of a picker is that you select rather than write. A field asking for "an
example of how it should sound" is the same blank-page problem in a
smaller box.

`core/style_choices.py` is deliberately pure selection: eight axes,
three required (Format, Register, Personality), five optional with
sensible defaults. `pipeline.style_gen.draft_candidates` takes only the
resolved choices — no free text parameter exists on it at all, and a
test asserts that.

## Real samples, not one-line pitches

An earlier design also filtered through a cheap pre-stage: one call
proposes five one-sentence style directions, the user picks which ones
are worth seeing in full. Rejected too — a single sentence doesn't show
cadence or flow, and choosing based on it means not really knowing what
you picked.

So there is no filter stage. One call drafts N (default 5, 3-8) complete,
genuinely distinct style prompts consistent with the same choices — the
distinctness is in phrasing habits and structural emphasis, not in the
underlying choices, which is what makes comparing them meaningful rather
than comparing noise from resampling one prompt. Each candidate then gets
a real short sample (`sample_for_candidate`), generated through the exact
same `script_gen.generate_script` a real video would use — a comparison
sample must be produced by the real code path, or a candidate could look
good here and behave differently in production.

Samples are short (2 segments, ~20 seconds of budget) rather than full
length, via `dataclasses.replace` on copies of the channel and its
pacing — cheap to generate several of, never touching the real channel on
disk. Measured on a real run: three candidates, drafted and sampled, cost
under a cent total and took about 30 seconds wall time (parallelised
across candidates via the same `job_context.parallel_map` the TTS stage
already uses for concurrent I/O).

## A bug this surfaced, twice

**`fetch_seed` crashed raw.** A topic-mode channel with no curriculum and
an empty topic list hit `random.choice([])` — an unhandled `IndexError`,
no `user_message`, violating this project's own stated convention that
every failure raises a `PipelineError` subclass. It had gone unnoticed
because the normal path to generation is gated by `channel_progress`
calling `validate()` first; this picker's preview calls `fetch_seed`
directly, ahead of that gate, and hit the gap immediately. Fixed at the
source in `pipeline/run.py`, which also hardens every other caller.

**The candidate cards truncated their own click handlers.** Rendered with
inline `onclick="listenToCandidate('key', this, ${JSON.stringify(text)})"`
— and `JSON.stringify` wraps its output in double quotes, which close an
`onclick="..."` attribute the moment the sample text contains one. Any
candidate whose sample or prompt used a quotation mark — not a rare event
in dialogue-style writing — silently lost the rest of its own click
handler. Found by clicking the button with real generated text, not by
reading the template.

Fixed by not embedding generated text into HTML attributes at all:
candidates render with a `data-candidate-index` and plain buttons, and a
`wireStyleCandidateButtons` pass attaches `addEventListener` handlers
afterward, closing over the real candidate objects. This is not a
one-off patch — it removes the entire class of bug for this component,
since no future candidate field can ever re-trigger it by containing a
character the old approach couldn't survive.

## Where it lives, and where it doesn't

Not part of Settings. Settings owns the final plain-text `style_prompt`
day to day; this is the tool that drafts a first one and hands off. The
entry point in Settings' Channel section reads either "Let AI help you
write this" (blank prompt) or "Rewrite this from scratch" behind a
`confirm()` naming exactly what happens — a full replacement, not a
blend, with existing wording preserved if only a small edit was wanted
(edit the textarea directly instead).

Choosing a candidate only ever writes `style_prompt`. It does not touch
voice, pacing, monetization, or anything else a "reset the whole channel"
reading of the original request might have implied — deliberately scoped
to exactly what the picker itself produces.
