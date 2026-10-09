# 082 — A quiz short's thumbnail is its stamped opening screen; what thumbnail testing can be

**Status:** active for thumbnails. Thumbnail testing is decided with the owner (below).

## What happened

On 9 October the owner asked for Pub Quiz Buzz's thumbnail to be "the
opening screen when the category and difficulty have been 'stamped on
the screen'", set on the videos automatically, and retroactively if
possible. They also asked whether thumbnails can be A/B tested, with
Insights saying which performed better and the losers adjusted towards
what made the winner work.

## Thumbnails

**The moment.** The board's timeline already knows when the stamp lands
(`quiz._hook_times`). Half a second after that it has settled, and the
hook screen hasn't cleared yet. The board stage records this as
`thumbnail_at` in the round's sidecar.

**Shorts made before this** work it out from the script kept beside
them: the hook's last word is its segment's end less the pause, then the
stamp lands 0.15 s later and settles 0.55 s after that. The 12 older
shorts with no stored script are scanned instead: frames from 1 to 7
seconds, taking the first where the stamp's band of the screen is as full
as it gets. On one where both methods could be used, the scan found 3.6 s
against the recorded 3.63 s. The oldest shorts have no hook screen; for
them, the scan finds the opening board, which shows the category and
difficulty and is the nearest thing.

**The files.** The frame is saved as `<stem>_cover.jpg`, under YouTube's
2 MB limit, and also replaces the app's poster frame. It's set on YouTube
when the short goes out. A short already out gets it from the channel's
Videos page ("Set N thumbnails on YouTube"), and a cover changed since it
was set is offered again. The record of when it was set is its own
sidecar (`<stem>_cover.json`): the publish sidecar's loader keeps only
the fields it knows.

**Pub Quiz Buzz is frozen** (decision 075). This changes what it makes,
at the owner's request, so its goldens were regenerated. The differences
were only the new cover, its moment in the sidecar, and the poster.

## What thumbnail testing can be (checked 9 Oct 2026)

- **Custom thumbnails for Shorts** came to YouTube Studio, desktop only,
  in July 2026. The Data API's `thumbnails.set` documents nothing about
  Shorts, so whether it applies one to a Short is unknown until it's
  tried. The first "Set thumbnails on YouTube" is that test.
- **YouTube's own A/B test (Test & Compare)** works only for long
  videos. It runs only in Studio and isn't in the API. It shows up to
  three thumbnails at once and judges them by share of watch time. It
  isn't available for Shorts.
- **Thumbnail impressions and click-through** aren't in the Analytics
  API. The bulk Reporting API has them per video per day
  (`channel_reach_basic_a1`: `video_thumbnail_impressions`,
  `video_thumbnail_impressions_ctr`), under the read-only analytics scope
  the app already asks for, about two days behind.

So an automatic test can only be sequential: one thumbnail for a few
days, then the next, compared on click-through. That's noisy at low
impressions, and confounded by a video's age, since a new video's first
days are its subscribers'. For Shorts, the feed plays the video rather
than showing a thumbnail, so a thumbnail mostly matters on the channel
page and in search.
