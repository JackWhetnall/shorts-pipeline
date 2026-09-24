# Spec: from a pitch to a channel that publishes itself

*Draft for review, 24 Sep 2026. Nothing here is built yet except where
marked. Decisions needed are collected at the end.*

## 1. Where things stand today

### Per platform

| | YouTube | TikTok | Instagram |
|---|---|---|---|
| Upload from the app | **Built.** OAuth, resumable upload, one click in review or automatic via autopilot | Not built. Review page links to tiktok.com/upload | Not built. Review page links to instagram.com |
| What blocks full automation | Google's audit: until it passes, every API upload is forced **private** and you make it public in Studio | TikTok's audit: until it passes, every direct post is **"only me"** | Needs an Instagram **Business** account linked to a Facebook Page, a Meta developer app, and the approved `instagram_business_content_publish` permission. The API also wants the video at a **public URL** |
| Numbers read back | **Built** (views, % viewed, subs) | No | No |
| `minute_pastor` state | Connected, with stats permission. Autopilot **off**. No generation schedule | Account exists (the Revelation video was posted by hand) | Account exists (same) |

### What `minute_pastor` still needs to publish on its own

1. **A generation schedule** (dashboard → Automatic generation). Nothing is made
   unless you click.
2. **Autopilot on** (Settings → Publishing). Everything built for this is in
   place; it's off by choice, pending a week of verdicts you agree with. The
   Malachi video waiting now is the first real one the gate has judged, and it
   passed.
3. **The app running.** The scheduler, autopilot and the stats refresh all live
   inside `python -m web`. If the PC is off or the app closed, nothing happens.
   A Task Scheduler entry that starts it at login fixes this (offered, not done).
4. **Google's audit**, so uploads can be public without a click in Studio.
   Until then, "autopilot" means "uploaded privately, one click to publish".
5. **TikTok and Instagram**: entirely manual today. See §4.

### Why the current checklist feels wrong

It was written for monetisation, not for publishing. Its essentials are "a
logo", "a YouTube *link* pasted in" and "one video exists"; the rest are
Patreon, merch and affiliate links. It knows nothing about the things that
actually decide whether a channel can run: a style that has been tested, a
voice chosen, a YouTube account *connected*, a schedule, the gate's track
record, autopilot. A channel can tick every box and still never publish.

## 2. The launch pipeline (replaces the checklist)

One ordered path per channel, shown on its dashboard as a single "you are
here" with one button for the next action. **A** = the app does it. **You**
= a decision or an account step only a person can do, done at the moment it's
needed, with exact instructions inline.

| # | Stage | Who | What happens | Done when |
|---|---|---|---|---|
| 1 | **Pitch** | You | Type an idea: *"science news"*, *"daily stoic quote"*, *"maths for the curious"* | Submitted |
| 2 | **Draft** | A | One Claude call (Sonnet, ~$0.03) plus existing helpers produces a complete channel for review: 3 name options; format (topic plan vs quote list vs news feed); style prompt via the existing style picker's machinery; target length and pacing; avoid-imagery list; 3 ElevenLabs voices matched to a described voice, with their free previews; a vetted caption palette; a 25-unit topic plan outline (existing `curriculum_gen`, under a cent); the visual approach (stock / diagrams / illustration; see the footage spec) | Draft exists |
| 3 | **Review the draft** | You | One page, every part editable, each with "regenerate this part". Nothing is saved as a channel until you accept | Accepted → channel created |
| 4 | **Samples** | A | 3 script previews (existing Preview) and **one full sample video**, about $0.25 | Rendered |
| 5 | **Approve the sample** | You | Watch it. Adjust and re-sample, or approve | Approved |
| 6 | **Logo** | A then You | 4 generated options (existing), pick one | Chosen |
| 7 | **YouTube account** | You | Create the channel in YouTube (a Brand Account per channel), then Connect. The step shows exactly what to click | Connected with stats permission |
| 8 | **Schedule** | A proposes, You confirm | Defaults from the voice quota: e.g. 1 video/day at 18:00, keep 3 ready. The quota maths is shown | Confirmed |
| 9 | **Shadow run** | A | Videos are made and queued. You review each with the gate's verdict beside it. The app tracks agreement: gate passed + you published, gate held + you discarded or edited | 5 videos reviewed, gate agreed on ≥ 4 |
| 10 | **Autopilot** | You | One click, offered once the shadow run earns it | **Live** |

After *Live*, a separate **Grow** track holds what the old checklist was
really for, in order of when it becomes worth doing: TikTok and Instagram
cross-posting (§4), Google's audit, then Patreon, merch and affiliates once
`/insights` shows an audience.

**Existing channels** get placed on the pipeline from real state: Minute
Pastor lands at stage 9 (all prior steps are true), Wren's at stage 5.

**Rules carried over from the current design:** state is computed from what
is true, never a stored tick box; a stage can be marked "skip" with a
visible note; ids are stable.

