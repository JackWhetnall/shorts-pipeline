# 026 — Check originality before the voiceover, and rewrite once

**Status:** active. Changes where the similarity check from the
originality work runs, and what happens when it fires.

## What was true

`similarity.check` ran in `_finish`, after the voiceover, the footage
matching and the encode. A script that was a reworded copy of an earlier
one had already spent its ElevenLabs characters, its footage calls and
any fetch rounds before anyone learned it was a copy. Then it arrived in
the review queue with a flag, and the fix was to discard it and pay for
everything again.

That order was backwards on both counts that matter here. Originality is
the monetization case (see CLAUDE.md), and the voice allowance is the
scarcest resource (decision 025). Each check costs nothing, since it's
local arithmetic over the history file. A rewrite costs one script call,
about a cent.

## What was decided

The script stage checks the new script against the channel's history
before returning, via `_originality_gate` in `pipeline/script_gen.py`.

- **Fresh script, flagged:** it's rewritten once. The request quotes
  the closest earlier script (its first 1,200 characters) and asks for a
  different opening, angle and phrasing. **The less similar of the two is
  kept,** measured by one number, `SimilarityReport.exceedance` (how far
  past the nearer threshold the closest script sits). A rewrite can land
  nearer some *other* earlier script, so "second attempt wins" would be
  wrong.
- **Still flagged after the rewrite:** the video continues and carries
  the flag to review exactly as before. It isn't failed. A retread is
  worth a person's judgement, not an automatic loss of the script, and
  one retry is the same limit the placeholder-text check settled on.
- **Script-studio script:** checked and flagged, never rewritten. It may
  carry hand edits, and replacing it silently would undo them.
- **Resumed from a checkpoint:** the checkpoint was saved after the gate
  ran, so it isn't re-gated. `_finish` computes the report for it
  instead.

Recording into the history still happens only in `_finish`, after a
successful render, so a failed attempt doesn't become something later
scripts are compared against.
