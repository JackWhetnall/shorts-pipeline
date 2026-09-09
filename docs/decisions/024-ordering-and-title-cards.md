# 024 — Ordering as policy, and two things the title card can say

**Status:** active

## Ordering used to be a one-off choice

"Make the next video" asked the same question every single time it was
clicked, when the real answer is almost always the same for a given
channel: this one always finishes a topic before starting the next; that
one wants a random subtopic from a random topic; a third wants to feel
like an organically growing series. That's a channel policy, not a
per-click decision — so it's a channel setting now
(`core.channels.Ordering`), and `pipeline.run.fetch_seed`'s "no explicit
pick" path (the common case: "just make me the next video") reads it via
a new `core.ordering.choose_next_subtopic`.

Three independent knobs — topic order, subtopic order, grouping
(finish-a-topic vs round-robin) — cover eight combinations without eight
named presets. "Natural" sits outside that grid on purpose: it's a
weighted continuation (one `stickiness` number — how often to keep going
on the topic already in progress before branching to whichever topic has
had the least attention), not a fixed sequence, and modelling it as a
fourth knob on the other three would have made every combination involving
it either meaningless or need its own special-casing anyway.

Every explicit pick on the Create Video page (a named subtopic, a named
topic, "random within this topic") is untouched — those are a genuine
escape hatch for "not the policy, just this once," and stay exactly as
they worked before.

### A bug in round-robin, caught by its own test

The first version of `_structured_choice` fell through to `pending_topics
[0]` whenever the current topic didn't apply — correct for `topic_first`
(nothing was "in progress," so start at the beginning), wrong for
`round_robin`, where it meant every topic *after* the first would get
skipped forever: topic 1 exhausts, "advance" lands back on topic 1's own
slot in the list, which is topic 1 again. Round-robin cycling needs to
advance from *wherever it was*, not reset to the start — fixed by tracking
the last-made topic's position and walking forward from there, wrapping
around. Caught by
`tests/test_ordering.py::TestRoundRobin::test_genuinely_cycles_rather_than_collapsing_back_to_the_first_topic`,
written specifically because the first version's own tests happened not
to exercise a *third* topic, which is exactly where the bug lived.

## The Create Video picker's own two complaints

"Within that topic" read as if a subtopic always had to be named, even
when "random" was chosen — relabelled to "Which subtopic," options reworded
to "The next one in order / A random one / A specific one." No logic
changed; `onWithinChosen()` already only revealed the subtopic dropdown for
"specific."

Fetching a seed always framed it as a candidate — Reroll, Use this — even
when the pick was fully explicit (a named subtopic) and there was nothing
to reroll. `getSeed()` now hides Reroll and relabels the button to
"Confirm" whenever `currentPick()` carries a `subtopic_id`: it's showing
back what was already chosen, not suggesting something.

## The title card: where it lands, and what it names

Two independent additions to `core.channels.Style`, both no-ops unless a
channel opts in.

**Placement.** `title_card_placement` — `"start"` (unchanged) or
`"after_intro"`. The card used to always precede all narration; now it can
splice in after the first segment's real, TTS-measured end
(`plan.script.segments[0].end`) instead — `pipeline.assemble.run` splits
`narration_video` and the raw audio array at that point rather than always
prepending. The historical risk here (decision 020: get the silence wrong
and every caption in the video drifts by the card's length) applies
identically to a mid-video splice, so the audio insertion point moves with
the video split rather than being computed separately — one `split_at`,
used for both. Verified with a real render
(`test_a_title_card_after_the_intro_line_splices_in_rather_than_leading`):
a frame inside segment 0 is real footage, a frame at the card's new,
shifted position is the card, and total duration is unchanged.

**What it names.** `title_card_show_topic` adds the enclosing syllabus
topic as a third line — channel name, topic, then the video's own title —
for a channel with a curriculum where a series-minded viewer benefits from
knowing which part of the syllabus this is. Styled like the channel line
(a breadcrumb) rather than introducing a whole new set of colour/size
settings for one extra line. `pipeline.assemble._topic_title_for_card`
does the one hop a `Seed` doesn't carry directly — its `topic_id` is
actually a *subtopic's* id (see `pipeline.plan.Seed`'s own docstring), so
naming the topic means looking the subtopic up and then its topic.

## Cross-topic context, made configurable

`build_on_previous` and the script studio's own batch-writer context
(`pipeline.script_gen._covered_titles`) only ever looked at a script's own
topic. `ChannelConfig.context_scope` (`"topic"` | `"recent_topics"` |
`"all"`, plus `context_topics` for how many) is additive alongside
`build_on_previous` rather than replacing it — renaming or removing a
field that real channel config (`wrens_guide_to_witchcraft`) already sets
to `true` risks it being silently dropped on the next load (`core.channels
.channel_from_dict` drops unknown fields without complaint, which is the
right behaviour for a genuinely removed field and the wrong one for a
renamed live setting).

`core.curriculum.covered_titles` is the one new read: given a scope, walks
the syllabus's own file order — topics fill in teaching order, so "the N
topics before this one" is a real position, never an arbitrary cut — and
returns published/used subtopic rows from the resulting window, same
shape `covered_in_topic` already returned so both call sites
(`script_gen._continuity` for a single video, `script_gen._covered_titles`
for the batch writer) needed only a one-line swap.

## Where these three land

None of it touches the script-studio work (decision 023) — a channel that
never sets an ordering, a title-card placement, or a context scope behaves
exactly as it always has, and none of the three needed to change how a
script itself is written, only what it's told and when the card appears.
