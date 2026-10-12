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
description with chapter marks, and a thumbnail go beside it.

Decision 086: a scene longer than about five seconds is cut into shots
from its still (pipeline.documentary.shots), a card scene is the card
itself, filmed (pipeline.documentary.cards), and a painting is credited.
Where every picture starts and ends is kept in the production sidecar,
so where viewers stop watching can be traced to the scene on screen
(core.retention), and the film's numbers (pictures a minute, the
longest hold, words a minute) go in its report (core.scorecard).
"""

from __future__ import annotations

import json
import re
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

# The silence after a scene's words, by how its last sentence ends. A
# scene often ends mid-thought ("...and so he wrote,") with the next
# picture carrying it on, and the same pause after every scene sounded
# like the narrator stopping for breath at random (decision 079).
# Tightened in decision 086: with 0.45 s after every sentence and the
# voice at 0.9 speed, the first film ran at 118 words a minute.
SENTENCE_GAP = 0.32         # after a full stop, question or exclamation
CLAUSE_GAP = 0.16           # after a comma, semicolon or colon
RUN_ON_GAP = 0.06           # mid-sentence: the line carries straight on
CHAPTER_GAP = 1.1           # and a longer one, now and then, between chapters
END_HOLD = 2.0
THUMB = (1280, 720)


def gap_after(text: str) -> float:
    end = text.rstrip().rstrip("\"'\u201d\u2019)")[-1:]
    if end in ".!?":
        return SENTENCE_GAP
    if end in ",;:":
        return CLAUSE_GAP
    return RUN_ON_GAP


def segments_for(scenes: list) -> list:
    out = []
    for i, s in enumerate(scenes):
        last_of_chapter = i + 1 == len(scenes) or scenes[i + 1]["chapter"] != s["chapter"]
        out.append(Segment(text=s["narration"],
                           pause_after=CHAPTER_GAP if last_of_chapter else gap_after(s["narration"])))
    out[-1].pause_after = END_HOLD
    return out


# British voices first, for characters (decision 087): the premade library
# is mostly American, and a film's cast mostly isn't.
MALE_VOICES = ("JBFqnCBsd6RMkjVDRZzb", "onwK4e9ZLuTAKqWW03F9", "N2lVS1w4EtoT3dr4eOWO", "pqHfZKP75CvOlQylNhV4",
               "nPczCjzI2devNBz1zQrb", "SOYHLrjzK2X1ezoPC6cr")
FEMALE_VOICES = ("pFZP5JQG7iQjIQuC4Bku", "Xb7hH8MSUJpSbSDYk0k2", "EXAVITQu4vr4xnSDxMaL", "XrExE9yKIg1WjnnlVkGX",
                 "hpp4J3VqNfWAUOO0d1Us", "FGY2WhTYpPnrIDTdsKH5")
FEMININE = re.compile(r"\b(woman|women|girl|her|she|widow|wife|goodwife|mother|daughter|sister|queen|lady|"
                      r"mistress|nun|maid|grandmother|aunt|female)\b", re.I)


def voices_for(channel, outline: dict, scenes: list) -> dict:
    """{cast name: voice} for every character who speaks a line, each a
    different voice from the narrator's and from each other, in the order
    they first speak. The same cast and order always get the same voices."""
    if not getattr(channel.documentary, "dialogue", False):
        return {}
    described = {m["name"]: m.get("description", "") for m in outline.get("cast") or []}
    order = []
    for s in scenes:
        if s.get("speaker") and s["speaker"] not in order:
            order.append(s["speaker"])
    taken = {channel.voice}
    out = {}
    for name in order:
        pool = FEMALE_VOICES if FEMININE.search(f"{name} {described.get(name, '')}") else MALE_VOICES
        choice = next((v for v in pool if v not in taken), pool[0])
        out[name] = choice
        taken.add(choice)
    return out


def beats_in(word_timings: list, start: float, seconds: float) -> list:
    """Seconds into a scene where a new sentence or clause begins."""
    beats, previous = [], None
    for w in word_timings or []:
        if start < w.start < start + seconds and previous is not None and previous.word[-1:] in ".,;:?!":
            beats.append(round(w.start - start, 3))
        previous = w
    return beats


def chapter_sounds(scenes: list, segments: list, outline: dict) -> list:
    """[(start, end, sound)] for each chapter's stretch of the film."""
    spans = []
    for s, seg in zip(scenes, segments):
        key = (outline["chapters"][s["chapter"] - 1].get("sound") or "none")             if s["chapter"] <= len(outline["chapters"]) else "none"
        if spans and spans[-1][2] == key and abs(spans[-1][1] - seg.start) < 0.01:
            spans[-1] = (spans[-1][0], seg.end, key)
        else:
            spans.append((seg.start, seg.end, key))
    return spans


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

    from pipeline.documentary import cards, shots

    outline, script = data["outline"], data["script"]
    scenes = script["scenes"]
    pictures = {int(k): production_folder / v for k, v in (data.get("stills") or {}).items()}
    shown = {int(k): v for k, v in (data.get("shown") or {}).items()}
    kinds = [shown.get(i) or ("card" if s.get("medium") == "card" and s.get("card") else "drawn")
             for i, s in enumerate(scenes)]
    missing = [i + 1 for i in range(len(scenes))
               if kinds[i] != "card" and not (pictures.get(i) and pictures[i].exists())]
    if missing:
        raise PipelineError(f"no still for scenes {missing}", user_message=(
            f"Scene{'s' if len(missing) > 1 else ''} {', '.join(map(str, missing[:8]))} "
            f"{'have' if len(missing) > 1 else 'has'} no picture. Draw the storyboard again."))
    look = storyboard.look_for(channel, "wide")
    from core import production as productions
    angle = productions.chosen_angle(data)
    title = angle.get("title") or (outline.get("title_options") or [data.get("title") or "Untitled"])[0]

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
    from pipeline.documentary import script as scripts
    model = scripts.voice_model(channel)
    cast_voices = voices_for(channel, outline, scenes)
    speaking = {i: cast_voices[s["speaker"]] for i, s in enumerate(scenes) if s.get("speaker") in cast_voices}
    voice_quota.require_room(tts.characters_to_voice(segments, None, channel.pacing, 0, channel.voice,
                                                     channel.speed, say_as, True, model=model, voices=speaking))
    log.info(f"[2/5] Voicing {len(scenes)} scenes ({len(speaking)} spoken by characters, {model})...")
    voice = tts.generate_voiceover(segments, None, channel.voice, str(work / "voice.mp3"), channel.pacing,
                                   speed=channel.speed, say_as=say_as, close=True,
                                   # A film made again re-voices only lines whose words changed.
                                   reuse=True, model=model, voices=speaking)

    job_context.report_stage(4)
    log.info(f"[4/5] Putting {len(scenes)} scenes on screen ({segments[-1].end / 60:.1f} minutes)...")
    art = dict(getattr(channel.scenes, "art", None) or {})
    size = finish._size(look)
    framings, shot_problem = shots.plan({i: p for i, p in pictures.items() if kinds[i] != "card"},
                                        production_folder / "shots.json")
    card_style = cards.style_for(channel) if "card" in kinds else None
    from pipeline.documentary import atmosphere, media
    air = bool(getattr(channel.documentary, "atmosphere", False))
    started = set()
    parts, timeline, scene_times = [], [], []
    for i, (scene, seg) in enumerate(zip(scenes, segments)):
        job_context.report_progress(round(100 * i / len(scenes)))
        # A segment runs to the next one's start, its pause included.
        start = seg.start
        seconds = max(0.5, seg.end - seg.start)
        scene_times.append([round(start, 2), round(start + seconds, 2)])
        first = scene["chapter"] not in started
        started.add(scene["chapter"])
        if kinds[i] == "card":
            raw = cards.clip(scene["card"], card_style, seconds, work / f"card_{i:03d}.mp4",
                             backdrop=media.backdrop_for(i, pictures, scenes))
            parts.append(finish.grade(raw, work / f"scene_{i:03d}.mp4", look))
            timeline.append([round(start, 2), round(start + seconds, 2)])
            continue
        overlay = None
        chapter_title = (outline["chapters"][scene["chapter"] - 1]["title"]
                         if first and i > 0 and channel.documentary.chapter_titles else "")
        if chapter_title or scene.get("caption"):
            overlay = work / f"label_{i:03d}.png"
            label_overlay(size, chapter_title, 0,
                          scene.get("caption", ""), art).save(overlay)
        at = start
        # Decision 087: a dark still lifted to a natural level, air where
        # the scene has it, and cuts on the starts of its sentences.
        adjust = atmosphere.exposure(pictures[i], scene.get("direction", ""))
        kind_of_air = atmosphere.pick(scene.get("direction", "")) if air else None
        loop = atmosphere.clip(kind_of_air) if kind_of_air else None
        beats = beats_in(voice.word_timings, start, seconds)
        for k, (picture, length, move) in enumerate(shots.cut(pictures[i], framings.get(i, []), seconds,
                                                              scene.get("camera", "push_in"), work,
                                                              f"s{i:03d}", beats=beats)):
            label = overlay if k == 0 else None
            parts.append(finish.camera_shot(picture, work / f"scene_{i:03d}_{k}.mp4", length, look, move, label,
                                            overlay_until=min(5.0, length - 0.4), adjust=adjust,
                                            atmosphere=loop,
                                            atmosphere_strength=atmosphere.strength(kind_of_air or "")))
            timeline.append([round(at, 2), round(at + length, 2)])
            at += length
    job_context.report_progress(None)
    board = finish.join(parts, work / "board.mp4")

    log.info("[4/5] Mixing the sound...")
    credits = []
    audio = voice.samples.astype(np.float32)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    sound_note = ""
    spans = chapter_sounds(scenes, segments, outline)
    if any(key != "none" for _, _, key in spans):
        from pipeline.documentary import ambience
        speech = audio[np.abs(audio).max(axis=1) > 0.02]
        voice_rms = float(np.sqrt((speech ** 2).mean())) if len(speech) else 0.05
        beds, sound_note = ambience.bed(spans, voice.fps, len(audio), voice_rms)
        audio = audio + beds
    if channel.sound.music:
        audio = audio + music_bed(channel, audio, voice.fps, stem, credits, seamless=True)
    peak = float(np.abs(audio).max() or 1.0)
    if peak > 0.98:
        audio *= 0.98 / peak
    _mux(board, audio, voice.fps, video_path, work)

    job_context.report_stage(5)
    log.info("[5/5] Title, chapters and thumbnail...")
    marks = chapter_marks(scenes, segments, outline)
    description = script.get("description") or ""
    description += "\n\nChapters\n" + "\n".join(f"{stamp(t)} {name}" for t, name in marks)
    art_credits = [c for _, c in sorted((int(k), v) for k, v in (data.get("credits") or {}).items())]
    credits = list(dict.fromkeys(art_credits + credits))
    if credits:
        description += "\n\n" + "\n".join(credits)
    gallery.save_title_and_description(video_path, title, description)
    from pipeline.documentary import thumbs
    thumb_note = thumbs.make(channel, data, pictures, title, video_path, art)

    similar = _originality(channel, scenes, title, video_path)
    reasons = ["A long video always waits for a look before it goes out."]
    if similar is not None and similar.flagged:
        reasons.append(f"Originality check: {similar.summary}")
    from core import scorecard
    numbers = {"video_seconds": round(segments[-1].end, 1), "pictures": len(timeline),
               "longest_hold": round(shots.longest_hold(timeline), 1),
               "first_30s_pictures": sum(1 for s, _ in timeline if s < 30),
               "words": sum(len(tts.strip_tags(s["narration"]).split()) for s in scenes),
               "speed": float(channel.speed or 1.0), "voice_model": model, "spoken_by_characters": len(speaking),
               "media": sorted(set(kinds)), "paintings": kinds.count("painting"), "cards": kinds.count("card")}
    gallery.save_report(video_path, {
        "longform": True, "documentary": True, "video_seconds": round(segments[-1].end, 1),
        "scenes": len(scenes), "title_options": outline.get("title_options") or [title],
        "similarity": None if similar is None else {"flagged": similar.flagged, "summary": similar.summary},
        "numbers": numbers, "scorecard": scorecard.score(title, angle, scenes, numbers),
        "notes": [n for n in (shot_problem, thumb_note, sound_note) if n],
        "gate": {"passed": False, "reasons": reasons}})
    video_path.with_name(f"{stem}_production.json").write_text(json.dumps({
        "documentary": True, "channel": channel.key, "subtopic_id": data["subtopic_id"],
        "chapters": marks, "scenes": scene_times}, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return SimpleNamespace(video_path=video_path, warnings=reasons[1:] + [n for n in (shot_problem, thumb_note) if n],
                           similarity=similar, script=Script(segments=segments))


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
    from pipeline import tts
    script = Script(segments=[Segment(text=tts.strip_tags(s["narration"])) for s in scenes], citation=None)
    try:
        report = similarity.check(channel.key, script)
        similarity.record(channel.key, title, script, video_path=video_path)
        return report
    except Exception as exc:  # noqa: BLE001 - an advisory check; the video is made
        log.warning(f"  [documentary] originality check failed ({exc})")
        return None
