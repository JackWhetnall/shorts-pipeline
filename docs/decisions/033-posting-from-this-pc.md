# 033 — Posting to TikTok and Instagram from this PC

**Status:** active. Replaces decision 031's phone hand-off folder.

## What happened

Decision 031 handed TikTok and Instagram posts to a phone: the video and
a caption file were copied to `OneDrive\Shorts to post`. The owner found
that clunkier than posting from the laptop the app already runs on,
where copying a description is easier. They wanted clicking "post" to
open the right pages, ideally already logged in to the right account,
ideally with the upload already there.

## What's possible

- **Fully automatic** posting needs the platforms' APIs: our own
  audited app (TikTok's audit, Meta's app review, plus an Instagram
  Business account, a Facebook Page and a public video URL), or a paid
  service that already has them (e.g. Upload-Post, around $16–24 a
  month). The service can also put a TikTok upload straight into the
  account's drafts. That is the only compliant way to have it "already
  there".
- **Filling the upload forms by script** in a logged-in browser would get
  closest for free, but both platforms' terms forbid automated access,
  and a restricted account is the wrong risk on a channel meant to earn.
  Not built.
- **Incognito with auto-login** is a contradiction: a private window is
  exactly the one that forgets logins.

## What was decided

`core/posting.py` does everything around the one step that has to be
the owner's:

- **A browser profile per channel.** Chrome keeps each profile's logins,
  so the channel's TikTok and Instagram are signed in once, in its own
  profile, and never mix with personal accounts or another channel's.
  Launching Chrome with a profile folder that doesn't exist creates it,
  so "Make a profile for this channel and sign in" is one click. It opens
  both login pages in the new profile. Existing Chrome and Edge profiles
  are listed from each browser's `Local State` and can be picked instead.
- **"Post to TikTok / Instagram"** (in review, and per video on To post)
  copies the caption to the clipboard in the click itself, where the
  browser allows it, then asks the app to open the channel's profile at
  the upload page and an Explorer window with the video selected.
  The rest is drag, paste, Post, then Done on the To post card (the link
  is optional; with one, the video counts as published there).

Everything is launched as the signed-in user from a list of arguments,
never through a shell. The app is bound to 127.0.0.1, so only this
machine can ask it to open anything.

The queue's hand-off state (`handoff` in the publish sidecar) is
unchanged. It now means "listed to post", with no file copied. The
channel flags became `post_tiktok` / `post_instagram`, plus
`posting_browser` / `posting_profile`.

## Worth revisiting

A paid posting service, once a channel's views make the minute a video
matter. The queue's `send` is where it plugs in.
