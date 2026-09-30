"""
Animation on a video that already exists: its script and narration
re-used, so a channel's look and the storyboard can be judged on real
material without paying for a new script or voice.

- `animatic`: storyboard and checked keyframes, each held and pushed in,
  cut to the narration. A few cents a shot; no video model.
- `film`: the same with every shot animated. What a real video's
  animation would cost.

Both write `<stem>_animatic.mp4` / `<stem>_animated.mp4` (with the
narration, no captions), and the storyboard and frames in a working folder
beside it, under cache/animation_previews/<channel>/: never in output/,
where every mp4 is a video waiting for review. Used by tools/animate.py
and the settings page.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR
from pipeline.plan import Segment, WordTiming

log = get_logger(__name__)

SEGMENT_RE = re.compile(r"^\[segment (\d+)\]\s*$")
PREVIEWS_DIR = CACHE_DIR / "animation_previews"


def preview_dir(channel_key: str) -> Path:
    return PREVIEWS_DIR / channel_key


def read_meta(meta_path: Path) -> list:
    """[(text, shot brief)] per segment from a video's _meta.txt."""
    segments, text, shot, inside = [], [], "", False
    for line in Path(meta_path).read_text(encoding="utf-8").splitlines():
        if SEGMENT_RE.match(line.strip()):
            if inside:
                segments.append((" ".join(text).strip(), shot))
            text, shot, inside = [], "", True
            continue
        if not inside:
            continue
        stripped = line.strip()
        if stripped.startswith("shot:"):
            shot = stripped[5:].strip()
        elif stripped.startswith("keywords:") or not stripped:
            continue
        elif not line.startswith("  "):
            text.append(stripped)
    if inside:
        segments.append((" ".join(text).strip(), shot))
    return [s for s in segments if s[0]]


def transcribe(audio_path: Path) -> list:
    """Word timings of an existing narration, heard locally."""
    from pipeline import tts
    model = tts._get_whisper()
    if model is None:
        raise PipelineError("whisper unavailable",
                            user_message="The local speech model isn't available, so this "
                                         "video's narration can't be timed.")
    parts, _ = model.transcribe(str(audio_path), language="en", beam_size=1,
                                word_timestamps=True, condition_on_previous_text=False)
    return [WordTiming(w.word.strip(), round(w.start, 3), round(w.end, 3))
            for part in parts for w in (part.words or []) if w.word.strip()]


def align(texts: list, words: list) -> list:
    """Segments with start and end, found by sharing the heard words out in
    proportion to each segment's written words."""
    counts = [max(1, len(t.split())) for t in texts]
    total = sum(counts)
    out, cursor = [], 0
    for i, (text, count) in enumerate(zip(texts, counts)):
        take = round(len(words) * count / total) if i < len(texts) - 1 else len(words) - cursor
        chunk = words[cursor:cursor + max(1, take)] or words[-1:]
        cursor += max(1, take)
        out.append((chunk[0].start, chunk[-1].end))
    # Each segment runs to the next one's start.
    return [(start, out[i + 1][0] if i + 1 < len(out) else end + 0.4)
            for i, (start, end) in enumerate(out)]


def plan_for(channel, video_path: Path):
    """What the animation stage needs, from a finished video's sidecars."""
    video_path = Path(video_path)
    stem = video_path.stem
    meta = video_path.with_name(f"{stem}_meta.txt")
    audio = video_path.with_name(f"{stem}_audio.mp3")
    if not meta.exists() or not audio.exists():
        raise PipelineError(f"{stem}: no meta or audio",
                            user_message="That video has no saved script or narration to "
                                         "animate.")
    written = read_meta(meta)
    words = transcribe(audio)
    if not words:
        raise PipelineError("no words heard", user_message="No speech was heard in that video.")
    spans = align([t for t, _ in written], words)
    segments = [Segment(text=t, shot_brief=b, start=s, end=e)
                for (t, b), (s, e) in zip(written, spans)]
    return SimpleNamespace(
        channel=channel, stem=stem, out_dir=video_path.parent,
        seed=SimpleNamespace(title=stem.replace("_", " ")),
        script=SimpleNamespace(segments=segments, screen_hook=""),
        voiceover=SimpleNamespace(word_timings=words, audio_path=audio))


def run(channel, video_path: Path, animate: bool) -> Path:
    """An animatic (animate=False) or an animated film of an existing
    video. Returns the new file."""
    from pipeline.animation import stage

    plan = plan_for(channel, video_path)
    from pipeline.animation import formats, look as looks
    fmt = formats.resolve(channel.animation.format)
    look = looks.resolve(channel.animation)
    # A composited format has no video model: its preview is the real thing.
    kind = "animated" if animate or formats.composited(fmt) else "animatic"
    home = preview_dir(channel.key)
    folder = home / f"{plan.stem}_{fmt['key']}_{look['key']}_{kind}"
    indices = list(range(len(plan.script.segments)))
    briefs = {i: s.shot_brief for i, s in enumerate(plan.script.segments)}
    result = stage.make(plan, indices, briefs, folder, tail=0.0, animate=animate)
    if not result.clips:
        raise PipelineError("nothing animated", user_message="Nothing could be animated "
                                                             "within the budget.")
    picture = Path(result.clips[0]["clip"])
    start = plan.script.segments[result.clips[0]["first"]].start
    out = home / f"{plan.stem}_{fmt['key']}_{look['key']}_{kind}.mp4"
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y",
                    "-i", str(picture), "-ss", f"{start:.3f}", "-i", str(plan.voiceover.audio_path),
                    # A size for watching, not an intermediate: grain alone made
                    # a 34-second felt preview 68 MB at the working quality.
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(out)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for note in result.notes:
        log.info(f"  [animation] note: {note}")
    log.info(f"  [animation] {kind}: {out}")
    return out
