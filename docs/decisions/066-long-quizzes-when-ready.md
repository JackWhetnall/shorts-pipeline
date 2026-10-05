# 066 — Long quizzes are made as soon as the shorts for one are ready

**Status:** active. Replaces the every-N-days timer of
[044](044-long-quizzes.md).

## What happened

Long-form is the earner (owner, 5 October). Research the same day:
mid-roll ads need 8 minutes or more, successful quiz channels run 16–30
minutes, and long-form breakout channels post about 1.6 videos a week.
Pub Quiz Buzz had made one long quiz, 7:22 long. Quiz nights were made
only "every N days", and that was set to 0, which meant only when asked.
A category's own quiz waited for a round at every level, which the
Easy shortage (decision 065) rarely allowed.

The owner: make a long quiz automatically as soon as there are six
suitable shorts, either one category from easiest to hardest, or six
categories at the same difficulty in random order.

## What was decided

- **A quiz night starts itself** once `longform_rounds` categories (6 by
  default) have an approved, non-clashing round at one difficulty. When
  more than one difficulty is ready, the one with most rounds to spare is
  used. The categories play in random order. Settings: "Make a quiz
  night once that many categories have a round at the same difficulty"
  (on by default), and "at least this many days apart" (0: whenever
  ready).
- **Category quizzes**, easiest to hardest, already started themselves
  once a category had a round at every level. Decision 065 makes that
  happen.
- **One waiting per series.** The next quiz night is made once the last
  has gone out, so they keep pace with the long-video slots instead of
  piling up in review. A long quiz's two formats count as one: once
  either has gone out, the other doesn't hold the next one up.
