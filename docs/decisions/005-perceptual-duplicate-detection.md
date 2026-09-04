# 005 — Multi-frame perceptual duplicate detection

**Status:** active

## Decision

A clip counts as a duplicate only if **every** sampled frame's average
hash matches within 6 bits of 64 **and** the durations are close.

## Why

Overlapping searches, and Pexels and Pixabay both indexing the same
underlying footage, make re-downloads common. Catching them before the
vision describe call saves a real API cost, and it is also what stops the
same physical clip being assigned to two shots in one video.

## The incident

The first version compared a single mid-clip frame. Two completely
unrelated clips — a crowd shot and a wave shot — happened to share a
similar coarse bright/dark layout at that one sampled moment and were
identified as duplicates. Genuinely distinct footage was very nearly
deleted.

Requiring agreement across every sampled frame plus a similar duration
makes that essentially impossible: two different videos coincidentally
matching at all sample points *and* running the same length does not
happen. True duplicates — the same source re-encoded or re-exported —
still match throughout.

## Auto-deletion

The audit only auto-deletes within a **full clique**: every clip in the
group matches every other one directly. A group that is merely connected
(A matches B, B matches C, but A and C do not match) is reported as
ambiguous and left alone, because that chained shape is exactly what
produced the false positive.
