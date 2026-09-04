"""
Shrinking the library without changing what it can do.

Two measurements drove this. The clips average 19.8 seconds while the
renderer caps a shot at 5, so 75% of every footage-second on disk can
never appear in a video. And they average 6.5 Mbps, which is a lot for
material that plays behind burned-in captions.

Trimming to 15 seconds keeps three distinct 5-second windows — the
renderer picks a random one, so a clip reused across videos still looks
different — and re-encoding at CRF 26 measured 68-82% smaller on real
clips at 35.6 dB PSNR against the original. That was on stone rubble, the
hardest thing to compress; a side-by-side is indistinguishable.

Together: about 65% of the library, reclaimed.

Two things this has to get right. Frame hashes are recomputed, because
they are sampled at fractions of the duration and trimming moves those
sample points — stale hashes would quietly break duplicate detection. And
the original is only replaced once the new file is written and verified,
so an interrupted run leaves the library intact rather than half-empty.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg

from core.logging_setup import get_logger
from core.paths import CACHE_DIR, LIBRARY_DIR
from pipeline.footage import intake, store

log = get_logger(__name__)

# Three 5-second windows. Below this the renderer starts showing the same
# framing whenever a clip comes up twice.
DEFAULT_MAX_SECONDS = 15.0

# Measured indistinguishable from the CRF 20 originals on the most
# detailed clips in this library.
DEFAULT_CRF = 26

# Don't bother rewriting a clip that is already small and short — the
# re-encode would cost quality for a saving too small to notice.
MIN_SAVING_BYTES = 512 * 1024


@dataclass
class Candidate:
    clip: object
    before: int
    after: int = 0

    @property
    def saved(self) -> int:
        return max(0, self.before - self.after)


def _estimated_after(clip, size: int, max_seconds: float, crf: int) -> int:
    """What this clip would come to. Size scales with duration, and the
    CRF step is calibrated from real encodes of this library."""
    scale = min(1.0, max_seconds / clip.duration) if clip.duration else 1.0
    quality_factor = {20: 1.0, 22: 0.80, 24: 0.62, 26: 0.45, 28: 0.33}.get(crf, 0.45)
    return int(size * scale * quality_factor)


def plan(max_seconds: float = DEFAULT_MAX_SECONDS, crf: int = DEFAULT_CRF,
         db_path=None) -> dict:
    """What compacting would do, without doing any of it."""
    candidates, skipped, total_before = [], 0, 0
    for clip in store.all_clips(db_path=db_path):
        path = LIBRARY_DIR / clip.filename
        if not path.exists():
            continue
        size = path.stat().st_size
        total_before += size
        estimate = _estimated_after(clip, size, max_seconds, crf)
        if size - estimate < MIN_SAVING_BYTES:
            skipped += 1
            continue
        candidates.append(Candidate(clip=clip, before=size, after=estimate))

    return {
        "candidates": candidates,
        "skipped": skipped,
        "total_before": total_before,
        "estimated_after": total_before - sum(c.saved for c in candidates),
        "estimated_saving": sum(c.saved for c in candidates),
    }


def compact_clip(clip, max_seconds: float = DEFAULT_MAX_SECONDS,
                 crf: int = DEFAULT_CRF, db_path=None) -> int:
    """Rewrite one clip in place. Returns bytes saved (0 if skipped).

    Writes to a temporary file first and only swaps it in once ffmpeg has
    succeeded and the result is a plausible size, so an interrupted or
    failed run can never leave a truncated clip in the library.
    """
    source = LIBRARY_DIR / clip.filename
    if not source.exists():
        return 0
    before = source.stat().st_size

    work_dir = CACHE_DIR / "compact"
    work_dir.mkdir(parents=True, exist_ok=True)
    temp = work_dir / clip.filename

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg, "-y"]
    if clip.duration and clip.duration > max_seconds:
        command += ["-t", str(max_seconds)]
    command += ["-i", str(source),
                "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-an", "-movflags", "+faststart",
                "-loglevel", "error", str(temp)]

    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0 or not temp.exists():
        log.warning(f"  [compact] {clip.filename} failed: "
                    f"{result.stderr.decode(errors='replace')[-200:]}")
        temp.unlink(missing_ok=True)
        return 0

    after = temp.stat().st_size
    # A result that is suspiciously tiny means the encode went wrong in a
    # way ffmpeg didn't report. Keep the original.
    if after < 10_000 or after >= before:
        temp.unlink(missing_ok=True)
        return 0

    temp.replace(source)

    # Re-measure. Duration changed if it was trimmed, and the frame
    # hashes are sampled at fractions of the duration — leaving the old
    # ones would break duplicate detection silently.
    try:
        clip.duration = intake.clip_duration(source)
        clip.frame_hashes = [intake.frame_hash(f) for f in intake.extract_frames(source)]
        store.upsert(clip, db_path=db_path)
    except Exception as exc:  # noqa: BLE001 - the file is fine; only metadata lagged
        log.warning(f"  [compact] {clip.filename} re-encoded but couldn't be "
                    f"re-measured ({exc}). Run find-duplicates to refresh it.")

    # The cached poster frame was taken from the old file.
    thumb = CACHE_DIR / "footage_thumbs" / f"{Path(clip.filename).stem}.jpg"
    thumb.unlink(missing_ok=True)

    return before - after


def compact_library(max_seconds: float = DEFAULT_MAX_SECONDS, crf: int = DEFAULT_CRF,
                    db_path=None, progress=None) -> dict:
    """Compact everything worth compacting."""
    proposal = plan(max_seconds, crf, db_path=db_path)
    candidates = proposal["candidates"]

    saved = done = 0
    for i, candidate in enumerate(candidates, 1):
        saved += compact_clip(candidate.clip, max_seconds, crf, db_path=db_path)
        done += 1
        if progress:
            progress(i, len(candidates))

    return {"processed": done, "saved": saved,
            "before": proposal["total_before"],
            "after": proposal["total_before"] - saved}
