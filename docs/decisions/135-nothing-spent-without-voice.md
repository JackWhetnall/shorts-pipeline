# 135 — Nothing spent on a video that can't be voiced; TikTok's AI label

**Status:** active.

## What the owner said (27 Oct)

> im worried that we still have API calls and cost for videos that are
> clearly not going to succeed. please can we make sure that we dont spend
> any money on these videos that are doomed to fail until out voice credits
> refresh.

## What had been spent

The credits ran out on 22 Oct. Since then about $7.26 has been spent. Of
that:
- about $7.10 went on the six newsroom films' storyboards and their checks.
  These are kept and will be voiced after the 7 Nov reset, so they weren't
  wasted;
- the rest was cents, mostly captions.

The jobs that failed at the voiceover stopped at its check, before paying for
anything. Only one Minute Pastor script was lost, at $0.008.

## The gaps, now closed

- **When the quota couldn't be read, the app assumed there was room.**
  `voice_quota.current` treated a network blip as "unknown, so go ahead",
  so videos started that could only fail. Now each quota read is kept
  (`cache/voice_quota_last.json`). While ElevenLabs can't be reached, the
  last read quota stands until its reset date. A key that has never been
  readable stays "unknown", as before.
- **The autopilot spent on films it couldn't voice.** It drew storyboards
  and made teasers for films with no credits to voice them. Now no paid
  step starts unless the film could be voiced now
  (`auto_films._voice_for`). The check uses the narration the film still
  needs, or a typical video's before that is written, and the channel
  order of decision 134. Approvals are free, so they still go ahead.
- **Long quizzes had no voice check.** Quiz nights and category quizzes
  now check, as the shorts already did.

Frozen channels make exactly what they did. They wait for credits sooner.

## TikTok

Why, Though? and Pub Quiz Buzz were getting exactly zero views on TikTok.
Videos with an AI voice and AI pictures need TikTok's AI-generated content
label. TikTok can also find unlabelled AI content itself, and an account
whose posts are kept out of the For You feed gets exactly this result. So
the posting steps now include turning the label on, and TASKS K1–K3 ask
the owner to look at each account's status.
