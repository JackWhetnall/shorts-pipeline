"""
The finish: generated shots made into the channel's film.

Every shot goes through the same chain, which is what makes shots drawn
by separate generations look like one film:

- **Retimed** onto its stretch of narration (sped up or slowed down by at
  most a quarter, models.fit), so every cut lands on its word and no
  generated second is wasted.
- **Drawn on its cadence.** Stop-motion on threes, hand-drawn looks on
  twos: frames are held as an animator would hold them. This is the
  single biggest step from "AI video" to "animation"; it also hides the
  shimmer video models leave between frames.
- **Scaled** to 1080x1920 with a sharpen matched to the upscale.
- **Graded** in the look's contrast, saturation and warmth, with its
  vignette.
- **Textured**: paper looks get a fixed paper tooth, film looks a moving
  grain, laid on at full resolution, where it also covers the softness of
  an upscale.

Shots are then joined with hard cuts, as animation is edited, into one
clip per animated stretch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.logging_setup import get_logger
from core.paths import FRAME_HEIGHT as H, FRAME_WIDTH as W
from pipeline.animation import look as looks, models

log = get_logger(__name__)

FPS = 30


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def grade_filters(look: dict) -> list:
    g = look.get("grade") or {}
    chain = []
    contrast, saturation = g.get("contrast", 1.0), g.get("saturation", 1.0)
    if abs(contrast - 1) > 1e-3 or abs(saturation - 1) > 1e-3:
        chain.append(f"eq=contrast={contrast:.3f}:saturation={saturation:.3f}")
    warmth = g.get("warmth", 0.0)
    if abs(warmth) > 1e-3:
        shift = 0.08 * warmth
        chain.append(f"colorbalance=rm={shift:.3f}:gm={shift * 0.25:.3f}:bm={-shift:.3f}:"
                     f"rh={shift * 0.5:.3f}:bh={-shift * 0.5:.3f}")
    vignette = g.get("vignette", 0.0)
    if vignette > 1e-3:
        chain.append(f"vignette=angle={min(0.9, 0.15 + vignette * 1.1):.3f}")
    return chain


def texture_filters(look: dict) -> list:
    grain = (look.get("grade") or {}).get("grain", 0.0)
    if grain <= 1e-3:
        return []
    strength = max(1, round(grain * 22))
    # Paper texture is the same on every frame; film grain moves.
    flags = "u" if look.get("texture") == "paper" else "t+u"
    return [f"noise=c0s={strength}:c0f={flags}:c1s={max(1, strength // 3)}:c1f={flags}:"
            f"c2s={max(1, strength // 3)}:c2f={flags}"]


def shot_filter(look: dict, speed: float) -> str:
    """The -vf chain for one shot, source frames in, finished frames out."""
    chain = [f"setpts=PTS/{speed:.5f}"]
    fps = looks.cadence_fps(look)
    if fps < 24:
        chain.append(f"fps={fps}")
    sharpen = (look.get("grade") or {}).get("sharpen", 0.15)
    chain += [f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos",
              f"crop={W}:{H}", "setsar=1",
              f"unsharp=5:5:{sharpen:.3f}:5:5:0"]
    chain += grade_filters(look)
    chain += texture_filters(look)
    chain += [f"fps={FPS}", "format=yuv420p"]
    return ",".join(chain)


def finish_shot(source: Path, out: Path, seconds: float, look: dict,
                hold: float = 0.0) -> Path:
    """One generated shot as exactly `seconds` of finished animation (plus
    `hold` seconds of its last frame, for a crossfade out)."""
    generated = _length(source)
    speed, used = models.fit(seconds, generated)
    vf = shot_filter(look, speed)
    total = seconds + hold
    if hold > 0 or used < seconds * speed - 1e-3:
        # Never short: a frame too few leaves the next cut early.
        vf += f",tpad=stop_mode=clone:stop_duration={hold + 1.0:.3f}"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_ffmpeg(), "-v", "error", "-y", "-t", f"{used:.3f}", "-i", str(source), "-an",
           "-vf", vf, "-t", f"{total:.3f}", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", str(out)]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out


def still_shot(image: Path, out: Path, seconds: float, look: dict, hold: float = 0.0) -> Path:
    """A keyframe held with a slow push-in: the stand-in for a shot the
    video model couldn't make, finished like the rest so it doesn't stand
    out more than it must."""
    total = seconds + hold
    frames = max(2, round(total * FPS))
    zoom = f"zoompan=z='1+0.06*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':" \
           f"d={frames}:s={W}x{H}:fps={FPS}"
    chain = [f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=lanczos",
             f"crop={W * 2}:{H * 2}", zoom, "setsar=1"]
    chain += grade_filters(look) + texture_filters(look) + ["format=yuv420p"]
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([_ffmpeg(), "-v", "error", "-y", "-loop", "1", "-i", str(image),
                    "-vf", ",".join(chain), "-t", f"{total:.3f}", "-r", str(FPS),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", str(out)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out


def join(parts: list, out: Path) -> Path:
    """Finished shots, cut together in order."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if len(parts) == 1:
        Path(parts[0]).replace(out)
        return out
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{Path(p).resolve().as_posix()}'\n" for p in parts),
                       encoding="utf-8")
    try:
        subprocess.run([_ffmpeg(), "-v", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-an", "-r", str(FPS), "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "15", "-pix_fmt", "yuv420p", str(out)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finally:
        listing.unlink(missing_ok=True)
    return out


def _length(path: Path) -> float:
    import imageio_ffmpeg
    return imageio_ffmpeg.count_frames_and_secs(str(path))[1]
