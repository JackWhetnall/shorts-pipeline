# 059 — Posting to TikTok and Instagram as guided steps; descriptions for viewers

**Status:** active. Replaces the To post page and the hand-off buttons of
[033](033-posting-from-this-pc.md) and
[058](058-publish-by-hand-and-channel-profile.md); keeps their reason
(neither platform lets an unreviewed app post).

## What happened

The owner tried to post their first video to TikTok and Instagram:
- The To post page showed a title and two buttons. They opened the wrong
  browser profile, didn't give the video's location, and gave no title,
  description or hashtags.
- It asked for a link (optional) without saying what for.
- An Explorer window with the file selected wasn't much help either: you
  still had to find the file and drag it.

The channel descriptions written by 058 were also poor. They described
the production ("a countdown clock", "matching on-screen text",
"questions read the way an actual quizmaster would say them") instead of
why someone would watch.

## What was decided

### Steps, per platform (`core.posting.plan`, `_post_steps.html`)

Shown on the To post page and on a published video's own page, where
Publish now lands. For each of TikTok and Instagram:
1. **Open TikTok** (or Instagram) opens the upload page in the channel's
   browser profile, and copies the video's full path to the clipboard as
   it does.
2. The platform's "Select video" (Instagram: Create, Post, Select from
   computer) opens a Windows file picker. **Ctrl+V, Enter** picks the
   file: a path pasted into a file picker's name box opens that file.
   This works whatever folder the picker opens in.
3. **Copy caption** copies that platform's caption, which can be checked
   and changed on the page first.
4. **I've posted it**. The post's link can be added (optional, and it
   says what for: so the video's page links to it).

Each button writes the clipboard on the click itself, as a browser
requires.

### One plain folder (`posting.stage`, `unstage`)

A video waiting to be posted is put in `Videos\Shorts to post`, named
"Channel - Title.mp4". It's hard-linked, so it takes no extra space,
and copied only if the disk won't allow a link. The folder holds nothing
else, so even browsing to it is easy. Each video is taken out once it's
posted everywhere, or if it's discarded. Only files the app put there are
ever removed: they're recorded in `cache/staged_posts.json`.

### Captions with hashtags (`posting.hashtags`, `caption`)

The hashtags come from:
1. what the video is about (a quiz's category: #countriesquiz,
   #countries);
2. the channel's profile keywords;
3. for quizzes, #quiz #trivia #pubquiz;
4. the channel's own name, which is always included.

How many depends on the platform: 3 for YouTube (appended to the
uploaded description unless it has its own; YouTube shows three above the
title), 5 for TikTok, 10 for Instagram. The captions differ too: TikTok
gets the title and its hashtags, Instagram the title, description and
hashtags.

### Browser profiles named by who's signed in

The channel was posting from Chrome's "Default" profile. Chrome calls
that "Person 1", and it was signed in to another person's Google
account. The profile made for the channel is called "Your Chrome".
Profiles are now listed with the Google account signed in to each, and
the one the app made for a channel says "made for <channel>". The steps
say which profile they open, with a link to change it.

### Descriptions for viewers (`core.channel_profile`)

The model is no longer given the host brief. That is instructions for
writing the videos, and it was echoed back as production talk. It's
given the channel in a viewer's terms instead: what it is, its
difficulties, its subject and topics. The prompt says what to write
(what it's like to watch, who it's for) and what never to mention
(clocks, on-screen text, voices, AI, quality claims), and gives an
example of the register wanted. Any reply that still uses production
words (`LEAKS`) is written again once, keeping whichever version has
fewer.

## What was rejected

- **Dragging the file from the app's page into TikTok's.** Browsers only
  drag files out to the desktop, not into another site's page.
- **Opening Explorer at the file.** It still meant finding the file and
  dragging it; a path pasted into the picker is two keys.
- **Filling the platforms' upload forms by script.** Both platforms'
  terms forbid it (033).
