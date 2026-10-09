# 085 — TikTok and Instagram captions written for search

**Status:** active. Amends 059 (the posting steps' captions).

## What happened

On 9 October the owner wrote:

> "ive noticed the instagram and tiktok descriptions arent really
> descriptions at all, just eg the verse number or licencing. really
> needs to be better for SEO, not explaining the video necessarily but
> being good for SEO"

Instagram got the YouTube description pasted in: a sentence, the YouTube
hashtags, "Reference: John 9:12", a music licence and ten hashtags.
TikTok got only the title and hashtags.

## What the platforms reward

**TikTok** is used as a search engine:
- It reads the caption's words, especially the first 80 to 100
  characters, to decide which searches a video belongs in.
- A natural sentence with the keyword in it beats a pile of hashtags.
- 3 to 5 hashtags work best.

**Instagram** cut hashtags to five a post in December 2025 and has made
caption keywords a search signal. Only about the first 125 characters
show before "more".

Sources:
- [trymypost](https://www.trymypost.com/blog/tiktok-seo-ranking-factors-2026)
- [capcut](https://www.capcut.com/create/tiktok-caption-keywords-discoverability)
- [wordcountertool](https://www.wordcountertool.net/blog/tiktok-caption-length-guide)
- [skedsocial](https://skedsocial.com/blog/how-to-use-hashtags-on-instagram-in-2026-hashtag-tips-to-up-your-insta-game)
- [lamplight](https://lamplightcreatives.com/captions-vs-hashtags-instagram-2026/)
- [sendible](https://www.sendible.com/insights/instagram-character-limit?hsLang=en)

## Decisions

**One Haiku call per video writes both captions** (`pipeline.social_caption`,
operation `social_caption`, about $0.003). It runs when a video is handed
off (`publish_queue.put_out`). The result is kept in `<stem>_social.json`
with the title it was written for; a retitled video goes back to the
plain caption.

The writer is given:
- a **search phrase**: a passage's reference ("John 9:12"), a quiz's
  category and "quiz", or else the title;
- the channel's own profile keywords and what it is;
- the title and what the description says about the video;
- for a passage, its spoken lines;
- for a quiz, its questions only. A quiz's spoken lines say the answers,
  so it never gets those.

Each caption:
- puts the search phrase first, inside 80 characters, in a natural
  sentence;
- follows it with a line or two of related search terms;
- has up to four hashtags, with the channel's own added last;
- uses British spelling and no dashes;
- has no "follow" or "link in bio".

A caption or hashtag that names a quiz answer is not used, and the plain
caption takes its place.

**Licence lines stay, last.** CC BY asks for a credit wherever the work
is shown, so the lines from the render report (or failing that, the
description's credit lines) go after the hashtags. There they cost
nothing in the 125 characters that show.

**The plain caption is better too.** For an older video, a failed call
or a retitled video, the caption is:
- the title and what the description says about the video (on TikTok,
  its first sentence);
- with no reference line, links or YouTube hashtags;
- with Instagram's five hashtags.

To post marks it "plain caption", with a "Write for search · $0.003"
button.

A failed write never fails a publish, because the video is already out
on YouTube by then. It's logged, and the page shows the plain caption.

Minute Pastor and Pub Quiz Buzz videos are unchanged. Only what's pasted
beside them on TikTok and Instagram changes, which is what the owner
asked for.

## Examples (the first real ones)

> John 9:12 shows a man healed of blindness who can't answer where his
> healer went. He never even saw Jesus's face. Sometimes the most honest
> answer is I don't know.
>
> #john912 #biblestudy #dailyreflection #faith #minutepastor

> Ancient History quiz time. Ten fiendish questions on Egyptian gods,
> Greek myths and Roman law. How many can you get before the clock runs
> out?
>
> #ancienthistory #quiztime #trivia #generalknowledge #pubquizbuzz

After these, the writer was told to tag a passage by its book and
chapter (#john9), not its verse number.
