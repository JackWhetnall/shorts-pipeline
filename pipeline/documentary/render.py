"""
A documentary from its approved script and storyboard (decision 074).

The narration is voiced a scene at a time (each line knowing its
neighbours, pipeline.tts), and every scene's still is put on screen for
exactly as long as its words take, the camera moving across it the way
the script asked (pipeline.animation.finish.camera_shot). A chapter's
first scene carries its title, and a scene with a caption carries that,
both drawn here in the channel's own type and faded in and out. The
music bed runs under the whole, ducked under the voice, as for a long
quiz (pipeline.longform.music_bed).

It lands in the channel's long-video folder, so it goes out in the long
slots, YouTube only, and always waits for review. Its title, a
description with chapter marks, and a thumbnail (the opening still with
the title) go beside it.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from core import gallery, job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import slugify, unique_stem
from pipeline.animation import finish
from pipeline.documentary import stills as storyboard
from pipeline.plan import Script, Segment

log = get_logger(__name__)

SCENE_GAP = 0.3             # silence after a scene's words
CHAPTER_GAP = 1.1           # and after a chapter's last scene
THUMB = (1280, 720)


def segments_for(scenes: list) -> list:
    out = []
    for i, s in enumerate(scenes):
        last_of_chapter = i + 1 == len(scenes) or scenes[i + 1]["chapter"] != s["chapter"]
        out.append(Segment(text=s["narration"], pause_after=CHAPTER_GAP if last_of_chapter else SCENE_GAP))
    out[-1].pause_after = 2.0
    return out


def chapter_marks(scenes: list, segments: list, outline: dict) -> list:
    """[(seconds, chapter title)] where each chapter starts."""
    marks, seen = [], set()
    for s, seg in zip(scenes, segments):
        if s["chapter"] not in seen:
            seen.add(s["chapter"])
            marks.append((0.0 if not marks else round(seg.start, 1),
                          outline["chapters"][s["chapter"] - 1]["title"]))
    return marks


def stamp(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 \
        else f"{seconds // 60}:{seconds % 60:02d}"


# --- the words on screen ---------------------------------------------------------

def _font(size: int, face: str):
    from pipeline.assemble import load_font
    return load_font(size, face)


def label_overlay(size: tuple, chapter: str = "", number: int = 0, caption: str = "",
                  art: dict = None, vertical: bool = False) -> Image.Image:
    """A transparent picture the frame's size with a chapter's title (top
    left) and a caption (lower left), each on a soft dark band so it reads
    over any picture."""
    art = art or {}
    w, h = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = int(w * 0.05)
    display = art.get("font_display") or None
    text_face = art.get("font_text") or display
    accent = art.get("accent1") or "#E3A93D"

    def band(box):
        shadow = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(box, radius=int(h * 0.012), fill=(0, 0, 0, 150))
        image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(int(h * 0.01))))

    if chapter:
        small, big = _font(int(h * (0.022 if vertical else 0.03)), text_face), \
            _font(int(h * (0.04 if vertical else 0.06)), display)
        kicker = f"Chapter {number}" if number else ""
        top = int(h * (0.12 if vertical else 0.08))
        kw = draw.textlength(kicker, font=small) if kicker else 0
        tw = min(draw.textlength(chapter, font=big), w - 2 * margin)
        band((margin - 24, top - 20, margin + max(kw, tw) + 24,
              top + int(h * (0.075 if vertical else 0.11))))
        draw.text((margin, top), kicker, font=small, fill=accent)
        draw.text((margin, top + int(h * (0.028 if vertical else 0.04))), chapter, font=big, fill="white")
    if caption:
        font = _font(int(h * (0.022 if vertical else 0.034)), text_face)
        y = int(h * (0.62 if vertical else 0.82))
        width = min(draw.textlength(caption, font=font), w - 2 * margin)
        band((margin - 20, y - 14, margin + width + 20, y + int(h * (0.03 if vertical else 0.05))))
        draw.text((margin, y), caption, font=font, fill="white")
    return image


# --- the video --------------------------------------------------------------------

def make(channel, data: dict, production_folder: Path) -> SimpleNamespace:
    """The widescreen video for a production whose script and stills are
    approved. Returns an object with video_path."""
    from core import voice_quota
    from pipeline import tts
    from pipeline.longform import _mux, music_bed

    outline, script = data["outline"], data["script"]
    scenes = script["scenes"]
    pictures = {int(k): production_folder / v for k, v in (data.get("stills") or {}).items()}
    missing = [i + 1 for i in range(len(scenes)) if not (pictures.get(i) and pictures[i].exists())]
    if missing:
        raise PipelineError(f"no still for scenes {missing}", user_message=(
            f"Scene{'s' if len(missing) > 1 else ''} {', '.join(map(str, missing[:8]))} "
            f"{'have' if len(missing) > 1 else 'has'} no picture. Draw the storyboard again."))
    look = storyboard.look_for(channel, "wide")
    title = (outline.get("title_options") or [data.get("title") or "Untitled"])[0]

    out_dir = gallery.resolve_output_dir(channel.output_dir) / gallery.LONGFORM_DIR / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = job_context.load_json_checkpoint("documentary") or {}
    stem = saved.get("stem") or unique_stem(out_dir, slugify(title, fallback="documentary"))
    try:
        job_context.save_json_checkpoint("documentary", {"stem": stem})
    except Exception:  # noqa: BLE001 - checkpointing is best-effort
        pass
    work = out_dir / f"{stem}_scenes"
    work.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / f"{stem}.mp4"

    job_context.report_stage(2)
    segments = segments_for(scenes)
    say_as = dict(getattr(channel, "pronunciations", None) or {})
    voice_quota.require_room(tts.characters_to_voice(segments, None, channel.pacing, 0, channel.voice,
                                                     channel.speed, say_as, False))
    log.info(f"[2/5] Voicing {len(scenes)} scenes...")
    voice = tts.generate_voiceover(segments, None, channel.voice, str(work / "voice.mp3"), channel.pacing,
                                   speed=channel.speed, say_as=say_as)

    job_context.report_stage(4)
    log.info(f"[4/5] Putting {len(scenes)} stills on screen ({segments[-1].end / 60:.1f} minutes)...")
    art = dict(getattr(channel.scenes, "art", None) or {})
    size = finish._size(look)
    started = set()
    parts = []
    for i, (scene, seg) in enumerate(zip(scenes, segments)):
        job_context.report_progress(round(100 * i / len(scenes)))
        seconds = max(0.5, seg.end - seg.start)
        first = scene["chapter"] not in started
        started.add(scene["chapter"])
        overlay = None
        chapter_title = outline["chapters"][scene["chapter"] - 1]["title"] if first and i > 0 else ""
        if chapter_title or scene.get("caption"):
            overlay = work / f"label_{i:03d}.png"
            label_overlay(size, chapter_title, scene["chapter"] if chapter_title else 0,
                          scene.get("caption", ""), art).save(overlay)
        parts.append(finish.camera_shot(pictures[i], work / f"scene_{i:03d}.mp4", seconds, look,
                                        scene.get("camera", "push_in"), overlay,
                                        overlay_until=min(5.0, seconds - 0.4)))
    job_context.report_progress(None)
    board = finish.join(parts, work / "board.mp4")

    log.info("[4/5] Mixing the sound...")
    credits = []
    audio = voice.samples.astype(np.float32)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    if channel.sound.music:
        audio = audio + music_bed(channel, audio, voice.fps, stem, credits)
    peak = float(np.abs(audio).max() or 1.0)
    if peak > 0.98:
        audio *= 0.98 / peak
    _mux(board, audio, voice.fps, video_path, work)

    job_context.report_stage(5)
    log.info("[5/5] Title, chapters and thumbnail...")
    marks = chapter_marks(scenes, segments, outline)
    description = script.get("description") or ""
    description += "\n\nChapters\n" + "\n".join(f"{stamp(t)} {name}" for t, name in marks)
    if credits:
        description += "\n\n" + "\n".join(credits)
    gallery.save_title_and_description(video_path, title, description)
    thumbnail(pictures[0], title, art).save(video_path.with_name(f"{stem}_thumb.jpg"), quality=90)

    similar = _originality(channel, scenes, title, video_path)
    reasons = ["A long video always waits for a look before it goes out."]
    if similar is not None and similar.flagged:
        reasons.append(f"Originality check: {similar.summary}")
    gallery.save_report(video_path, {
        "longform": True, "documentary": True, "video_seconds": round(segments[-1].end, 1),
        "scenes": len(scenes), "title_options": outline.get("title_options") or [title],
        "similarity": None if similar is None else {"flagged": similar.flagged, "summary": similar.summary},
        "gate": {"passed": False, "reasons": reasons}})
    video_path.with_name(f"{stem}_production.json").write_text(json.dumps({
        "documentary": True, "channel": channel.key, "subtopic_id": data["subtopic_id"],
        "chapters": marks}, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return SimpleNamespace(video_path=video_path, warnings=reasons[1:], similarity=similar,
                           script=Script(segments=segments))


def thumbnail(still: Path, title: str, art: dict) -> Image.Image:
    """The opening still with the title across its lower half."""
    image = Image.open(still).convert("RGB").resize(THUMB, Image.LANCZOS).convert("RGBA")
    w, h = THUMB
    shade = Image.new("RGBA", THUMB, (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle((0, int(h * 0.55), w, h), fill=(0, 0, 0, 140))
    image.alpha_composite(shade.filter(ImageFilter.GaussianBlur(30)))
    draw = ImageDraw.Draw(image)
    font = _font(int(h * 0.1), art.get("font_display"))
    words, lines, line = title.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) > w * 0.88 and line:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    y = h - int(h * 0.08) - len(lines[:3]) * int(h * 0.115)
    for text in lines[:3]:
        draw.text((int(w * 0.06), y), text, font=font, fill="white", stroke_width=3, stroke_fill="black")
        y += int(h * 0.115)
    return image.convert("RGB")


def _originality(channel, scenes: list, title: str, video_path: Path):
    """The originality check against the channel's earlier scripts
    (pipeline.similarity), recorded once the video exists."""
    from pipeline import similarity
    script = Script(segments=[Segment(text=s["narration"]) for s in scenes], citation=None)
    try:
        report = similarity.check(channel.key, script)
        similarity.record(channel.key, title, script, video_path=video_path)
        return report
    except Exception as exc:  # noqa: BLE001 - an advisory check; the video is made
        log.warning(f"  [documentary] originality check failed ({exc})")
        return None
