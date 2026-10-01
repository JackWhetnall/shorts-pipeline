# 058 — Publishing by hand in one click, and a channel's profile

**Status:** active.

## What happened

Publishing the first quiz video by hand was awkward:
- An approved video's own page had a "Publish video" button that only
  scrolled down to boxes for pasting links in. It showed no title and no
  description to use.
- Everything needed already existed on the Review page (title and
  description fields, an Upload to YouTube button, TikTok and Instagram
  buttons), but not where an Approved video leads.
- The YouTube upload there didn't open TikTok or Instagram, so each
  platform was a separate trip.
- Finding the file to upload by hand meant knowing the date of its folder
  and picking the right mp4 from among its sidecars, with no sign of
  whether it was discarded.

And setting up the socials meant writing the same pitch several times,
remembering every link, and making a YouTube banner somewhere else.

## What was decided

### Publish now (`publish_queue.publish_now`)

The scheduled send and the manual publish are now one function,
`put_out`: upload to YouTube through the API (never twice, so a video
with a YouTube link isn't uploaded again), then hand off to TikTok and
Instagram. `send` (the schedule) wraps it with its own failure handling
(back to review, with the reason); `publish_now` raises the error to the
person instead.

- **Where:** the video's own page and the Review page both have it, with
  the title and description in editable boxes, copy buttons, a privacy
  choice, **Show the file** and **Download**.
- **What it does, from this PC:** saves the title and description,
  uploads to YouTube, and, for TikTok and Instagram, opens their upload
  pages in the channel's browser profile with the video selected in
  Explorer. The caption was put on the clipboard on the click itself,
  because a browser only allows that during the click.
- **Which platforms:** the ones the channel's plan posts to. A channel
  with a posting browser profile but no plan gets both when you publish by
  hand, since it's you asking.
- **From a phone:** nothing is opened on the PC. The video waits in To
  post.
- **If YouTube refuses it:** nothing is handed off or marked published.
  Without YouTube connected and nowhere else to send it, it says so
  rather than failing.
- **Finding the file:** **Show the file** opens its folder with it
  selected. Downloads are named after the title, not the file stem.

### Channel profile (`core/channel_profile.py`, `core/banner.py`)

A **Channel profile** page (the first step of a channel's "grow"
checklist) holds what to paste into each platform:
- **Written by the model** (one call, about a cent, from the channel's
  name, host brief and topics): a tagline, the YouTube About text, a
  TikTok bio (80 characters), an Instagram bio (150) and channel
  keywords. Each is held to its platform's limit, cut at a word. They are
  stored in `channels/<key>/profile.json` and are the owner's to edit.
- **Never written by the model:** the links. They're taken from the
  channel's settings each time it's shown: where it lives (YouTube,
  TikTok, Instagram), and how to support it (Patreon, merch, affiliate
  links, with the Amazon Associates disclosure those need). Missing ones
  are listed with a link to where to add them. A model that writes a URL
  can get it wrong, and a stored one goes stale.
- **A YouTube banner**, drawn locally from the channel's own logo,
  colours and typeface (no image model, so free, instant, and the name is
  always spelled right), in two layouts. It's 2560x1440 with everything
  that matters inside the middle 1546x423, which is all a phone shows.
  It's redrawn when the tagline changes.

## What was rejected

- **Opening Explorer once per platform.** One window, with the file
  selected, serves both.
- **Having the model write the links.** See above.
- **An image model for the banner.** About $0.04 a try, misspells names,
  and it can't be redrawn when the tagline changes.
- **Posting to TikTok or Instagram automatically.** Neither lets an
  unreviewed app (decision 033); the aim here is that the owner has
  everything open and ready, with the caption on the clipboard.
