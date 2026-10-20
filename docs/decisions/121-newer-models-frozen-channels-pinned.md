# 121 — Newer models, the frozen channels kept on theirs; a stop-motion camera

**Status:** active. Keeps decision [075](075-long-form-pivot-and-frozen-channels.md)'s
promise that the frozen channels make exactly what they made.

## What changed

On 20 Oct the Claude dashboard recommended moving to Claude Sonnet 5.5
and Claude Haiku 5.5.
- **Sonnet 5.5** costs the same as Sonnet 5 ($2 / $10 a million tokens)
  and uses the same tokenizer. Its effort levels were recalibrated.
- **Haiku 5.5** costs a tenth of Haiku 4.5 ($0.10 / $0.50 for a prompt up
  to 100K tokens, which every call here is). It thinks by default, its
  tokenizer counts about 30% more tokens, and it refuses a sampling
  parameter or a prefill.

None of the app's request shapes uses what either model refuses: no
thinking parameter, no temperature, no forced tool.

## Decision

**Every channel but the frozen ones moves.**
- `llm.DEFAULT_MODEL` and `VISION_MODEL` are now Sonnet 5.5.
- A new `llm.FAST_MODEL` is Haiku 5.5. It replaces the nine places that
  named Haiku 4.5: picture picks, shot plans, repeat checks, picture
  checks, the editor check, social captions, music moods and retention
  lessons.

**Haiku 5.5's budget.** Its calls were sized for Haiku 4.5's answer alone:
- The cap is raised to 1.3× plus 1,500 tokens, for the thinking and the
  bigger tokenizer. Only tokens used are billed.
- A call that sets no effort runs at `low`.

**The frozen channels are pinned** (`llm.LEGACY`, `LEGACY_CHANNELS`).
- A Minute Pastor or Pub Quiz Buzz request is sent to the model it was
  made with: Sonnet 5 or Haiku 4.5.
- Haiku 4.5 refuses an effort, so none is sent. The budget is unchanged.
- The pin is found from the job's channel key, and from `llm.for_channel`
  around the frozen channels' work that runs outside a job:
  - `longform.make`
  - `quiz.top_up` (the scheduler)
  - `posting.write_social` (the publish queue, To post)
- `tests/frozen` records the requests as sent. It passes unchanged, and
  fails when the pin is taken away.
- The fact store (`pipeline/facts`) serves only the quiz channel, so it
  keeps naming its models outright.

**A stop-motion look's camera moves in steps** (`finish.stepped_filters`).
- A paper cutout moved smoothly reads as a slideshow. Moved by hand
  between photographs, it reads as stop motion.
- A look whose motion asks for a jitter (`stop_motion`, `stop_motion_rough`)
  gets its camera held on the look's cadence: 12 or 8 steps a second.
  Each step is nudged a pixel or two by a fixed pattern, so a re-render
  lands in the same places.
- Every look without a jitter (all the existing channels) moves smoothly,
  as before.

## Not done

- Effort was not re-swept on Sonnet 5.5. The app's calls are structured
  extraction at `low`, and the guidance for that is still `low`. Re-check
  if script quality shifts.
- The frozen channels move only with the owner's agreement and new
  goldens.
