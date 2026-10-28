# 139 — Week by week, what went out, and test channels set aside

**Status:** active.

## What the owner said (28 Oct)

- Insights showed Why, Though?'s spend as zero, "when in reality it
  should be the highest of the lot", and said 38 videos were waiting for
  review while the review queue was empty.
- The channels still being set up are "mostly just tests for now". They
  asked for a checkbox to include them, unchecked by default.
- They wanted a page showing "what went out yesterday (or since this
  page's updates were "cleared" by me), and what is expected to go out
  today".
- Insights "doesn't show the trajectory eg if my shorts a week ago were
  getting 10 views and this week they are getting 50 views then it's
  actually a marked improvement". Because of daily swings, "these
  comparative insights should compare things on a week-by-week basis",
  split by channel.

## The two numbers that were wrong

- **Spend by channel** added up the cost file written beside each video. A
  film's costs never sit beside its video, so Why, Though?, the biggest
  spender at $49, showed $0. It now adds up everything in the cost log for
  that channel.
- **"Awaiting review"** was every kept video that wasn't out. That meant 35
  videos approved and queued for their slots, plus 3 set aside for their
  pair. It now counts only videos waiting for a look, which is what the
  review queue shows. A new **Queued** tile shows the rest.

## Test channels

A channel that isn't archived and isn't publishing yet counts as a test
channel (`web.focus.is_test`). Today, Insights and the channel picker in
the header leave test channels out. A **Tests** toggle in the header,
off by default and remembered per browser, brings them back.

## Going out, and Out since

Today gains two cards (`core.digest`):
- **Going out:** what the publishing queues send today and tomorrow,
  marked Long, Teaser or Short.
- **Out since:** everything that went out on YouTube, TikTok or Instagram
  since the start of yesterday, or since the owner last pressed
  **Clear**. It's grouped by channel, with links to each platform.

## Week by week

Insights gains a **Week by week** panel, built from YouTube's day-by-day
figures (`core.outlook.daily`, cached twelve hours). It shows:
- Shorts views;
- views per Short that went out that week;
- long-video views;
- watch hours;
- subscribers.

**How weeks are compared:**
- The week under way is compared only with the same days of the week
  before, up to the last day YouTube has figures for. Its figures run a
  day or two behind.
- A full week is compared with the week before.
- There's a bar chart of the last eight weeks for each measure, with the
  part week hatched.
- With all channels shown, there's a row for each channel.
- With one channel chosen in the header, it's that channel alone.
