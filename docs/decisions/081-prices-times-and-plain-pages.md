# 081 — Prices and times on every choice, plain pages, long quiz picks

**Status:** active. A standing rule for the interface, and fixes to 044, 066, 072 and 074.

## What happened

On 9 October the owner wrote:

> "i HATE overly wordy sections that explain more than i would ever care
> about ... please can you make sure that your ongoing instructions
> include the fact that things should not be over described in text
> always visible on screen. use tooltips where absolutely necessary, and
> even then, make sure it is concise. also ALWAYS give '$' tips when
> things will cost, and what the expected cost is."

They also listed:
- The production page explained itself in paragraphs ("Nothing to do
  until it's done ... Refresh this page to see it", which was misleading:
  the script was still being made).
- Nothing showed that a stage being redone made the ones after it out of
  date, or that the video had gone.
- "Accelerate" and "now, at full price" appeared everywhere, with no
  idea what either costs or how much sooner it'd be.
- Activity's "open the progress view" went to the channel's Productions
  list, not the film.
- The long-quiz menu said "Tricky - 7 ready", and making one then said
  "5 of 6 rounds are ready at Tricky".
- "Rising" sat among the levels and could be made automatically.
- There was no way to see or choose which categories go in.

## Decisions

**The rule** (CLAUDE.md, Conventions):
- Labels, not sentences.
- State shown visually.
- A tooltip only where truly needed, in one line.
- Every paid action shows its $.
- A batch-or-now choice shows both prices and when each would be done.

**Estimates** (`core/estimates.py`). A job's kind (a short, a long quiz,
a documentary stage) sets both its price and its time, measured from
this machine's own record:
- the cost log, by job: Claude's part halves at batch prices, the voice
  and pictures don't;
- finished jobs' durations, split by whether they ran at batch prices;
- the queue ahead of it, for when it would finish.

With no record of a kind yet, a rough default stands in, and its tooltip
says so. Measured on 9 Oct, for example:
- a script: $0.10 in about 48 minutes at batch prices, or $0.19 in 3
  now;
- a storyboard: $1.81 at batch prices in about 3 hours, against $1.85
  in 15 minutes now.

The second is why the "now" box comes pre-ticked when it costs under a
cent more.

Shown as one control (`_speed.html`): "$0.10 · ~48 min ☐ now +$0.09,
~3 min", on every start button on the production page, on New video and
on the long quiz. Activity's Accelerate says the same, e.g. "Batch: ~48
min, Accelerate +$0.09, ~3 min", and its link opens the production at
that stage.

**The production page** lost its explanations. It has:
- a stage strip;
- one pill per section: Being made (pulsing), To approve, Approved,
  Failed (the reason in its tooltip) or Out of date;
- "Will be redone" on every later stage while an earlier one is being
  made, with those sections dimmed;
- one price-and-time control per action.

It polls its stages while one is being made and reloads itself when that
finishes, so there's no "refresh to see it".

**An old video is retired.** When an earlier stage is redone, or a new
video is made, a video that no longer follows from the plan is
discarded (reason "remade", restorable from Videos), unless it has gone
out. The page shows "Old version discarded", linking to it.

**Long quizzes:**
- **Counts.** The menu's counts are clash-free (`availability(...,
  clash_free=True)`): what can actually go into one quiz together. For
  Pub Quiz Buzz that's Tricky 5 rather than 7, Medium 5 rather than 9.
  The scheduler's choice of level is unchanged: Pub Quiz Buzz is frozen
  (decision 075), and the frozen harness checks those numbers.
- **Picking.** Choosing a level lists its approved rounds, the ones that
  would be used ticked, to untick, add or reorder (`rounds_for`,
  `picked_rounds`). A pair whose answers give each other away is
  refused, naming both.
- **Rising** sits in its own "Mixed levels" group. It's made only when
  asked for: the "best" request no longer falls back to it, and the
  scheduler never chose it.
- **When it happens by itself** is one line on the card ("Auto: quiz
  night waiting; category quiz when one has every level"), with the rule
  in its tooltip: a quiz night once that many clash-free rounds are ready
  at one level, a category quiz once a category has every level, one of
  each waiting at a time, checked every few minutes, and only with the
  publishing plan on.
