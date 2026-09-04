# 015 — Three copies of everything

**Status:** active

## What was on disk

28 GB under `footage/`, of which the pipeline read 4.4 GB.

```
old_downloads/       13.4 GB   raw originals
normalized/           5.5 GB   cropped copies, already inside the library
default_downloaded/   4.7 GB   an orphaned bulk-download batch
library/              4.4 GB   the only directory anything opens
```

Every auto-fetched clip was written three times: the raw download, the
cropped copy, and the library copy. Nothing ever removed the first two.

## Stop making them

The fetch path now downloads to a scratch directory under `cache/`,
normalizes straight into the library, and deletes the raw file in a
`finally`. One copy.

The raw file was the least worth keeping anyway. Its source URL is
recorded on the clip, so for 244 of the 264 clips in this library the
"original" is one HTTP request away — keeping 13 GB of local copies of
re-downloadable files buys nothing. `manage_library.py prune` reports
what the old flow left behind and says this, and only deletes with
`--delete`.

## Then shrink what is left

Two measurements:

- Clips average **19.8 seconds**; the renderer caps a shot at 5. **75% of
  every footage-second on disk can never appear in a video.**
- They average **6.5 Mbps**, which is a lot for material that plays
  behind burned-in captions.

`manage_library.py compact` trims to 15 seconds and re-encodes at CRF 26.
On this library that is a projected **71% reduction, 4.1 GB to 1.2 GB**;
measured on real clips it came out at 61-86% each.

**Fifteen seconds, not five.** The renderer takes a random window into a
clip, so a clip reused across videos looks different each time. Three
5-second windows keeps that; trimming to exactly one shot's length would
make every reuse identical.

**CRF 26.** Measured against the CRF 20 originals at 35.6 dB PSNR on
stone rubble — the hardest content in the library to compress — and
indistinguishable side by side.

Two things the implementation has to get right. Frame hashes are
recomputed, because they are sampled at fractions of the duration and
trimming moves those sample points; stale hashes would silently break
duplicate detection. And the new file is written to a temporary path and
only swapped in once ffmpeg has succeeded and the result is a plausible
size, so an interrupted run leaves the library intact rather than
half-truncated.

Reporting is the default. Re-encoding is lossy and cannot be undone.

## Thumbnails, while here

The footage browser's grid was extracting poster frames through moviepy
at ~2 seconds each, which made the first view of a page unusable. ffmpeg's
`thumbnail` filter does it in one pass at ~230 ms, and picks a
representative frame rather than whatever sits at a fixed offset — which
also fixed clips whose poster came out black because they open on a fade.

Sampling 30 frames rather than 150 is 2.8x faster and, measured across
this library, picks an equally good frame every time. Output is scaled to
540 px, the width the grid actually renders, instead of shipping
1080x1920 into a 292-pixel card.
