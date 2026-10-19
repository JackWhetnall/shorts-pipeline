# 116 — Instagram posts by itself; TikTok stays a few clicks

**Status:** active. Corrects decision [033](033-posting-from-this-pc.md)'s
reading of what Instagram allows. TikTok's steps from decision
[059](059-posting-steps.md) are unchanged.

## What the owner said

"The TikTok/instagram posting is still annoyingly manual. Why didn't we
implement the private upload features to save us clicks?" Then, after
being told what each platform allows, they asked for full setup
instructions, with as much of the work as possible done for them.

## What each platform allows, checked this time

Decision 033 assumed both platforms needed an audited, reviewed app
before anything could be posted for you. That was never checked, and for
Instagram it's wrong.

**Instagram:** Meta's "Standard Access" covers an app used only by the
people with a role on it, with no App Review and no business
verification. An app that serves only its developer's own professional
accounts needs nothing more: tokens from the app dashboard, no login flow
([Instagram Platform overview](https://developers.facebook.com/docs/instagram-platform/overview)).
Instagram's API has two sides, though:
- **Instagram login:** no Facebook Page is needed, but a video is only
  taken from a public web address (`video_url`). Uploading a file
  ("resumable upload", `rupload.facebook.com`) is "available only for
  apps that have implemented Facebook Login for Business"
  ([resumable uploads](https://developers.facebook.com/docs/instagram-platform/content-publishing/resumable-uploads/)).
- **Facebook login:** the Instagram account must be linked to a Facebook
  Page, and the file goes straight up from this PC.

The videos are on this PC, so it's the Facebook side.

**TikTok:** worse than the owner was first told.
- An unaudited app's posts are private (`SELF_ONLY`), and "unaudited
  clients can only post to a private account": the whole account has to
  be private when it posts
  ([Direct Post reference](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post)).
  Making each video public afterwards would mean flipping the account to
  private and back, which takes more clicks than posting by hand.
- The audit that lifts this lists "a tool to help upload contents to the
  account(s) you or your team manages" as not acceptable
  ([content sharing guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines)).
- Uploading a draft to the TikTok app's inbox needs no audit, but it
  can't carry a caption, it's finished on the phone, and an app for your
  own accounts would be using a sandbox meant for testing.

## Decision

### Instagram (`core/instagram.py`)

**Connecting, once for every channel.**
- The owner makes a Meta app (Business type, left in development mode)
  and pastes its ID and secret on **Instagram setup**. They're kept in
  `config/instagram.json`, outside version control, or taken from
  `META_APP_ID` and `META_APP_SECRET`.
- They then paste one user token from Meta's Graph API Explorer, with
  five permissions: `instagram_basic`, `instagram_content_publish`,
  `pages_show_list`, `pages_read_engagement` and `business_management`.
  The last is there because a Page held in a business portfolio is only
  listed with it.
- `connect` swaps the token for a long-lived one, then lists the Pages.
  Each Page's own token, which doesn't expire, is kept with the
  Instagram account linked to that Page.
- Each channel picks its account in Settings, stored as
  `publishing.instagram_account`. It lives in the channel's own settings,
  so a rename carries it.
- Tokens go in a header, never a URL. A failed request's message would
  otherwise carry its URL into the log, and the token swap and paging
  links have secrets in theirs (`_redacted`).

**Posting, on each scheduler pass** (`post_due`, straight after
publishing). A Short or teaser handed off to Instagram when it went out
(`publish_queue.put_out`) goes through these steps:
1. It's copied with its index at the front, as Instagram's Reels rules
   ask, and its sound re-encoded at 128 kbps. The picture is untouched.
2. It's uploaded into a container with its Instagram caption.
3. It's published once Instagram has finished processing it. A pass
   waits up to a minute for that, and the next pass picks up where it
   left off.
4. It's marked posted with its link (`publish_queue.mark_posted`),
   exactly as if posted by hand.

**Never twice.** Each step's state is in the video's publish sidecar
(`handoff.instagram.auto`):
- The container is saved before the upload. A restart picks it up again
  rather than making another.
- A container Instagram reports as already published is recorded, not
  published again. Its link is found by its caption.
- A container still processing after 30 minutes is given up and never
  published.
- One lock covers every step, so the scheduler and a "Post it for me"
  can't both start one Short. A restart waits for it (`instagram.busy`).

**No flood.** Only Shorts handed off, asked for, or started in the last
two days go by themselves. Connecting doesn't post the 33 already waiting
in To post: each of those has **Post it for me**.

**Failures cost what they should.**
- A busy Instagram (rate limits, server errors, no connection) is tried
  again at the next pass and not counted.
- A lapsed or refused connection is shown on Instagram setup and on the
  Short. It waits for the reconnect without counting either.
- Anything else counts. After three, the Short is left to the owner with
  Instagram's own words for why, a **Try again** button and the steps by
  hand.

**What the owner sees.**
- On To post and the video's page, Instagram shows **Posting by itself**,
  **Posted** with its link, **Didn't post** with the reason, or **Post it
  for me**.
- The menu's To post count leaves out what Instagram is already doing
  (`awaiting_posts`' `by_itself`).

**A teaser says where its film is.** Its spoken ending sends viewers to
"our channel", which on TikTok or Instagram isn't where the film is.
Both captions now end with "Full video on YouTube: <channel>", before the
hashtags (`posting.full_video_line`). Only teasers get it, so the frozen
channels' captions are unchanged.

### TikTok

It stays as decision 059's steps, about 30 seconds a teaser. The
long-form settings page can now make the channel's browser profile, so
Why, Though?'s TikTok opens signed in as the channel. A paid posting
service with an audited app is the only automatic route.

## Rejected

- **Instagram login with a public address for each video:** it needs
  somewhere public to put the file, such as a tunnel, cloud storage or a
  file host. That's a moving part, a cost or an exposure, all to avoid
  making one Facebook Page.
- **The app's own Facebook sign-in instead of the Explorer token:** it
  needs a redirect address registered in the Meta app's login settings,
  one more console step to get wrong. The Explorer is one paste, once.
- **TikTok private posts, or drafts in its inbox:** see above.

## Worth revisiting

- Posting Reels to each channel's Facebook Page too: the Page token
  already allows it.
- A posting service for TikTok, once TikTok brings real views.
