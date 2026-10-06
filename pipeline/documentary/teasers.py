"""
Teaser shorts from a documentary (decision 074).

A few vertical shorts per long video, each a self-contained little film
from one part of its story: a hook, a piece of the story told well, and
an ending that leaves the real question open, so a viewer wants the
whole thing. They are not adverts. Nothing in them says "watch the full
video" or "subscribe"; the description names the long video, and the
story does the asking.

Their words are new (a short reusing the long video's sentences would
be the reused content YouTube demonetises), and their pictures are drawn
again, vertical, from the same people, places and look (`stills.draw`
with the vertical frame): the same characters' model sheets and the
same style sheet, so a teaser looks like part of the film.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from core import gallery, job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import slugify, unique_stem
from pipeline.documentary import script as scripts
from pipeline.documentary import stills as storyboard
from pipeline.llm import SystemBlock, call_json
from pipeline.plan import Segment

log = get_logger(__name__)

MAX_TOKENS = 12000
EFFORT = "medium"
WORDS = (85, 130)               # 35-55 seconds spoken

SYSTEM = """
You write teaser shorts for a documentary: vertical videos of 35 to 55
seconds, each a little film of its own made from one part of the
documentary's story, in the same drawn style.

Each teaser:
- opens on a hook: a concrete moment of tension from the story, stated
  in the first line, the picture putting the viewer inside it;
- tells one piece of the story well: a choice, a reversal, a strange
  true detail. Different teasers take different parts of the story;
- ends on an open question the full documentary answers, so a viewer
  wants the whole story. Never reveal the documentary's payoff (its
  through-line's answer);
- never mentions the documentary, a full video, a channel, a link,
  subscribing or watching more. The story does the asking;
- is written in new words: never copy a sentence from the documentary's
  narration;
- has 3 to 6 scenes. Each scene: `narration` (spoken over it),
  `direction` (one drawable moment for a vertical frame: subject in the
  upper two thirds, no text in the picture), `cast` (the documentary's
  cast members in it, by exact name), `framing`, `camera`;
- `title`: a short title for the short; `description`: one or two
  sentences about the story, without spoilers.

Narration is read by a voice engine exactly as written: no dashes, no
stage directions, numbers said as words.
""".strip()


def schema() -> dict:
    scene = {"type": "object", "properties": {
        "direction": {"type": "string"}, "cast": {"type": "array", "items": {"type": "string"}},
        "framing": {"type": "string", "enum": list(scripts.FRAMINGS)},
        "camera": {"type": "string", "enum": list(scripts.CAMERA)},
        "narration": {"type": "string"}},
        "required": ["direction", "cast", "framing", "camera", "narration"], "additionalProperties": False}
    teaser = {"type": "object", "properties": {
        "title": {"type": "string"}, "description": {"type": "string"},
        "scenes": {"type": "array", "items": scene}},
        "required": ["title", "description", "scenes"], "additionalProperties": False}
    return {"type": "object", "properties": {"teasers": {"type": "array", "items": teaser}},
            "required": ["teasers"], "additionalProperties": False}


def write(channel, title: str, outline: dict, script: dict, note: str = "") -> list:
    """The teasers' scripts. About three cents."""
    count = int(channel.documentary.teasers)
    if count < 1:
        return []
    narration = "\n".join(f"[{s['chapter']}] {s['narration']}" for s in script["scenes"])
    user = (f"The documentary: {title}\n\n{scripts.outline_text(outline)}\n\n"
            f"Its narration, chapter by chapter:\n{narration}\n\n"
            f"Write {count} teasers, each {WORDS[0]}-{WORDS[1]} words of narration.")
    if note:
        user += f"\n\nThe owner asks: {note}"
    data = call_json([SystemBlock(SYSTEM, cacheable=True),
                      SystemBlock(f"The channel's brief for its writers:\n\n{channel.style_prompt}")],
                     user, schema(), operation="documentary_teasers", max_tokens=MAX_TOKENS, effort=EFFORT)
    names = {m["name"].lower(): m["name"] for m in outline.get("cast") or []}
    out = []
    for t in data.get("teasers") or []:
        scenes = [{"chapter": 1, "caption": "",
                   "direction": " ".join(str(s.get("direction") or "").split()),
                   "cast": [names[n.strip().lower()] for n in s.get("cast") or [] if n.strip().lower() in names],
                   "framing": s.get("framing") if s.get("framing") in scripts.FRAMINGS else "medium",
                   "camera": s.get("camera") if s.get("camera") in scripts.CAMERA else "push_in",
                   "narration": " ".join(str(s.get("narration") or "").split())}
                  for s in t.get("scenes") or []]
        scenes = [s for s in scenes if s["narration"] and s["direction"]]
        if scenes and str(t.get("title") or "").strip():
            out.append({"title": t["title"].strip(), "description": str(t.get("description") or "").strip(),
                        "scenes": scenes})
    if not out:
        raise PipelineError("no teasers", user_message="The teasers came back empty. Try again.")
    return out[:count]


