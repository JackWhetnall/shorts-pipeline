# 114 — Growth tools: linked teasers, A/B options, playlists, keywords, where viewers left

**Status:** active.

## What the owner asked

The owner agreed to "all of those things" from the growth review of 18
October:
- teasers that send viewers to the film through the Shorts "Related
  video" link;
- A/B test options for every film's title and thumbnail;
- automatic playlists and channel keywords;
- a view of where viewers leave each film.

## Decision

**Linked teasers.**
- `documentary.teasers_linked` ("Teasers link to their film") swaps the
  teaser's last-line rule from "on our channel" to "tap the link below",
  which is YouTube's own advice for the final seconds.
- The link itself is set by hand: the Data API can't set a Short's
  Related video. Each published teaser's page gets a **Link its film ↗**
  button that opens it in Studio, with the film's title in its tooltip.

**A/B options** (`thumbs.ab_variants`, made at the video stage and kept
in `<stem>_ab/`):
- three titles: the film's own, then the pitch's two next-best angles;
- three thumbnails:
  - the film's own;
  - the film's picture with the next angle's words (free);
  - a newly drawn picture of the third angle's idea (about 3¢).
- The film's page shows them with downloads, copy buttons for the
  titles, and **A/B test in Studio ↗**.
- They were made for the eleven films that already existed.

**Playlists and keywords** (`core.playlists`, run twice a day with the
audience refresh):
- A documentary channel's consent screen also asks for the `youtube`
  scope (managing the channel). Other channels' consent screens are
  unchanged.
- **Playlists:** each published film goes into one themed playlist. A
  small model call picks the playlist from the channel's own list, or
  names a new one.
- **Keywords:** the channel's keywords are written once if it has none.
- Placements are kept in `cache/playlists.json`, keyed by channel; a
  channel rename carries them over.
- Until the channel is reconnected with the scope, nothing is tried.

**Where viewers left.** A film's page shows:
- the retention curve YouTube reports, as a chart in seconds with a
  tooltip;
- the share still watching at 0:30 and at the end;
- the scenes that lost the most, with the line said over each
  (`core.retention`).

The first live curve (the ocean film) showed:
- the biggest drop at 0:08: 35.8% of viewers left over "We have never
  done that for most of our own ocean floor";
- 21% still watching at 0:30.

Along the way:
- YouTube's curve rows have three values, not two, which broke the first
  version.
- An older stray `<style>` block was moved out of the video page's title.

## TikTok and Instagram

Decision 033 assumed both platforms need an audited or reviewed app.
For the owner's own accounts, that's not the whole story:
- **Instagram:** a Meta app in development mode can publish Reels to
  the owner's own Business or Creator account without app review.
- **TikTok:** an unaudited app can post privately, leaving one tap to
  make each post public, or can send drafts to the inbox.

Both need developer apps that only the owner can register. Proposed, not
built, until they exist.
