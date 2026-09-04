# 017 — Uploading to YouTube, and what that cannot mean

**Status:** active

## The constraint, first

Google's documentation for `videos.insert` states that "all videos
uploaded via the videos.insert endpoint from unverified API projects
created after 28 July 2020 will be restricted to private viewing mode."
The requested `privacyStatus` is ignored. Lifting it needs a compliance
audit of the API project — a review Google runs.

So "publish automatically to YouTube" is not something this can promise
today. What it can do is everything else: the file, the title, the
description, the tags, the category, in one click from the review queue.
The remaining manual step is flipping one switch in Studio.

That distinction is load-bearing enough to be built into the return value
rather than left in a comment. `upload()` reports the privacy YouTube
actually assigned alongside the one that was asked for, and sets
`locked_private` when they differ. The UI says so at the moment it
happens, because a video that quietly went up private is discovered days
later.

## Raw HTTP, not google-api-python-client

The official client pulls in google-api-core, protobuf,
googleapis-common-protos and more, for what is three requests here: a
token refresh, a resumable-session start, and a PUT. Every other
integration in this project — ElevenLabs, Pexels, Pixabay — is `requests`
for the same reason.

Resumable rather than a single multipart POST: these are 20-40 MB files,
and a plain upload that fails at 90% starts over.

The one subtlety is that a 308 response carries the byte range YouTube
actually holds, and the next chunk starts from *that*, not from what the
client thinks it sent. A partially accepted chunk otherwise corrupts the
upload silently. There is a test for exactly this.

## Credentials: installation-wide client, per-channel tokens

One Google Cloud project can hold the OAuth client for every channel, so
asking for it once is right; each channel is a different YouTube account,
so tokens are per channel.

Three scopes: `youtube.upload`, plus `openid email`. The last two are not
YouTube scopes and grant nothing beyond the address — they exist so the
settings page can say *which* Google account a channel is connected to.
Running several channels, connecting the wrong account is an easy mistake
and an expensive one to find late.

`prompt=consent` is explicit in the authorization URL. Without it Google
returns a refresh token only on the very first authorization ever granted
to a client, so reconnecting a channel after a revocation would yield an
access token that expires in an hour with nothing to renew it — a bug
that would appear weeks after the code was written.

## The two failure modes worth naming

A consent screen left in **Testing** expires refresh tokens after seven
days. That reads as an ordinary auth failure, and the fix is not
"reconnect" but "publish the consent screen", so the error message says
that.

`uploadLimitExceeded` is not a quota error, although it looks like one.
Quota resets at midnight Pacific; the upload limit is a cap on new and
unverified YouTube accounts and is lifted by verifying the account with a
phone number. Two different waits, so two different messages.

## Synchronous, not a job

Uploads do not go through the job queue. That queue exists to serialise
expensive generation against rate-limited APIs, one job at a time
globally — putting an upload in it would mean waiting behind a render.
An upload is a 20-40 MB PUT that finishes in seconds.

## Recording the result

A successful upload writes the returned watch URL through
`gallery.save_publish_info`, which is exactly what the manual flow does.
There is one notion of "published", so the review queue, the gallery and
`/insights` see an ordinary published video and nothing downstream needs
to know how it got there.

## Not built

TikTok and Instagram. Both need an approved developer app rather than
just credentials — TikTok's Content Posting API requires app review, and
Instagram's Content Publishing API requires a Business or Creator account
connected to a Facebook Page plus a reviewed Meta app. Neither is a
credential you create in an afternoon, and neither should be started
before YouTube is actually earning.