### Pitch-specific content types

"Science news" is a different *source* from a syllabus: topics come from
recent events. That needs a news source. The simplest honest version is
a list of RSS feeds per channel (e.g. a science desk, press releases), with
one Claude call per video picking an item not yet covered and writing
from its summary and link. Anything fetched is attributed in the
description. This is a third `content_mode` beside `topic` and
`static_corpus`, about a day of work, and only needed if a news channel is
pitched.

## 3. The publishing queue (generate ahead, publish on time)

Today generation and publishing are one event: a video is made, then
published (or held) immediately, and the scheduler refuses to make another
while one is waiting. That couples a slow step to a timed one.

**Proposed:**

- Per channel: **publish slots** (e.g. daily 18:00, or Mon/Wed/Fri 12:00)
  and a **buffer target** (e.g. 3 ready videos).
- A video moves through: *made* → *needs a look* or *approved* (by you, or
  by the gate under autopilot) → **queued** into the next free slot →
  *published*.
- The **generator** keeps each channel's queue at its buffer target, spread
  through the day, within the voice quota. That replaces the current "don't
  generate while anything is unpublished" rule, which blocks a channel on
  one held video.
- The **publisher** uploads the next queued video at its slot. Once
  Google's audit passes, it can upload early with YouTube's own `publishAt`,
  so publishing no longer depends on the PC being on at 18:00. Before the
  audit, uploads are private regardless, so the slot is when it uploads.
- **Review becomes three tabs:** *Needs a look* (held by the gate, with
  reasons), *Queued* (with slot times, drag to reorder, pull one out), and
  *Published*. Approving in review queues a video rather than publishing
  it, unless you choose "publish now".
- Held videos never block the queue. They wait in *Needs a look* while clean
  ones keep the slots filled.

Size: medium. The state is a new `queued_for` field in each video's
publish sidecar, a slot calculator, and two scheduler duties.

## 4. TikTok and Instagram: three routes

| Route | How | Cost | Time to working | Catch |
|---|---|---|---|---|
| **A. Hand-off (semi-auto)** | For each queued video the app prepares the file, caption and hashtags, and sends it to your phone (a phone-friendly page on your network, or an email/Drive drop). You post from the TikTok and Instagram apps, where you can also add a trending sound | Free | Days | About a minute per video per platform, by you |
| **B. A posting service** | Services that have already passed TikTok's and Meta's reviews, e.g. Upload-Post (~$16–24/mo), PostPeer (~$8.50 per 1,000 posts), Ayrshare ($149+/mo). The app calls one API; they post everywhere, including YouTube | $10–25/mo at this volume | Days | A third party holds your account tokens; one more bill before there's revenue |
| **C. Official APIs, our own apps** | TikTok Content Posting API and the Instagram Graph API, like the YouTube integration | Free | Weeks: two separate app reviews with demo videos, uncertain for a personal tool. Instagram also needs a Business account, a Facebook Page and a public URL for each video | Most work, and the approval is out of your hands |

**Recommendation:** A now, because it's cheap and keeps you in the loop
while nothing is proven. Switch TikTok and Instagram to B once a channel
shows traction and the minute a day starts to matter. Skip C unless B's
terms become a problem. Any route plugs into the same queue in §3: each
platform is one "publisher" for a slot.

## 5. Build order (proposed)

1. **Launch pipeline view + placing existing channels on it** (replaces the
   checklist; no new generation). Small–medium.
2. **Publishing queue** (§3), YouTube first. Medium.
3. **TikTok/Instagram hand-off** (§4 route A). Small.
4. **Pitch → draft channel** (§2 stages 1–3). Medium. Most parts exist;
   this composes them.
5. News-feed content mode, only if a news channel is pitched.

Generated footage is its own spec (`generated-footage.md`) and can run
alongside from step 2.

## 6. Decisions needed

1. TikTok/Instagram route: A, B or C (§4)?
2. Build order above, or pitch-to-channel first?
3. Default publish slot and buffer for Minute Pastor (proposed: daily
   18:00 local, keep 3 ready)? Daily is about 30 videos, roughly 26,000
   of the Starter plan's 30,000 characters a month, which leaves little
   room for other channels or experiments.
4. Start the app at login with Task Scheduler (so all of this runs without
   you opening it)?

### Sources

- TikTok: [Direct Post API](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post), [private-only until audited](https://vorplabs.com/agent-tools/tiktok-content-posting-api), [2026 overview and alternatives](https://www.postpeer.dev/blog/best-tiktok-posting-api)
- Instagram: [Meta content publishing docs](https://developers.facebook.com/docs/instagram-platform/content-publishing/), [Reels via API, 2026](https://postproxy.dev/blog/instagram-reels-api-publishing-guide/)
- Posting services: [Upload-Post pricing comparison](https://www.upload-post.com/pricing-comparison/), [Ayrshare pricing](https://www.ayrshare.com/pricing/)
