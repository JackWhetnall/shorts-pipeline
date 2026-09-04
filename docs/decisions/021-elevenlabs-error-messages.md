# 021 — "Check your API key" was a guess, and usually the wrong one

**Status:** active

## What happened

A real job died in the voiceover stage:

```
core.errors.ExternalServiceError: HTTP 401
```

surfaced to the UI as *"ElevenLabs rejected the request — check that
ELEVENLABS_API_KEY is set correctly."*

The key was fine. Querying the real API directly with it showed two
separate, genuine rejections, neither about the key:

```
401  {"detail": {"code": "quota_exceeded",
                 "message": "This request exceeds your quota of 10000.
                 You have 0 credits remaining, while 2 credits are
                 required for this request."}}

402  {"detail": {"code": "paid_plan_required",
                 "message": "Free users cannot use library voices via
                 the API. Please upgrade your subscription to use this
                 voice."}}
```

A spent monthly quota, and a free-tier restriction on using premade
"library" voices through the API at all — a structural limit that applies
regardless of quota. Both are account-level facts ElevenLabs already
states in the response body. The pipeline was discarding that message and
substituting a guess.

## Why the guess was there

`_post_with_backoff` treated every 401/403 as the same failure and picked
the most common cause of that status code in general. It is not the most
common cause *for this API*: ElevenLabs overloads 401 for quota
exhaustion specifically, which is unusual enough to be worth knowing
about the vendor rather than assuming.

402 was not handled at all. It fell through to `response.raise_for_status()`
and would have crashed as a raw `requests.HTTPError` with no
`user_message` — the exact kind of bare exception this project's own
conventions forbid, just not the one that happened to get hit that day.

## The fix

`_rejection_error` reads ElevenLabs' own `detail.code` and `detail.message`
— the same pattern `voice_lab.refresh_voices` already used for its own
401 handling — and answers three cases instead of one:

- `quota_exceeded` → says the account is out of quota, quotes ElevenLabs'
  own numbers, says to upgrade or wait for reset.
- `paid_plan_required` → says the free plan can't use that voice via the
  API, says to use a voice the account owns or upgrade.
- anything else → the original "check your key" guess, now correctly
  scoped to the case it was actually written for.

None of this needed a new HTTP status to be added to the retry loop
except accepting 402 into the same branch as 401/403 — quota and
plan-tier rejections are not transient, so retrying them is pointless in
the way retrying a 429 is not.

## The general lesson

A generic message for a specific vendor's specific status code is a bet
that the vendor uses that code the way most APIs do. When the vendor's
own error body is sitting right there in the response — as it is here,
and was already being read correctly in the sibling function that lists
voices — reading it costs nothing and turns a wrong guess into the actual
answer.
