"""
A quiz short's thumbnail: its opening screen once the category and
difficulty have been stamped under the hook (decision 082).

The moment comes from the board's own timeline (`quiz.board` records it
as `thumbnail_at` in the round's sidecar). For a short made before that,
it's worked out from the script kept beside it: the hook's last word,
then the stamp landing and settling. It's saved as `<stem>_cover.jpg`,
which is what's set on YouTube, and as the poster the app shows.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger(__name__)

STAMP_SETTLE = 0.55         # after the stamp lands, it has stopped moving
HOOK_STAMP_AFTER = 0.15     # pipeline.quiz: the stamp lands this long after the hook's last word
DEFAULT_AT = 3.0            # a short with neither record: about where the stamp sits
MAX_BYTES = 2 * 1024 * 1024 # YouTube's limit for a custom thumbnail


def cover_path(video_path) -> Path:
    video_path = Path(video_path)
    return video_path.with_name(f"{video_path.stem}_cover.jpg")


def stamp_moment(video_path, pause_between: float = 0.4) -> float:
    """Seconds into the short when the stamp has landed and settled."""
    video_path = Path(video_path)
    sidecar = video_path.with_name(f"{video_path.stem}_quiz.json")
    try:
        at = json.loads(sidecar.read_text(encoding="utf-8")).get("thumbnail_at")
        if at:
            return float(at)
    except (OSError, ValueError):
        pass
    script = video_path.with_name(f"{video_path.stem}_script.json")
    try:
        data = json.loads(script.read_text(encoding="utf-8"))
        hook = (data.get("quiz") or {}).get("hook")
        first = data["segments"][0]
        if hook and first.get("text", "").strip() == hook.strip() and first.get("end"):
            # The hook's segment runs to the next one's start, its pause included.
            said_by = float(first["end"]) - float(first.get("pause_after") or pause_between)
            return max(0.5, said_by + HOOK_STAMP_AFTER + STAMP_SETTLE)
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    return find_stamp(video_path)


SCAN = (1.0, 7.0, 0.2)      # from, to, step (seconds): where a hook's stamp lands


def find_stamp(video_path) -> float:
    """For a short with no record of its timing: the first moment the
    stamp's band of the screen is as full as it gets, just after it has
    settled. The stamp sits below the hook in the middle of the screen,
    so the band's share of pixels unlike the background rises as it lands
    and drops when the hook screen clears."""
    import numpy as np
    from moviepy.editor import VideoFileClip
    try:
        clip = VideoFileClip(str(video_path), audio=False)
    except Exception:  # noqa: BLE001 - unreadable: the usual moment
        return DEFAULT_AT
    try:
        start, end, step = SCAN
        times, fill = [], []
        background = None
        t = start
        while t < min(end, clip.duration - 0.1):
            image = clip.get_frame(t).astype(np.int16)
            h = image.shape[0]
            band = image[int(h * 0.5):int(h * 0.7)]
            if background is None:
                background = np.median(image.reshape(-1, 3), axis=0)
            fill.append(float((np.abs(band - background).sum(axis=2) > 60).mean()))
            times.append(t)
            t += step
    finally:
        clip.close()
    if not fill or max(fill) < 0.02:
        return DEFAULT_AT
    top = max(fill)
    first = next(i for i, f in enumerate(fill) if f >= 0.97 * top)
    return times[min(first + 2, len(times) - 1)]


def frame(video_path, at: float, out: Path) -> Path:
    """One frame of the video at `at` seconds, as a JPEG under YouTube's limit."""
    import imageio_ffmpeg
    out = Path(out)
    for quality in (2, 4, 7):
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-ss", f"{at:.3f}",
                        "-i", str(video_path), "-frames:v", "1", "-q:v", str(quality), str(out)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if out.stat().st_size <= MAX_BYTES:
            break
    return out


def quiz_cover(video_path, pause_between: float = 0.4, force: bool = False) -> Path:
    """The short's thumbnail, made if it isn't there (or `force`), and used
    as its poster in the app too."""
    video_path = Path(video_path)
    cover = cover_path(video_path)
    if cover.exists() and not force:
        return cover
    frame(video_path, stamp_moment(video_path, pause_between), cover)
    poster = video_path.with_name(f"{video_path.stem}_thumb.jpg")
    poster.write_bytes(cover.read_bytes())
    return cover


def channel_covers(channel, force: bool = False) -> int:
    """A thumbnail for every quiz short this channel has made that hasn't
    one (or every one, `force`). Free: frames from the videos. Returns how
    many were made."""
    from core import gallery
    root = gallery.resolve_output_dir(channel.output_dir)
    if not root.exists():
        return 0
    made = 0
    for video in gallery.videos_in(root, long=False):
        if not video.with_name(f"{video.stem}_quiz.json").exists():
            continue
        if cover_path(video).exists() and not force:
            continue
        try:
            quiz_cover(video, channel.pacing.pause_between_segments, force=True)
            made += 1
        except (OSError, subprocess.CalledProcessError) as exc:
            log.warning(f"  [thumbnail] {video.name}: {exc}")
    return made