def make(channel, data: dict, production_folder: Path) -> list:
    """Every teaser drawn, voiced and cut into a vertical short, into the
    review queue. Returns their video paths."""
    teasers = (data.get("teasers") or {}).get("scripts") or []
    long_title = ((data.get("outline") or {}).get("title_options") or [data.get("title", "")])[0]
    made = []
    for n, teaser in enumerate(teasers, start=1):
        job_context.report_stage(3)
        log.info(f"[3/5] Teaser {n} of {len(teasers)}: drawing its pictures...")
        folder = production_folder / "teasers" / str(n)
        pictures = storyboard.draw(channel, data["outline"], teaser["scenes"], folder, frame="vertical")
        missing = [i for i in range(len(teaser["scenes"])) if i not in pictures]
        if missing:
            raise PipelineError(f"teaser {n} missing stills {missing}",
                                user_message=f"Teaser {n}'s pictures couldn't all be drawn. Try again.")
        made.append(_render(channel, teaser, pictures, long_title, n))
    return made


def _render(channel, teaser: dict, pictures: dict, long_title: str, number: int) -> Path:
    from moviepy.editor import CompositeVideoClip, VideoFileClip
    from moviepy.video.io.ffmpeg_tools import ffmpeg_merge_video_audio

    from core import voice_quota
    from pipeline import assemble, tts
    from pipeline.animation import finish
    from pipeline.longform import music_bed

    look = storyboard.look_for(channel, "vertical")
    out_dir = gallery.resolve_output_dir(channel.output_dir) / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = unique_stem(out_dir, slugify(teaser["title"], fallback=f"teaser_{number}"))
    work = out_dir / f"{stem}_scenes"
    work.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / f"{stem}.mp4"

    job_context.report_stage(2)
    segments = [Segment(text=s["narration"], pause_after=0.25) for s in teaser["scenes"]]
    segments[-1].pause_after = 1.2
    say_as = dict(getattr(channel, "pronunciations", None) or {})
    voice_quota.require_room(tts.characters_to_voice(segments, None, channel.pacing, 0, channel.voice,
                                                     channel.speed, say_as, False))
    voice = tts.generate_voiceover(segments, None, channel.voice, str(work / "voice.mp3"), channel.pacing,
                                   speed=channel.speed, say_as=say_as)

    job_context.report_stage(4)
    parts = [finish.camera_shot(pictures[i], work / f"scene_{i:02d}.mp4", max(0.5, seg.end - seg.start),
                                look, scene.get("camera", "push_in"))
             for i, (scene, seg) in enumerate(zip(teaser["scenes"], segments))]
    board = finish.join(parts, work / "board.mp4")
    background = VideoFileClip(str(board))
    captions = assemble.build_caption_clips(voice.word_timings, channel.style, channel.pacing) \
        if channel.style.captions_enabled else []
    temp_video = work / "captioned.mp4"
    final = CompositeVideoClip([background, *captions], size=background.size).set_duration(background.duration)
    try:
        final.write_videofile(str(temp_video), fps=finish.FPS, codec="libx264", audio=False,
                              preset="veryfast", logger=None)
    finally:
        final.close()
        background.close()

    audio = voice.samples.astype(np.float32)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    credits = []
    if channel.sound.music:
        audio = audio + music_bed(channel, audio, voice.fps, stem, credits)
    peak = float(np.abs(audio).max() or 1.0)
    if peak > 0.98:
        audio *= 0.98 / peak
    from moviepy.audio.AudioClip import AudioArrayClip
    temp_audio = work / "audio.m4a"
    clip = AudioArrayClip(audio, fps=voice.fps)
    clip.write_audiofile(str(temp_audio), codec="aac", fps=voice.fps, logger=None)
    clip.close()
    ffmpeg_merge_video_audio(str(temp_video), str(temp_audio), str(video_path), vcodec="copy",
                             acodec="copy", logger=None)

    description = teaser.get("description", "")
    if long_title:
        description += f"\n\nThe full story: {long_title}"
    if credits:
        description += "\n\n" + "\n".join(credits)
    gallery.save_title_and_description(video_path, teaser["title"], description.strip())
    gallery.save_report(video_path, {
        "teaser": True, "teaser_of": long_title, "video_seconds": round(segments[-1].end, 1),
        "gate": {"passed": False, "reasons": [
            f"A teaser for “{long_title}”: it does most for the channel once the full "
            f"video is out."]}})
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    return video_path


def summary(paths: list) -> SimpleNamespace:
    return SimpleNamespace(video_path=paths[0] if paths else None, warnings=[], similarity=None)
