# 095 — Prompt caching that pays, thumbnails, Insights by channel, a calmer Money page

**Status:** active.

## What happened

On 13 October the owner raised:
- **Teasers.** They couldn't find them: the box showed "2" and nothing
  else.
- **Thumbnails.** They seemed not to be set on YouTube.
- **Insights.** The page ignored the chosen channel.
- **The Money page.** It repeated a wordy Partner Programme note for
  each channel and had no way to add a top-up.
- **The Claude Console** said: "Your prompt cache hit rate is low".

## Findings and decisions

**Teasers.** Teasers are made only once the film's video is approved,
and both films were still waiting for a look. The section now says
"After the video's approved".

**Thumbnails were mostly set.** Pub Quiz Buzz's published videos have
their own pictures on YouTube: 11 of 12, compared image for image with
what YouTube serves.

The exception was a long quiz whose thumbnail was redrawn after it went
out. "Set thumbnails" only looked at shorts' `_cover.jpg` files, so it
was never sent again. Now:
- `publish_queue.own_picture` counts a long video's `_thumb.jpg` too;
- an upload marks the picture as sent.

The refusal YouTube gave on 9 October ("doesn't have permissions to
upload and set custom video thumbnails") is about the account's
verification, not the login. The message now says to verify by phone.

Two things that are not bugs:
- **Minute Pastor's shorts have no designed cover at all,** only a frame
  for the app's lists. So nothing was sent, and a frame is never sent as
  a cover.
- **The Shorts feed shows video, not thumbnails.** Covers appear on the
  channel page and in search.

**Insights by channel.** The page now follows the channel chosen in the
header (`web.focus`), like Review and Queued.

**Money.**
- The 8,000-hour change of 1 February 2027 is said once. Each channel
  just shows "A day to join first: N h".
- The "read twice a day" note is a tooltip.
- +$10 and +$20 buttons add to what's left (`money.top_up`).

**Caching.**
- **The problem.** 30 days of calls read only 4% of input from cache.
  The repeated context sat in the message rather than the system prompt
  (an outline sent with every chapter, the quiz rounds with every batch
  of questions), and batch calls are minutes apart, past the
  five-minute cache life.
- **A cacheable message prefix.** `llm.call_json(cache_prefix=...)` puts
  that context first and caches it whenever system and prefix together
  pass the minimum. It's used by the documentary script (the outline),
  fact intake (the rounds) and the picture editor (settings and cast).
  The text the model reads is unchanged.
- **The hour-long cache in batch mode.** It costs 2x input to write,
  recorded at that price, and pays back on the first read.
- **Checked live.** The second call read 2,871 tokens from cache and
  cost a tenth as much.
- **What can't be cached.** Prompts under the roughly 1,024-token
  minimum (bank writing, verification) aren't cacheable, and padding
  them would cost more than it saves.
