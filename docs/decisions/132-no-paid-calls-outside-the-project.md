# 132 — No money or voice credits spent outside the project's own programs

**Status:** active.

## What the owner said (23 Oct)

> real API usage and voice credits should never be spent on testing, ever.
> if tests need voice (eg to test the checks that make sure pronunciation
> is ok) then that should be got once and saved and reused. ideally new
> tests would use the same voice as other existing tests to make sure no
> new calls are made.

## What was found

The test suite already couldn't spend. `tests/conftest.py` blocks the
Claude client and every web request that isn't local.

The 10,785 voice credits recorded on 11–13 October with no channel were
voiceovers made by hand, from one-off scripts run while the voice changes
of decision 087 were being built. That is about a third of a month's
allowance.

## Decision

`core.paid`, installed when `core` is imported, refuses a billable request
before it's sent unless the program making it is one of the project's own:
the app, `main.py`, the overseer and newsroom commands, the `tools/`
scripts. A script from anywhere else, `python -c` or code piped in gets an
error instead of a bill.

**What counts as billable:**
- a Claude reply (checked in `llm.client`);
- an OpenAI picture, file or batch;
- an ElevenLabs voiceover or sound;
- a fal video.

**What stays free:** lookups like the voice list, the credits left, or a
batch's status.

**When the owner asks for a one-off paid run by hand,** `SHORTS_PAID_OK=1`
allows that run.

**Tests that need real audio** use clips recorded once and kept in the
tests' fixtures, and new tests reuse those clips and their voice. No test
needs one yet.

**The newsroom's session** now stops after eight rounds or two hours. On 22
October one stalled for twelve hours and the 04:00 run couldn't start.
