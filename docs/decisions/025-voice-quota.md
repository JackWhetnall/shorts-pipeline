# 025 — The voice allowance is the limit, so read it

**Status:** active. Qualifies the "spend, never a balance" rule in
`core/services.py` for one provider.

## What was true

The `/apis` page reports what this installation has spent and never a
balance, on the grounds that no provider exposes one to an ordinary API
key. For money that holds. ElevenLabs is different: a subscription is a
character allowance per billing period, and `GET /v1/user/subscription`
returns `character_count`, `character_limit` and the reset time to any key
with the `user_read` permission.

On the Starter plan that allowance, not the Claude budget, limits how many
videos can be made. Jobs have averaged about 850 characters each,
retries included. A month's allowance runs to a few dozen videos, and
two channels at one video a day can exhaust it. Every Voice Lab test and
every "Listen" in the style picker spends from the same allowance.

Running out was only discovered when ElevenLabs refused a request
(decision 021). By then the script was paid for, and any segments that
got through before the refusal were billed for a voiceover that could
never be finished.

## What was decided

`core/voice_quota.py` reads the allowance and uses it in three places:

- **Before the voiceover.** `tts.run` works out the characters one clean
  pass of the script will cost and raises `VoiceQuotaExhausted` if the
  allowance can't cover it. The script is checkpointed, so retrying the
  job after the reset doesn't pay for it again. This read is always
  fresh.
- **Before a scheduled run.** The scheduler skips a due channel whose
  typical video won't fit, without stamping `last_run_at`, so the channel
  stays due and runs once the allowance resets. "Typical" is the median
  characters per job for that channel from the cost log (1,000 until
  there's history).
- **Where you look.** `/apis` shows remaining, limit, reset date and
  roughly how many videos that is. The home page shows the same thing as
  a banner once fewer than five videos' worth remain.

**Unknown never blocks.** A key without `user_read`, a network error or
no key at all all mean "can't tell", and nothing is refused on a number
that couldn't be read. ElevenLabs' own `quota_exceeded` response is
still the backstop. The page says which permission to add to get the
number.

The check doesn't reserve headroom for retries. A transcript-triggered
retry can still push a video over the edge; decision 021's message
covers that case, and a margin would refuse videos that would have fit.
