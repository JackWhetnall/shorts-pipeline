# 031 — A launch pipeline, and a queue between making and publishing

**Status:** active. Replaces the launch checklist (`web/checklist.py`,
decision 019's tracking of what's left) and the per-channel "every N days
at hour H" generation schedule. Specified in
`docs/specs/launch-pipeline-and-publishing.md`.

## What was wrong

**The checklist was shaped around monetisation.** Its essentials were a
logo, a YouTube *link* pasted in, and one video existing; the rest were
Patreon, merch and affiliate links, two of which the real channel had
marked done just to get out of "Setting up". None of it was about what
decides whether a channel can run on its own: a tested style, a YouTube
account actually connected, a schedule, whether the automatic checks can
be trusted. A channel could tick every box and never publish anything.

**Making and publishing were one event.** The scheduler made a video and
then (with autopilot) uploaded it at once, whenever the render happened
to finish. And it refused to make another while any video was
unpublished, so one video held for review stopped the whole channel.
There was no way to have videos ready ahead of a good time to post.

## What was decided

**Launch pipeline (`core/launch.py`).** Seven stages in order: content,
first approved video, logo, YouTube connected with stats, publishing
plan, a shadow run where the checks must agree with you on at least 4 of
5 reviewed videos (videos the checks approved themselves don't count as
a second opinion), and autopilot. Each is computed from real state every
time; skipping is allowed (except content) and shows as skipped, reusing
`manual_checklist_overrides` so existing skips survive. After launch,
**Grow** holds TikTok/Instagram hand-off, Google's audit (the one
self-reported item), and the money links. The dashboard shows the
current stage with its action; the home page shows "Next: ...".

**Publishing queue (`core/publish_queue.py`).** A video is approved (by
you in review, or by the gate under autopilot) into its channel's queue,
state kept in its own publish sidecar. Each channel's `publishing` plan
has slot times, days and a buffer. The scheduler's tick publishes one
queued video per slot. A missed slot is made up once within 20 hours,
not in a burst, and never twice, tracked per channel in
`config/publishing_state.json`. It then starts a video whenever fewer
than `buffer` are queued, and pauses while `buffer` or more wait for a
look. No slots means "on the next check", preserving the old immediate
behaviour for anyone who wants it.

**TikTok and Instagram as a hand-off.** Neither platform lets an
unreviewed app post publicly (TikTok: "only me" until audit; Instagram:
Business account + Facebook Page + app review + a public video URL). So
"out" includes copying the video and a caption file to a synced folder
(`OneDrive\Shorts to post\<channel>`), where the phone's OneDrive app
picks it up. `/to-post` lists them until marked posted; posted
everywhere deletes the phone copy. The folder was chosen over serving
the app on the LAN, which would expose an unauthenticated app that can
spend money and delete channels. A handed-off video with no link yet
counts as out (`gallery.is_out`), so it never returns to review.

**Order and failure.** YouTube is uploaded before anything is handed
off, so a failed upload unqueues the video, puts it back in review with
the reason, and leaves nothing in the phone folder for a video that
didn't go out.

**Always running.** A logon task starts the app windowless
(`tools/start_web.pyw`), since the scheduler lives inside it.

## What was not done

- **Pitch-to-channel** (stages 1–3 of the spec): next.
- **YouTube's own `publishAt`**, which would let a video upload early and
  go public at its slot without the PC on. It needs the Google audit
  first, because unaudited uploads are private regardless.
- **A paid cross-posting service**: chosen against for now; the queue's
  "send" is the one place it would plug in.
