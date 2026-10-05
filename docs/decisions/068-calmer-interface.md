# 068 — A calmer interface: one look, tally lights, a channel's pages as tabs

**Status:** active. Builds on 067's Today and Money.

## What happened

On 5 October the owner asked for the whole interface to be smoother,
sleeker and more intuitive: modern and clean, without explaining every
feature, and with a structure that flows rather than one you search
around in. Going through it page by page found:

- **Gold everywhere.** The active nav item was a filled gold pill, every
  number on a stat tile was gold, every link was gold and every bare
  button was gold. With everything highlighted, nothing was: the one
  thing waiting on you looked the same as a page title.
- **A channel's pages didn't know about each other.** Overview, Videos,
  Topic plan, Settings and Profile were separate pages joined by "back to
  dashboard" links and a stray "Logo / Topic plan" row on Settings. You
  had to go back up to go across.
- **Explanations where labels belonged.** Settings' sidebar had a
  sentence under every section name; Insights explained each statistic in
  a paragraph; the Voice Lab opened with eight lines on caching. The
  explanation is often right, but it belongs in a tooltip or the decision
  log, not in front of the control.
- **Bugs that only show on screen.** Review's Approve/Discard bar stayed
  up with an empty queue (`.hidden` lost to `.review-bar`'s own display).
  Every secondary `<button>` turned gold on hover
  (`button:hover:not(:disabled)` outranks `.btn-ghost:hover`). Tables had
  no styles at all outside two pages. Hidden tooltips still counted
  towards the page's width, so the APIs page scrolled sideways.
- **Developer lines on Activity.** "[llm] footage_match: 14,751 uncached
  input tokens" was shown as a warning on finished videos; it's a log
  line, and a false alarm since 027.

## What was decided

- **One look.** A charcoal editing-suite palette rather than near-black,
  so the videos are the brightest thing on screen. One typeface, Archivo:
  expanded and heavy for titles (the lower-third voice of the videos
  themselves), normal width for reading. Loaded from Google Fonts, with
  Windows' own UI face as the fallback offline.
- **Colour means state: tally lights.** Gold is something waiting on
  you and the one primary action on a page; red is blocked or failing;
  green is running by itself; hollow is off. The same small light marks a
  Today item, a channel's status pill, a review flag and the activity
  chip. Numbers, links and the active nav item are no longer gold.
- **A channel's pages share a header and tabs**
  (`_channel_head.html`): logo, name, status pill (the same words as
  Today, now `core.today.channel_status`), "New video", and tabs for
  Overview, Videos, Plan, Settings and Profile. Back links between them
  are gone.
- **The header** keeps the five places from 067. Activity is a chip on
  the right that is always there ("Idle", or "Making 2 videos" with a
  pulsing gold light) and the occasional tools sit in one More menu,
  grouped as Library and Setup.
- **Overview** is two columns: what's happening (launch, the next videos
  going out as a run sheet, links, grow) and the facts (at a glance, how
  it's made, what it has spent). Finished launch steps fold into one
  line. Costs are grouped into what a channel pays for (voice, scripts,
  question bank, pictures, checks) by `core.costs.by_kind`, with the
  per-operation list behind "Every operation".
- **Review** filters by channel with chips that carry counts, and keeps
  the decision bar to Approve and Discard. "Mark published" moved beside
  the links it records ("Posted it yourself?", folded away); the P key
  still works. The bar hides when there is nothing to decide.
- **Copy.** Labels say what a thing is; one short line under a title at
  most; the reasoning goes in a `?` tooltip or here. Pages are named as
  the nav names them (Insights, not "How it's going").
- **Rare or destructive actions are a click away, not in the open:**
  "Make a video for every live channel" behind the channel list's ⋯ menu,
  a plan topic's rename/remove/delete-scripts behind Edit, a video's
  discard and posted-links forms folded.

## Not done, and why

- **The channel wizard and settings in tiers** from the 5 October review
  are their own pieces of work: they change what's asked and when, not how
  it looks. This pass makes them easier to build, because every channel
  page now shares one frame.
- **A light theme.** Nobody asked for one, and a second palette doubles
  every colour decision while the first is still settling.
