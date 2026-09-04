# 004 — Match footage by meaning, not tags

**Status:** active

## Decision

Each clip carries a natural-language description, and matching is done by
a model reading those descriptions alongside the script segments.

## Why

Tag overlap was tried first and dropped. It is a controlled-vocabulary
guessing game — you have to predict every tag a future script might
search for — and it fails silently on synonyms: a clip tagged "sunshine"
against a segment asking for "sunlight" scores zero, with no signal that
the two are related.

Descriptions have no vocabulary to agree on. "Golden sunlight through a
window" matches a segment about dawn on meaning, and the same mechanism
works for "coffee" or "SpaceX" as well as for mood imagery — nothing
about it is specific to one content format.

## Confidence scoring

The model scores each candidate 1-10, and anything below the threshold is
treated as no match at all rather than a weak one. Forcing an explicit
numeric self-rating and filtering on it in code is a real mechanism;
stronger wording in the prompt alone left the model free to call a
loosely-related clip "good enough" — a generic crowd shot offered for a
segment specifically about doubt.

The threshold's history (7, then 6, then 5) was the bar chasing scores
that drifted, because the model was ranking hundreds of mostly-irrelevant
clips at once. See [007](007-shortlist-before-matching.md), which
addresses the cause. The threshold was deliberately left at 5 in that
change so the retrieval change could be evaluated on its own, rather than
two variables moving at once.

## Scale

One batched call over every description was fine at tens of clips. It is
not fine at hundreds — see [007](007-shortlist-before-matching.md).
