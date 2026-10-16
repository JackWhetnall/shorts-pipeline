# 111 — Four films at once, four banked; the overseer reads the teasers

**Status:** active.

## What the owner asked

The aim is four films a week (Mon, Wed, Fri, Sun at 16:30). A film can
take about three days when OpenAI's picture batches are slow, so several
should be made at once. The owner suggested up to four being made, plus
a bank of four made and not yet published. The overseer should also
check the teasers, against all the editorial decisions that shaped them.

## How long a film takes

From the films so far:
- angle to script: one to three hours;
- the overseer's read: until its next run;
- storyboard: one to ten hours, but each picture-batch round can take a
  day;
- video: about an hour;
- the owner's look: as long as it takes;
- teasers: about an hour.

That's a day to a day and a half typically, and three days at worst.

## Decision

- **Two numbers instead of one.**
  - `documentary.parallel` is how many films are made at once (default
    2).
  - `documentary.ahead` is the bank: films finished and not yet out,
    whether waiting for a look or approved and queued.
  - A new film starts while fewer than `parallel` are being made and the
    films in hand are fewer than `parallel + ahead`.
  - Settings shows both, as "Films made at once" and "Finished films
    banked, at most".
  - Why, Though? is set to 4 and 4.
- **The teasers are a third checkpoint on an overseen channel.** Their
  scripts wait, written, until the overseer has read them:
  - `overseer teasers` prints each teaser line by line, with the picture
    it's shown over;
  - `edit-teaser` fixes a line or a title;
  - `approve … teasers` marks them read, and the autopilot then makes
    them.
- **The checklist records the owner's rules.** `docs/overseer.md`
  Checkpoint 3 lists the rules from decisions 106 and 110: hook, premise,
  payoff, stop short, clarity, the film's own facts and comparisons, the
  plain invitation that names the channel, two different teasers, an
  honest title.
