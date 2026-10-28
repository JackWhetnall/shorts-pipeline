# 141 — Phone copies per channel, and notifications

**Status:** active. Refines 140.

## What the owner said (28 Oct)

> the send to phone button is too big and not part of the normal posting
> workflow ... it should be smaller and separate from the others (and just
> an icon with a tooltip ideally. also its is currently unclear if
> accidentally clicking that button will move the video ... also it is
> unclear if clicking the button again will undo this. also if i do want
> to start posting from my phone, i should have a setting for the given
> channel ... and then they should be sent there automatically (JUST FOR
> THIS CHANNEL). I then would want the video to still be available to post
> from laptop anyway.

> it would also be good if i got notified on my phone whenever a video
> gets posted, and other updates/breakdowns ... there are things like the
> teasers being published, and i need to link the main video to the
> teaser, but there is no notification if or when this has happened and
> what is needed

## Phone copies

**The control:** a small phone icon at the top right of each video's
posting steps, away from the copy buttons. Clicking it toggles a second
copy in `OneDrive\Shorts to post`, and clicking again removes that copy.
The tooltip says the PC's copy stays. When the video is on the phone, the
icon is lit.

**Per channel:** `publishing.phone_copies`, shown in the channel's
settings as "Copy each to the phone too" or "Copy teasers to the phone
too". Every video that channel hands off for TikTok or Instagram is then
copied to OneDrive as well. The PC copy in `Videos\Shorts to post` stays
as it is, so either device can post it. The copy goes once the video is
posted everywhere or discarded. It's off by default, so the frozen channels
are untouched.

## Notifications

Notifications are sent through **ntfy**, a free phone app that needs no
account (`core.notify`, run each scheduler tick). The owner chooses a
topic on the Phone page, subscribes to it in the app and sends a test.
Nothing is sent before a topic is chosen. Anyone who knows a topic can
read it, so the suggested topic is long and random.

There are four kinds, each on or off:
- **Each video out:** on YouTube, or marked posted on TikTok or Instagram.
  For a teaser on a channel that links its film (decision 114), it says
  "In Studio, set its Related video to …", and tapping opens that teaser's
  Studio edit page. If the film isn't out yet, it says to do it once it is.
- **Something needs you:** each new item on Today's Needs you.
- **Morning summary,** at 08:00:
  - what goes out today;
  - what's to review and what's queued;
  - what's still to post on TikTok and Instagram;
  - the voice left.
- **Monday: the week:** last week against the week before (decision 139).

The first run marks everything already there as seen, so nothing old
arrives in a burst. Each item is sent once. Tapping a summary opens the
app on the phone when phone access is on.

Tests never send: the settings and state files are moved aside in every
test.
