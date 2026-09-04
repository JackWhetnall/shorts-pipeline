# 008 — SQLite for the clip library

**Status:** active. Supersedes `footage/manifest.json`.

## Decision

Clip metadata lives in `footage/library.db`. The JSON manifest is kept as
a backup and import source, and is no longer read at runtime.

## Why

Three problems, all downstream of the metadata being one flat file:

1. **Write amplification.** Recording usage after a render loaded,
   parsed, mutated, serialised and rewrote all 320 KB *once per clip* —
   eight full round-trips for a typical video, on the machine that was
   simultaneously encoding video.
2. **Races.** Nothing locked it. A usage write racing an auto-fetch write
   could silently lose an entry.
3. **No queries.** Every consumer wanting a subset had to load everything
   and filter in Python — which is a large part of why the matcher ended
   up sending the whole library to the model.

SQLite is in the standard library, so this adds no dependency, and its
FTS5 extension provides the BM25 index that
[007](007-shortlist-before-matching.md) needs. Connections are opened per
operation, and WAL mode keeps readers from blocking on writes.

## Licence data

Made first-class in the same change. Every imported clip carried the same
"unverified — confirm before scaling/monetizing" placeholder — all 264 of
them — with no visibility short of reading the JSON by hand. For a
project whose purpose is monetization, that was the largest business risk
in the repository, and it was invisible.

`license_verified` is now a real column. Because fetches record the
licence the source publishes (Pexels and Pixabay both publish
unambiguous commercial-use terms), the import resolved 244 of 264
automatically, leaving 20 genuinely unknown hand-added clips — a number
small enough to act on, and shown on the home page.

## Dropped

The legacy `frame_hash` field: a single perceptual hash, superseded by
the multi-frame `frame_hashes` and still present on 69 entries. Nothing
read it.
