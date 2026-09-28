# 047 — Each quiz format on its own settings, both long formats every time, and a hook

**Status:** active. Revises 044's single long-quiz variant and its shared timings.

## What happened

The owner looked over The Pub Quiz Round's settings and asked for:

- **Timing per format.** The gap between question and answer "shouldn't
  affect both shorts and long videos equally". Shorts, answers-as-you-go
  long quizzes and answers-at-the-end long quizzes each need their own
  settings.
- **Both long formats every time.** Make both "even if not publishing
  both types": one may do better, and it's "better to have them all now
  than miss some that are needed".
- **Visible difficulty levels.** Levels could be set with `Hard (5.5)`,
  but only a paragraph of text said so, and they couldn't find it.
- **Less text on the settings page.** A "waffly text section" should never
  exist. Important information goes in tooltips; anything else is deleted.
- **The danger zone in its own place,** not under every settings section.
- **Gentler ticks.** The clock ticks "can be a bit harsh", so they should
  be customisable.
- **A hook for quiz shorts,** with splash text to catch the eye. Openings
  must be varied and novel. Examples in the prompt must never be
  suggested verbatim.
- **A music picker that works.** On quiz channels it did nothing.

## What was decided

**Timings.** Each format has its own settings:

| Format | Settings |
|---|---|
| Shorts | countdown after each question; pause after each answer |
| Answers as you go | clock for each question; pause after each answer |
| Answers at the end | clock for each question; time to finish a round; gap between a question read again and its answer; pause after each answer |

The old shared `longform_clock_seconds` and `longform_finish_seconds`
carry over to both long formats on load (`channels._RENAMED`).

**Both long formats, one kept as a spare.** Every long quiz is made in
both formats from the same rounds:

- The host's joining lines are written once and voiced once, because only
  the finish lines and "pens down" lines differ, and the as-you-go
  version simply leaves those out. The second format costs filming time,
  not voice characters.
- The channel's choice goes to review: one format, or "alternate" (odd
  episodes answers as you go, even ones answers at the end).
- The other is a **spare** (`spare_of` in its publish sidecar). A spare
  is:
  - kept out of review, the counts, the publishing queue and the series'
    round and episode records;
  - listed under **Spares** in the gallery, with **Use this one
    instead**, which swaps the two;
  - discarded along with its partner.

Publishing both would put the same questions on one channel twice, which
is the reused-content pattern CLAUDE.md warns about. So the app never
queues a spare by itself; it's there for when one format proves better.

**Levels as rows.** Each row is a name and its level (1-10, in halves).
They're saved as `Name (N)`, ordered by level, so a new row slots in
wherever its number puts it.

**Settings text.** Paragraph hints became tooltips where the information
matters and were deleted where it didn't, across every section. The
danger zone (archive, delete) is its own sidebar section. It sits outside
the settings form, which steps aside while it's shown, because those are
actions, not settings to save.

**The clock.** `sound.clock_sound` chooses between:

- soft knock (the new default, low with no noise);
- wooden tick (the old one);
- sharp click;
- soft beep;
- none.

`sound.clock_level` scales the tick against the other effects. **Listen**
plays four seconds of the clock and the answer chime at the chosen
settings. The same tick serves shorts and long quizzes.

**The hook.**

- The writer returns a `hook` (spoken first, under 12 words) and a
  `splash` (two to five words shown big on the opening card, tilted in
  the accent colour, popping in). The intro that follows is shorter.
- The prompt describes what a hook does, not what one says. It dares the
  viewer to prove what they know, is pitched to the difficulty, and
  belongs to the category's world.
- The prompt has no example lines. Examples in prompts get copied
  (decision 037), and the owner asked for this explicitly.
- Each round's hook and splash are remembered in the question bank. The
  channel's last 15 (made or written ahead) go to the writer as openings
  it must not echo in wording, shape or how they begin.
- Rounds already written before this have no hook and play as before.

**The music picker.** A quiz channel has no graphics slider, so setting
up the graphics section threw an error, and every later part of the page
was left dead. Each part of the page is now set up on its own
(`initEach`), so one failure can't take the others down.

## Tried and rejected

- **Hook rules that only said "vary it".** The first real test opened
  with "Think you know your tunes? Time to prove it.": generic, and the
  shape the owner named as the thing to avoid. Another told the viewer
  "the rest of you should leave now". The rules now require:
  - the category's own world;
  - no pushing viewers away;
  - no promising what isn't there. "Name that tune" implied audio clips.
- **Queueing both long formats.** This would repeat a round's questions
  on one channel. See above.
