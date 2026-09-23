# 029 — Reading back what viewers do

**Status:** active.

## Why

Every number this project measured was about itself: discard rate,
render flags, spend per video. `/insights` was called the improvement
loop, but it could only improve what the operator liked, never what
viewers watched. With automatic publishing (decision 028), that gap
matters more, because fewer videos get watched by the operator at all.

## What was decided

`core/audience.py` reads two things per published video, using the
channel's existing OAuth connection with two extra read-only scopes:

- Views, likes and comments from the Data API. Close to live, 1 quota
  unit per 50 videos.
- Average view duration, average percentage viewed and subscribers
  gained from the Analytics API. Percentage viewed is the number that
  decides short-form reach. It lags a day or two.

Refreshed from the scheduler's tick at most every 12 hours per video,
or on demand from `/insights`. Only the latest snapshot is kept, in a
`_stats.json` sidecar that purge removes with the video. That is all the
page needs, and it is what YouTube's developer policies ask of stored
statistics.

The Analytics API is a separate switch in the Cloud project. A project
without it still gets views, and the page says what to enable. A token
saved before the new scopes existed recorded no scope list; `connection()`
reports `stats: False` for it, and `/insights` links straight to
reconnecting that channel. Tokens now store the scopes Google actually
granted, since a person can untick one on the consent screen.

## What was not done

- **No history of snapshots**: a trend line would be nice, but it means
  accumulating API data, which the policies discourage. Revisit if a
  per-video curve turns out to matter.
- **TikTok and Instagram numbers**: their APIs need reviewed apps.
- **Feeding numbers back into generation automatically**: first there has
  to be enough data to show what a good video looks like. That is a
  person's call for now, made on this page.
