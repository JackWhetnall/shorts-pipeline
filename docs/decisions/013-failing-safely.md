# 013 — Failing safely

**Status:** active

## What happened

A real generation died at the footage stage:

```
[3/5] Matching footage for 15 shot(s) across 4 segment(s)...
  [llm] footage_match: cached 14,119 tokens for reuse ($0.07)
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

The call succeeded. Usage was recorded. And then `json.loads("")` failed,
because `response.content` held a thinking block and no text block at
all.

On current models thinking is on by default and is billed out of the same
`max_tokens` budget as the answer. Scoring 50 clips against 4 segments is
a lot to reason about, and the budget was 3000 — so reasoning consumed
all of it, `stop_reason` came back `max_tokens`, and there was no answer
to parse.

The script and the voiceover for that video had already been generated
and paid for. Both were thrown away.

## Three separate mistakes

**A budget that didn't account for thinking.** 3000 tokens for the most
demanding call in the pipeline. The vision call that describes footage
was worse at 250 — it had not yet been exercised, but the first
auto-fetch would have written empty descriptions into the library,
silently poisoning every future match for those clips.

**Trusting `content` without checking `stop_reason`.** A schema
guarantees the shape of a *completed* answer and says nothing about
whether the answer arrived. Structured outputs replaced an older
ask-for-JSON-and-retry loop, and in doing so removed a safety net without
replacing it.

**Treating a recoverable failure as fatal.** A scoring call failing is
annoying. Losing a script and a voiceover because of it is expensive, and
the pipeline had no way to express the difference.

## The decision

**Budgets cover reasoning as well as output.** 8000 by default, 12000 for
footage matching, 2000 for vision. A large ceiling costs nothing — you
pay for tokens used, not tokens allowed — while one too small is a failed
render that has already paid for everything upstream. `effort` is set
explicitly (`low` for extraction, `medium` for scoring) so thinking is
bounded rather than open-ended.

**Every response is checked before it's trusted.** `stop_reason` first: a
truncated response retries once with triple the budget, and a refusal is
never retried, because identical input gets an identical refusal and
costs twice as much. Text blocks are joined rather than taking the first,
since an answer can arrive split.

**Failure cost is proportional to what is recoverable.** `TruncatedResponse`
and `RefusedResponse` are their own types so callers can respond
differently. The footage matcher catches them and falls back to
recency-ordered picks from the same lexical shortlist — a weaker video,
flagged as such, rather than no video. `RenderPlan.footage_degraded`
carries that fact to the render report, the job warnings, and the review
queue, so nobody publishes a degraded video thinking it had the usual
treatment.

The same reasoning covers three other paths:

- A clip whose file has gone is substituted before the render starts,
  rather than discovered inside moviepy a minute in.
- The local transcript check returns "pass" when the model can't be
  loaded, instead of failing a render over a quality check — and reports
  its unavailability once rather than per segment.
- One unreadable channel directory no longer empties the review queue for
  every other channel.

## Testing this without spending money

Every test is mocked. `tests/test_failure_modes.py` constructs the exact
SDK response shapes locally — thinking-only, empty, refusal, split text,
malformed — and asserts the handling. `tests/test_end_to_end.py` runs the
whole pipeline with Claude and ElevenLabs replaced by canned responses
and locally-generated silence, over footage made by ffmpeg's own test
pattern. The render is real, because that step costs nothing and is the
one most likely to break silently.

The failure-mode suite was mutation-tested: removing the `stop_reason`
check fails three tests, and reverting to first-text-block-only fails
five. A suite that passes against a broken implementation is worse than
none.

## Preventing the next one of these

The SDK ships generated TypedDicts describing what the API accepts, so
requests can be validated locally rather than by sending them. There is
now a test that checks every `effort` value against the SDK's own
`Literal`, every `output_config` key against `OutputConfigParam`, and
every JSON schema for keywords the API rejects.

That last one would have caught the other 400 in this same area:
`minItems: 3`, which is invalid because array bounds other than 0 or 1
are unsupported. Both bugs were requests this code built wrongly, and
both were checkable offline.
