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
from pipeline.animation import frame as frames, look as looks, models

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


def _size(look: dict) -> tuple:
    """(width, height) of the frame the look is being made for."""
    f = frames.get(look.get("frame"))
    return f.w, f.h


def shot_filter(look: dict, speed: float) -> str:
    """The -vf chain for one shot, source frames in, finished frames out."""
    chain = [f"setpts=PTS/{speed:.5f}"]
    fps = looks.cadence_fps(look)
    if fps < 24:
        chain.append(f"fps={fps}")
    sharpen = (look.get("grade") or {}).get("sharpen", 0.15)
    w, h = _size(look)
    chain += [f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos",
              f"crop={w}:{h}", "setsar=1",
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
    w, h = _size(look)
    zoom = f"zoompan=z='1+0.06*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':" \
           f"d={frames}:s={w}x{h}:fps={FPS}"
    chain = [f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase:flags=lanczos",
             f"crop={w * 2}:{h * 2}", zoom, "setsar=1"]
    chain += grade_filters(look) + texture_filters(look) + ["format=yuv420p"]
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([_ffmpeg(), "-v", "error", "-y", "-loop", "1", "-i", str(image),
                    "-vf", ",".join(chain), "-t", f"{total:.3f}", "-r", str(FPS),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", str(out)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out


# How a still moves while it's on screen (a documentary's storyboard,
# pipeline.documentary): zoom from, zoom to, and the left edge's travel
# across the spare width (0 = left, 1 = right), from and to.
CAMERA_MOVES = {
    "push_in": (1.0, 1.12, 0.5, 0.5),
    "pull_out": (1.12, 1.0, 0.5, 0.5),
    "pan_left": (1.12, 1.12, 1.0, 0.0),
    "pan_right": (1.12, 1.12, 0.0, 1.0),
    "still": (1.04, 1.06, 0.5, 0.5),
}
CAMERA_SCALE = 1.5          # drawn larger than the frame first, so the move is smooth


def camera_shot(image: Path, out: Path, seconds: float, look: dict, move: str = "push_in",
                overlay: Path = None, overlay_until: float = 0.0, adjust: list = None,
                atmosphere: Path = None, atmosphere_strength: float = 0.6) -> Path:
    """A still on screen for `seconds`, the camera moving across it, in
    the look's grade and grain. `overlay` (a transparent picture the
    frame's size: a chapter title, a caption) fades in at half a second
    and out at `overlay_until`. `adjust`: ffmpeg filters applied to the
    picture before the grade (an exposure lift). `atmosphere`: a looping
    clip of light on black (embers, dust, rain) screened over the picture
    at `atmosphere_strength`, so a still breathes (decision 087)."""
    z0, z1, x0, x1 = CAMERA_MOVES.get(move, CAMERA_MOVES["push_in"])
    frames = max(2, round(seconds * FPS))
    w, h = _size(look)
    big_w, big_h = round(w * CAMERA_SCALE / 2) * 2, round(h * CAMERA_SCALE / 2) * 2
    p = f"(on/{frames})"
    ease = f"(0.5-0.5*cos(PI*{p}))"
    zoom = (f"zoompan=z='{z0}+({z1 - z0})*{ease}':"
            f"x='(iw-iw/zoom)*({x0}+({x1 - x0})*{ease})':y='(ih-ih/zoom)/2':"
            f"d={frames}:s={w}x{h}:fps={FPS}")
    chain = [f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase:flags=lanczos",
             f"crop={big_w}:{big_h}"] + list(adjust or []) + [zoom, "setsar=1"]
    chain += grade_filters(look) + texture_filters(look) + ["format=yuv420p"]
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_ffmpeg(), "-v", "error", "-y", "-loop", "1", "-i", str(image)]
    if atmosphere is not None:
        # Light added, never darkened: a screen blend of the particles.
        n = 1
        cmd += ["-stream_loop", "-1", "-i", str(atmosphere)]
        graph = (f"[0:v]{','.join(chain[:-1])},format=gbrp[base];"
                 f"[{n}:v]scale={w}:{h},format=gbrp,colorchannelmixer=rr={atmosphere_strength:.2f}:"
                 f"gg={atmosphere_strength:.2f}:bb={atmosphere_strength:.2f}[air];"
                 f"[base][air]blend=all_mode=screen:shortest=1,format=yuv420p[mixed]")
        last = "mixed"
        if overlay is not None:
            until = max(1.2, min(overlay_until or seconds - 0.4, seconds - 0.2))
            cmd += ["-loop", "1", "-i", str(overlay)]
            graph += (f";[{n + 1}:v]format=rgba,fade=in:st=0.4:d=0.5:alpha=1,"
                      f"fade=out:st={max(0.9, until - 0.5):.3f}:d=0.5:alpha=1[label];"
                      f"[mixed][label]overlay=0:0:shortest=1,format=yuv420p[v]")
            last = "v"
        cmd += ["-filter_complex", graph, "-map", f"[{last}]"]
    elif overlay is not None:
        until = max(1.2, min(overlay_until or seconds - 0.4, seconds - 0.2))
        cmd += ["-loop", "1", "-i", str(overlay)]
        graph = (f"[0:v]{','.join(chain[:-1])}[base];"
                 f"[1:v]format=rgba,fade=in:st=0.4:d=0.5:alpha=1,"
                 f"fade=out:st={max(0.9, until - 0.5):.3f}:d=0.5:alpha=1[label];"
                 f"[base][label]overlay=0:0:shortest=1,format=yuv420p[v]")
        cmd += ["-filter_complex", graph, "-map", "[v]"]
    else:
        cmd += ["-vf", ",".join(chain)]
    cmd += ["-t", f"{seconds:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "18", str(out)]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out


def grade(source: Path, out: Path, look: dict) -> Path:
    """A composited clip in the look's grade and grain (its timing and
    cadence are already the compositor's)."""
    chain = grade_filters(look) + texture_filters(look)
    if not chain:
        Path(source).replace(out)
        return out
    subprocess.run([_ffmpeg(), "-v", "error", "-y", "-i", str(source), "-an",
                    "-vf", ",".join(chain + ["format=yuv420p"]), "-r", str(FPS),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", str(out)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out


def overlay_captions(clip: Path, captions: list, out: Path, top: int = 150) -> Path:
    """`captions`: [(png, start, end)] in the clip's seconds, each laid
    over the top of the picture (clear of the subtitles' third), faded in
    and out."""
    if not captions:
        return clip
    cmd = [_ffmpeg(), "-v", "error", "-y", "-i", str(clip)]
    chain, label = [], "0:v"
    for i, (png, start, end) in enumerate(captions, start=1):
        cmd += ["-loop", "1", "-t", f"{end + 0.5:.3f}", "-i", str(png)]
        fade = min(0.35, max(0.1, (end - start) / 4))
        chain.append(f"[{i}:v]format=rgba,fade=in:st={start:.3f}:d={fade:.3f}:alpha=1,"
                     f"fade=out:st={max(start, end - fade):.3f}:d={fade:.3f}:alpha=1[c{i}]")
        chain.append(f"[{label}][c{i}]overlay=x=(W-w)/2:y={top}:"
                     f"enable='between(t,{start:.3f},{end:.3f})'[v{i}]")
        label = f"v{i}"
    cmd += ["-filter_complex", ";".join(chain), "-map", f"[{label}]", "-an", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", "-pix_fmt", "yuv420p",
            str(out)]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
