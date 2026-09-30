"""
Motion: each keyframe animated into its shot by the channel's video
model, then looked at.

The prompt carries the shot's action and camera move, the look's way of
moving and the rules every shot shares (stay on-model, no morphing, no
text). A continued take starts from the last frame of the shot before
it, so a journey or a transformation runs on across the cut unbroken.

Video models fail in their own ways: faces melt, a character becomes
someone else halfway, writing appears, nothing moves, the picture drifts
out of the style. Three frames of every shot go to a vision model in one
call beside its keyframe; a shot with a real problem is made again once
with the problem named, if the budget has room.
"""

from __future__ import annotations

import random
import subprocess
from pathlib import Path

from core import costs
from core.logging_setup import get_logger
from pipeline.animation import fal, frame as frames, look as looks, models
from pipeline.animation.keyframes import thumbnail
from pipeline.llm import call_json

log = get_logger(__name__)


def prompt_for(shot: dict, board: dict, look: dict, avoid: list = None) -> str:
    who = [board["elements"][k] for k in shot["elements"] if k in board["elements"]]
    parts = [shot["motion"].strip().rstrip(".") + ".",
             f"Camera: {shot['camera'].strip().rstrip('.')}."]
    if who:
        parts.append("In the shot: " + "; ".join(
            f"{e['name']} ({e['description'][:160]})" for e in who) + ".")
    parts.append(looks.motion_text(look))
    if avoid:
        parts.append("Avoid what went wrong last time: " + "; ".join(avoid) + ".")
    return " ".join(parts)


def path_for(folder: Path, shot: dict) -> Path:
    return Path(folder) / f"shot_{shot['index']:02d}.mp4"


def animate(shot: dict, board: dict, look: dict, first_frame: Path, video: models.VideoModel,
            quality: str, folder: Path, avoid: list = None) -> Path:
    """The shot as generated (before finishing), downloaded to the folder."""
    out = path_for(folder, shot)
    if out.exists() and not avoid:
        return out
    seconds = shot["generate"]
    request = video.request(prompt_for(shot, board, look, avoid), fal.data_uri(first_frame),
                            seconds, quality, seed=random.randint(1, 2 ** 31 - 1),
                            aspect_ratio=frames.get(look.get("frame")).aspect_ratio)
    log.info(f"  [animation] shot {shot['index']}: {seconds}s on {video.label} "
             f"({shot['camera'][:40]})")
    result = fal.run(video.endpoint, request, what=f"shot {shot['index'] + 1}")
    url = video.video_url(result)
    if not url:
        from core.errors import ExternalServiceError
        raise ExternalServiceError(fal.SERVICE, f"no video in result: {str(result)[:300]}",
                                   user_message="fal finished a shot but sent no video back.")
    costs.record_fal("animation_shot", video.key, video.cost(seconds, quality), seconds=seconds)
    return fal.download(url, out)


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def length(path: Path) -> float:
    import imageio_ffmpeg
    return imageio_ffmpeg.count_frames_and_secs(str(path))[1]


def frame_at(clip: Path, seconds: float, out: Path) -> Path:
    """One frame of a clip as a picture (a continued take's first frame,
    or a frame to check)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([_ffmpeg(), "-v", "error", "-y", "-ss", f"{max(0.0, seconds):.3f}",
                    "-i", str(clip), "-frames:v", "1", "-q:v", "2", str(out)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out


def last_frame(clip: Path, out: Path, used: float = None) -> Path:
    """The frame a continued take starts from: the last one actually
    shown (`used` seconds of source), not the end of the file."""
    end = used if used else length(clip)
    return frame_at(clip, max(0.0, end - 0.06), out)


CHECK = """
These are shots of an animated short, each shown as its first frame and three frames from
across the generated shot, with what the shot should show. The video model that made them can
fail in particular ways. For each shot, list only these real problems:
- faces, hands or bodies melt, warp, double or change shape between frames;
- a character becomes someone else (different face, hair or clothes from the first frame);
- text, letters, numbers or gibberish writing appear;
- the picture drifts out of the style of its first frame (goes photographic, 3D, blurry);
- nothing moves at all, or the shot flashes, glitches or cuts to something unrelated;
- objects or people appear from nowhere or vanish.
Ordinary animation (a camera move, a small change of expression) is fine. ok is false only for
these problems; say each in a short sentence.
""".strip()


def check(shots: list, clips: dict, keyframes: dict, folder: Path) -> dict:
    """{shot index: [problems]} for the shots worth making again."""
    from pipeline.animation.keyframes import _check_schema

    todo = [s for s in shots if s["index"] in clips]
    if not todo:
        return {}
    pictures = []
    for s in todo:
        clip = clips[s["index"]]
        used = min(length(clip), s["duration"] * models.RETIME_MAX)
        pictures.append(("text", f"Shot {s['index']} should show: {s['motion']}"))
        first = keyframes.get(s["index"])
        if first:
            pictures.append(thumbnail(first, (240, 426)))
        for k, at in enumerate((0.35, 0.7, 0.97)):
            still = frame_at(clip, used * at, folder / "check" / f"s{s['index']}_{k}.jpg")
            pictures.append(thumbnail(still, (240, 426)))
    data = call_json(CHECK, "Check every shot above.", _check_schema(), images=pictures,
                     operation="animation_motion_check", max_tokens=6000)
    wanted = {s["index"] for s in todo}
    return {r["index"]: [p for p in r.get("problems") or [] if p]
            for r in data.get("shots") or []
            if r.get("index") in wanted and not r.get("ok") and r.get("problems")}
