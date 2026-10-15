# 105 — Three films in hand, not one at a time

**Status:** active.

## What the owner saw

The autopilot was working on one film at a time. The owner wanted three
full films ready and waiting, plus their teasers.

## Why

- **`_next_film` returned a single film,** and `step` only ever tried
  that one. A film waiting for the overseer, or for the owner's look,
  made the step return having done nothing, so nothing else moved on.
- **A new film started only while fewer than `ahead` films were waiting
  for a look.** Once the owner approved a film, it stopped counting even
  though it hadn't gone out yet. In practice, then, the channel only
  started making a new film once its stock had run out.

## Decision

- **`_candidates` lists every film worth trying,** in this order:
  1. films whose teasers are due;
  2. films part-way through;
  3. the next films up in the plan.

  `step` tries each in turn and does the first thing that can be done. A
  film waiting on someone is skipped, not waited on. Films with a stage
  already in a job are left out.
- **`_in_hand` counts the films the channel has:**
  - films being made, past their angle;
  - films made and waiting for a look;
  - films approved and queued but not yet out.

  New films start until there are `documentary.ahead` of them (3 for
  Why, Though?).
- **What hasn't changed:**
  - Jobs still work one at a time, and decision 103's stepping aside lets
    several films progress while each waits on its batches.
  - Stages still start only within the channel's `hours`.
