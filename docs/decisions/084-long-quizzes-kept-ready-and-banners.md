# 084 — Long quizzes kept ready by making shorts ahead; banners in each channel's look

**Status:** active. Amends 066 (one long quiz waiting at a time) and 058 (banners).

## What happened

On 9 October the owner wrote that with 7 shorts a week there should be a
long quiz every week. Because shorts come in random order, though, there
weren't enough complete sets yet:

> "if we want to have, say 3 long form quizzes ready to go in advance,
> then we should have an option to generate shorts until those quizzes
> are available (then generate that quiz, of course). due to wanting a
> random ordering of the shorts quizzes, i dont want to just generate
> the 'most efficient' shorts to make the next quiz"

And: "the youtube banners seem to be identical between channels".

## How much stock self-sustains

Pub Quiz Buzz has 13 categories, 6 levels and one long slot a week. At
7 shorts a week, each level gains about 1.2 rounds a week. Each round
can go into one quiz night and one category quiz (the series are kept
apart), so the long-run supply is about 2.3 long quizzes a week against
the one a week that goes out. The constraint is the stock.

A simulation of random plan order, 200 runs, quiz nights only, found the
stock of quiz nights (median) after:

| Weeks of shorts | Quiz nights in stock |
|---|---|
| 4 | 0 |
| 8 | 1 |
| 12 | 3 |
| 26 | 4 |

So it's self-sustaining after about 12 weeks of shorts (around 80
made), sooner with category quizzes.

## Decisions

**"Kept ready"** (`quiz.longform_ready`, Settings, Quiz, Long quizzes):
- **0** (the default) is as before: at most one quiz night and one
  category quiz waiting.
- **N** lets up to N long quizzes wait at once, in both series together.
- While what's waiting plus what the rounds could make (`longform.
  projection`) is short of N, the scheduler makes shorts beyond the
  channel's usual buffer (`scheduler._shorts_for_long_quizzes`).
- Each one is the plan's next short, in its own random order. Nothing is
  chosen to complete a set, so publishing order stays natural.
- Shorts waiting for review count towards the projection, so it doesn't
  overshoot while they wait.
- It never goes past 10 weeks of short slots made ahead.

The projection takes quiz nights at the level with the most to spare,
clash-free, until none can be made, and category quizzes as one per
complete set of a category's levels. The long quiz card says where it
stands in one line, e.g. "1 made, 2 makeable of 3 kept ready · 3 weeks ·
making shorts ahead".

Pub Quiz Buzz is frozen (075); with the setting at 0, nothing it makes
or when changes.

**Banners in the channel's own look.** The old ones took their colours
from the end card, near-black on every channel, in one layout, with the
same light bars, so only the logo told them apart. Now there are two
designs, drawn as pages in the theme the channel's videos use (its
palette, display face, background texture):
- **"In its own look":** the name and tagline, with its topics as chips.
  A quiz carries its stamp, as on every short's opening screen, and its
  big "?".
- **"With its own picture":** a picture of its own work behind the name:
  - a documentary: its latest storyboard still or style frame;
  - a footage channel: the most colourful of several frames from its
    recent videos, scored for colourfulness and contrast (one fixed
    frame gave Minute Pastor a door handle);
  - a quiz, which has no picture: its board, dark.

Everything that matters stays in the centre a phone shows. If the page
renderer fails, the old plain drawing is used.
