# 067 — Today and Money: what needs you, and what it all costs

**Status:** active.

## What happened

The owner's review on 5 October found three problems with the app:

- It was organised around what it contains: channels, footage, facts,
  voices, APIs. What it should be organised around is what the owner
  does.
- Nothing said what to do next:
  - Minute Pastor's YouTube connection died around 1 October, and the
    only sign was a line on Insights, with an upload due on the 7th.
  - Wren's Guide sat at "make and approve a first video" for twelve
    days.
  - A drafted channel went unread.
  - TASKS.md, 585 lines kept by hand, was doing the app's job.
- Nothing said what running the channels costs a month, how long the
  Claude credit and the voice allowance last, or when the money comes
  back. The credit was close to running out, the voice allowance
  wouldn't cover a month at the current pace, and nothing on screen said
  either.

The owner's terms, the same day:

- Every cost on these keys is spent by this app.
- The Claude budget so far is $40.
- Once the channels break even, spending needs no limit; until then,
  show the real monthly cost and when, or whether, it gets paid back.
- Long-form is the earner.

## What was decided

- **Today is the home page** (`/`, `core.today`). It has three parts:
  - **Needs you** is one list, worst first. Each item has one button
    that does the thing (Reconnect, Billing, Resume, Archive, Review,
    Topic plan). An item leaves only when the state behind it changes;
    nothing is dismissed by hand. The sources are:
    - a YouTube connection Google rejected (remembered in its token file
      as `rejected_at` until it works again);
    - Claude credit under a week;
    - a voice allowance that runs out before it resets, or can't cover
      a month at its recent pace;
    - videos to review, per channel;
    - failed videos;
    - topic plans that won't top themselves up;
    - channels stalled in setup (with how long, and Archive);
    - undecided channel drafts;
    - dead quiz categories (decision 065).

    A source that fails shows as "couldn't check X" and never hides the
    rest.
  - **Running by itself:** each live channel's state, schedule, queue
    and next slot; the question bank; long quizzes.
  - **This month:** cost at this schedule, credit left, the voice
    allowance, and earnings.
- **Money** (`/money`, `core.money`) shows:
  - cost a day, a week and a month at this schedule. That's each
    channel's videos a month, from its publishing plan, times the median
    API cost of its last ten videos, plus the ElevenLabs plan. Last 7 and
    30 days' actual spend sits beside it.
  - **Credit left.** The owner enters what's on the account once, and
    again after a top-up. The cost log takes everything spent since off
    it. Seeded with $40 since the start.
  - **The voice allowance** at its own counter's pace over the last
    week, read daily into `cache/voice_usage.json`. Never from the cost
    log, which overcounts about fourfold. It was seeded with the two real
    readings: 4,381 on 30 Sep and 11,061 on 5 Oct.
  - **Payback:** long-form views a month that would cover the costs at
    an editable RPM ($4 for trivia and education), and earnings, counted
    only for channels marked as in the Partner Programme.
  - **Partner Programme progress:** subscribers, read with the audience
    refresh; long-form watch hours over 12 months; and Shorts views over
    90 days. It's against whichever bar applies, and gives the watch
    hours a day needed to join at 4,000 before the bar doubles on
    1 Feb 2027.
- **Navigation** is Today, Channels, Review, Money and Insights, with
  Activity, Footage, Facts, Voice Lab, APIs and Phone under More. The
  channel list moved to `/channels`.

## Not done, and why

- **Earnings from YouTube itself.** The Analytics API reports revenue
  only to monetised channels with a further permission. Until then it's
  views times an RPM, and the page says so.
- **Settings tiers, review by channel, the channel wizard.** These are
  next in the review's order.
