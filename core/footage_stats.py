"""
Library health, surfaced in the UI.

The licence count is the point of this module. Every clip in the imported
library carried the same "unverified — confirm before scaling/monetizing"
placeholder, all 264 of them, and the only way to know that was to read a
320 KB JSON file by hand. For a project whose whole purpose is
monetization, that is the largest business risk in the repository and it
had no visibility at all.

Now that stock-footage fetches record the licence their source actually
publishes, the number that matters is small and actionable — the
hand-added clips whose provenance genuinely isn't known — instead of
"everything".
"""

from __future__ import annotations

from pathlib import Path

from core.paths import CACHE_DIR, LIBRARY_DIR, LIBRARY_DB_PATH

THUMBS_DIR = CACHE_DIR / "footage_thumbs"

# Frames ffmpeg scores before choosing. Measured on this library: 30 is
# 2.8x faster than 150 and picks an equally good frame every time, while
# fewer than 30 stops getting faster. Enough to clear an opening fade
# without paying to decode the whole clip.
THUMBNAIL_SAMPLE_FRAMES = 30
# The grid renders these at roughly 290px wide; 540 covers high-DPI
# displays with room to spare.
THUMBNAIL_WIDTH = 540


def clip_thumbnail(filename: str) -> Path:
    """A cached poster frame for one library clip.

    Browsers will not reliably paint a frame from `preload="metadata"`
    alone — sixty video elements on a page get deprioritised and the grid
    stays black — so the grid is built from real images instead.

    Extraction is one ffmpeg pass using its `thumbnail` filter, which
    scores a window of frames and returns the most representative one.
    That matters twice over: it is roughly ten times faster than opening
    the clip through moviepy and seeking (2s per clip made a 60-clip page
    unusable on first view), and it inherently skips the fades and black
    frames that clips routinely open on. Output is scaled to the width
    the grid actually displays rather than shipping 1080x1920 into a
    292-pixel card.
    """
    import subprocess

    import imageio_ffmpeg

    source = LIBRARY_DIR / filename
    if not source.exists():
        raise FileNotFoundError(filename)

    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    thumb = THUMBS_DIR / f"{Path(filename).stem}.jpg"
    if thumb.exists():
        return thumb

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg, "-y", "-i", str(source),
         "-vf", f"thumbnail={THUMBNAIL_SAMPLE_FRAMES},scale={THUMBNAIL_WIDTH}:-2",
         "-frames:v", "1", "-q:v", "4", "-loglevel", "error", str(thumb)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0 or not thumb.exists():
        raise RuntimeError(result.stderr.decode(errors="replace")[-200:] or "no frame")
    return thumb


def library_stats() -> dict:
    """Counts for the home page. Returns zeros rather than raising if the
    library hasn't been set up yet — an empty library is a legitimate
    starting state, not an error."""
    if not LIBRARY_DB_PATH.exists():
        return {"total": 0, "unverified_licenses": 0, "missing_files": 0,
                "unenriched": 0, "ready": False}

    from pipeline.footage import store
    from core.logging_setup import get_logger

    try:
        clips = store.all_clips()
    except Exception as exc:  # noqa: BLE001
        # A corrupt or locked database stops you making videos; it should
        # not also stop you opening the app to find that out.
        get_logger(__name__).warning(f"Couldn't read the footage library: {exc}")
        return {"total": 0, "unverified_licenses": 0, "missing_files": 0,
                "unenriched": 0, "ready": False, "error": True}

    return {
        "total": len(clips),
        "unverified_licenses": sum(1 for c in clips if not c.license_verified),
        # Clips without a subject fall back to matching on prose alone,
        # which ranks a clip that merely contains the thing alongside one
        # that IS it.
        "unenriched": sum(1 for c in clips if not c.enriched),
        # A row whose file is gone would fail at render time. Better to
        # count it here than to discover it mid-generation.
        "missing_files": sum(1 for c in clips if not (LIBRARY_DIR / c.filename).exists()),
        "ready": bool(clips),
    }
