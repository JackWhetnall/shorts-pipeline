# 028 — Publishing without a person, behind a gate

**Status:** active.

## Why

The goal is a pipeline that runs without daily review. Reviewing every
video by hand caps output at whatever an hour a day allows, and a
backlog of unreviewed takes is what the scheduler already refuses to
build. But publishing unwatched AI video is exactly where a channel can
be lost rather than a video: a wrong citation on a Bible channel, a
health claim on a witchcraft channel, or an elephant procession under "a
crowd in Jerusalem" (a real render, from before decision 027's fallback
fix).

So a video publishes itself only when nothing about it asks for a person,
and the checks that decide that run on every video from the start, not
only once a channel is switched over. The review queue shows how the gate
would have called each one, so trust is built on a record before
anything is published on its word.

## What was decided

**Two new checks** (`pipeline/editor_check.py`), each one Haiku call:

- *Script*: the channel's own style prompt as the rules, the script with
  any quoted source marked as someone else's words, and a narrow list of
  what counts: factual errors, advice or promised results stated as fact,
  broken channel rules, text that isn't a spoken line, and anything unfit
  for a general audience. About $0.001.
- *Picture*: six frames sampled across the finished file (captions
  burned in), each labelled with the line spoken and the shot asked for,
  checked against the channel's avoid list. About $0.006. The frame
  times account for the title card; `assemble` records where it spliced
  it, rather than the checker re-deriving it.

Both separate `block` from `note`, and both are told that generic
background footage is fine: the point is to catch wrong, not to demand
perfect.

Calibrated on real renders before shipping: the Acts video's elephant
procession frame came back `block`; the Ezekiel script came back clean.

**The gate** (`core/publish_gate.py`) is a pure function over the
render report. It holds a video for any existing pipeline flag (degraded,
repeated or unconfident footage, a placeholder line, close wording), any
blocking check problem, and any check that didn't run. "Couldn't check"
is never "fine".

**Autopilot** (`core/autopilot.py`, per channel, off by default):
`when_clean` uploads a video that passes, through the same `youtube.upload`
and `gallery.save_publish_info` path the review button uses. Anything
else is held, with the reason written into the report for the review
queue. So is one clean video in every `spot_check_every` (default 5),
counted over the channel's clean videos so the sample is spread evenly:
the gate can only catch what it was written to catch, and a regular
sample is how anyone finds out what it misses. An upload failure, or a
channel not connected to YouTube, also holds rather than fails. The
video is paid for, and waiting in review is where it would have been
anyway.

## What was not done

- **No automatic rewrite on a blocking script problem.** It would spend
  more voice characters on a guess. A person fixes it in the script
  studio.
- **Unaudited Google projects** get every upload made private by
  YouTube. Autopilot reports that in the job notes rather than pretend
  otherwise; the fix is the audit, not code (decision 017).
- **TikTok and Instagram** are unchanged: still manual.
