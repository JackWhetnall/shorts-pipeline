# 125 — Every film tested from its first day, titles included

**Status:** active. Changes how decision 117's film rotation starts, and
adds a title test beside it.

## What the owner said (21 Oct)

> the thumbnails and titles for the Why Though channel all seem to be
> identical format - i thought we were supposed to be testing different
> ones? are you testing them by changing them dynamically and checking
> which performs best? are you publishing each video with a different
> version to see which one is best? at the moment it just looks like the
> default one is there every time - this needs to be done better

## What was happening

They were right on both counts:
- **Every film showed A.** A film held A for two days before rotating
  (`SETTLE_DAYS`), so nothing could look tested in its first days. Four
  of the five films out were at day 2 on A. The only one that wasn't was
  the second film in its round.
- **Titles weren't tested.** Titles were only rotated in a content
  round, the last phase of the programme. All three running rounds were
  style rounds, so no title had ever been changed.
- **Too few impressions to judge.** Click-through reports were arriving,
  but there were only 987 impressions across 8 videos, the best 567 in
  four days. A test needs about 900 a round (300 a variant), so most
  rounds would end "too few impressions to tell".

## Decision

**A film starts on its own variant the moment it's out.** There's no
settle. The channel's films go out on A, B and C in turn, counted across
the whole channel rather than per round, because three rounds had each
started their first film on A. A film then rotates every three days over
18 days. The launch burst, when a film gets most of its impressions, is
spread across the variants instead of always landing on A.

**Titles are tested too, as a second test running alongside.** Each film
that's out gets two more titles, written for it by one cheap call (about
a tenth of a cent), in deliberately different forms
(`pipeline.documentary.title_variants`):
- A: the title it went out with;
- B: a statement, the film's most surprising true claim said outright;
- C: to the viewer, speaking to them or opening a gap.

Because they differ in form, what the test learns is which kind of title
works for the channel, not just which wording.

**The two tests are kept separable.** A title's turn runs one segment
ahead of the film's thumbnail on alternate films, and two segments ahead
on the others. So no title always shares its days with one thumbnail,
and across a round's films each effect can be told apart.

**Titles are judged like thumbnails.** That means at least 300
impressions each and a 10% lead. A clear winner is kept as the film's
title, counted in `title_formats` for the channel, and written into the
channel's lessons for its writers. Titles change only when the channel
may be managed.

A content round's titles still change with its thumbnails, as before.

**The film page shows what's live:** the day, the thumbnail and title up
now, impressions so far against what's needed, and the three titles with
the live one marked.

**Films already out:** they move to the channel-wide order at once.

## What this doesn't fix

The tests are only as good as the impressions behind them. At the
current reach, a round will often end with no verdict. The test has to
run regardless, because the cost of running it is nothing. But the honest
expectation is that for the first months it will only find big
differences, not small ones.
