# 112 — A film and its teasers cost as one output

**Status:** active.

## What happened

- **Films cost $0.00 on Insights.** Why, Though?'s films showed as
  costing nothing. A short's cost is written beside its video
  (`_cost.json`); a film's is only in the cost log, under its production
  id, so Insights found nothing.
- **Teasers were counted as videos of their own.** The owner's rule: a
  film and its teasers are one output.
- **"Total recorded" ignored the channel dropdown.** It added up every
  channel.
- **Spend was mislabelled.** Everything unaccounted for was called "runs
  that failed before a video was made", including films still being made.
- **A tooltip was unreadable.** The "Per published video" tooltip was
  cut off by its stat strip's `overflow: hidden`.
- **Activity never showed batch waits.** The Activity feed
  (`_for_activity`) dropped `waiting` and `waiting_since`, so decision
  109's "Waiting on batch · 7 h" label never showed.

## Decision

**Costs per output:**
- `insights._outputs` treats a short as one output, at its own cost.
- A film and its teasers are one output, costed from every cost record
  carrying that film's id (`_film_costs`).
- Spend is read only for the channels being looked at.
- Films still being made are shown on their own line ("Films still being
  made") and left out of "per published".
- What's left is "Not tied to a video": tests, previews and failed runs.

**Page fixes:**
- Stat strips no longer clip; their end tiles carry the rounded corners.
- The Activity feed carries `waiting`, `waiting_since` and `film`.

## Known gap

About $40 of picture and voice spend from 30 September to 13 October has
no channel or film on it. It came from stages run outside the app's jobs
while the documentary pipeline was being built, and there is nothing to
trace it back by. It counts under "All channels" as "Not tied to a
video".

Today's teaser test drafts and remakes ($1.32, also run outside a job)
were tagged by hand with their channel, since several were throwaway
tests that belong to no single film.
