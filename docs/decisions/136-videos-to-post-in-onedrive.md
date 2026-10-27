# 136 — The videos to post sit in OneDrive

**Status:** active. Refines 059.

## What the owner said (27 Oct)

> how do i get the videos onto my phone from my laptop. i dont want to
> have to transfer them manually every time.

Why, Though?'s TikTok posts get no views from strangers even though they're
public, and the account check is clean. As a test, the owner is posting from
the phone app instead of the website.

## Decision

The folder of videos waiting to be posted, `Shorts to post`, is now inside
OneDrive when OneDrive is set up. Otherwise it stays in `Videos`, as
before. The phone's OneDrive app then has every video, with no cable or
copying by hand.

In a synced folder each video is a copy, not a hard link, because OneDrive
doesn't upload a linked file reliably. The videos already waiting were moved
across once (`posting.move_staged`). Posted and discarded videos still leave
the folder as before. The folder stays small, about 300 MB for 25 videos.
