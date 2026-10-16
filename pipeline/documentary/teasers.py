"""
Teaser shorts from a documentary (decision 074).

A few vertical shorts per long video whose job is to send viewers to it
(decision 106): each hooks in its first line, makes the film's question
plain, pays off one real piece of it, and leaves the rest to the full
video, which it may say is there. The first ones did none of that: they
were told never to mention the film, and read as one more scene.

Their words are new (a short reusing the long video's sentences would
be the reused content YouTube demonetises). Their pictures are the
film's own, made tall (`vertical`), rather than drawn again; a teaser
written before that (with `direction` instead of `picture`) is still
drawn the old way.
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
You write teaser shorts for a documentary on this channel: vertical videos of 35 to 55
seconds, shown in the Shorts feed to people who have never heard of the film. Each teaser's
job is to make them go and watch the full documentary. It succeeds only if it does all of
these, each in its own way:

- Hook in the first line. Within two seconds the viewer must have a reason to stay: a
  claim that sounds wrong but is true, a question they can't answer, a number that doesn't
  fit, a thing everyone believes that isn't so. Never a line that only sets the scene.
- Make the premise plain. By the end the viewer knows what question the full documentary
  answers, and why it's worth answering.
- Pay off something real. Give one genuinely interesting piece of the documentary, told
  well: a fact, a mechanism, a reversal, so the short is worth its time on its own.
- Leave them wanting the rest. Stop short of the documentary's main answer (its
  through-line's payoff) and make it clear there is more, and where it is. Ways to do that
  include an open question left hanging, a reveal stopped at its turn, "and that's the easy
  part", naming what the full film goes into next, or turning the viewer's assumption back on
  them. Every teaser also points to the full video, once, in a few crisp words, and the
  pointer has to have some zing: "The answer's in the full video." "Full video's on the
  channel." "That's where the full video starts." It can come before the last line rather
  than be it, so the teaser still ends on its hook. Call it the video or the full video, never
  "the documentary" or "the full documentary" (Shorts viewers don't go looking for one), and
  never "on this channel" tacked on the end. Never "like and subscribe", "link in bio",
  "smash that button" or any stock call to action. Two teasers never point the same way.

These are examples, not a template. Make the teasers differ from each other in which part of
the story they take, how they hook and how they end, and don't repeat the shapes this
channel's recent teasers used (listed below, when there are any).

Facts: the narration below has been fact-checked and is right; where the outline or angle
says more (a "complete" where the narration says "near-complete"), the narration wins. Claim
nothing the narration doesn't.

Words: new. Never copy a sentence from the documentary's narration. Narration is read by a
voice engine exactly as written: no dashes, no stage directions, numbers said as words.

Pictures: the documentary's own. Each teaser has 3 to 6 scenes. Each scene is `narration`
(spoken over it), `picture` (the number of the documentary picture shown meanwhile, from the
list: one that shows what the line says, each used at most once in a teaser) and `camera`.

`title`: a short, honest title for the short. `description`: one or two sentences that pose
the question without answering it.
""".strip()


def schema() -> dict:
    scene = {"type": "object", "properties": {
        "picture": {"type": "integer"},
        "camera": {"type": "string", "enum": list(scripts.CAMERA)},
        "narration": {"type": "string"}},
        "required": ["picture", "camera", "narration"], "additionalProperties": False}
    teaser = {"type": "object", "properties": {
        "title": {"type": "string"}, "description": {"type": "string"},
        "scenes": {"type": "array", "items": scene}},
        "required": ["title", "description", "scenes"], "additionalProperties": False}
    return {"type": "object", "properties": {"teasers": {"type": "array", "items": teaser}},
            "required": ["teasers"], "additionalProperties": False}


def write(channel, title: str, outline: dict, script: dict, note: str = "", angle: dict = None,
          stills: dict = None, recent: list = None) -> list:
    """The teasers' scripts, each scene shown over one of the film's
    pictures (`stills`: {scene index: picture}). `recent`: the first and
    last lines of the channel's recent teasers, so these don't repeat
    their shapes. About three cents."""
    count = int(channel.documentary.teasers)
    if count < 1:
        return []
    shown = {int(k) for k in (stills or {})}
    lines = []
    for i, s in enumerate(script["scenes"]):
        picture = f" | picture {i}: {s.get('direction', '')[:160]}" if i in shown and s.get("medium", "picture") == "picture" else ""
        lines.append(f"[chapter {s['chapter']}] {s['narration']}{picture}")
    user = (f"The documentary: {title}\n\n{scripts.outline_text(outline, angle)}\n\n"
            f"Its narration, scene by scene, with the picture shown over each (use these numbers):\n"
            + "\n".join(lines) + "\n\n")
    if recent:
        user += "This channel's recent teasers opened and closed like this; do it differently:\n" + \
            "\n".join(f"- {r}" for r in recent[-12:]) + "\n\n"
    user += f"Write {count} teasers, each {WORDS[0]}-{WORDS[1]} words of narration."
    if note:
        user += f"\n\nThe owner asks: {note}"
    data = call_json([SystemBlock(SYSTEM, cacheable=True),
                      SystemBlock(f"The channel's brief for its writers:\n\n{channel.style_prompt}")],
                     user, schema(), operation="documentary_teasers", max_tokens=MAX_TOKENS, effort=EFFORT)
    pictures = [i for i, s in enumerate(script["scenes"]) if i in shown and s.get("medium", "picture") == "picture"]
    out = []
    for t in data.get("teasers") or []:
        scenes, used = [], set()
        for s in t.get("scenes") or []:
            narration = " ".join(str(s.get("narration") or "").split())
            picture = s.get("picture")
            if not narration:
                continue
            if picture not in pictures or picture in used:
                # A number not in the list, or one already used: the nearest unused picture.
                spare = [p for p in pictures if p not in used]
                if not spare:
                    continue
                picture = min(spare, key=lambda p: abs(p - (picture if isinstance(picture, int) else 0)))
            used.add(picture)
            scenes.append({"chapter": 1, "caption": "", "picture": picture,
                           "direction": script["scenes"][picture].get("direction", ""),
                           "camera": s.get("camera") if s.get("camera") in scripts.CAMERA else "push_in",
                           "narration": narration})
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
    film = (data.get("video") or {}).get("path")
    film_info = gallery.load_publish_info(gallery.resolve_output_dir(channel.output_dir) / film) if film else {}
    long_url = film_info.get("youtube_url") or ""
    long_title = film_info.get("title") or long_title
    made = []
    for n, teaser in enumerate(teasers, start=1):
        job_context.report_stage(3)
        log.info(f"[3/5] Teaser {n} of {len(teasers)}: drawing its pictures...")
        folder = production_folder / "teasers" / str(n)
        if all(isinstance(s.get("picture"), int) for s in teaser["scenes"]):
            pictures = _from_the_film(data, teaser["scenes"], production_folder, folder)
        else:
            pictures = storyboard.draw(channel, data["outline"], teaser["scenes"], folder, frame="vertical")
        missing = [i for i in range(len(teaser["scenes"])) if i not in pictures]
        if missing:
            raise PipelineError(f"teaser {n} missing stills {missing}",
                                user_message=f"Teaser {n}'s pictures couldn't all be drawn. Try again.")
        made.append(_render(channel, teaser, pictures, long_title, n, long_url, film or ""))
    return made


def _from_the_film(data: dict, scenes: list, production_folder: Path, folder: Path) -> dict:
    """{scene: tall picture} from the film's own pictures (decision 106)."""
    from pipeline.documentary import vertical
    stills = data.get("stills") or {}
    sources = []
    for s in scenes:
        rel = stills.get(str(s["picture"]))
        if not rel or not (production_folder / rel).exists():
            raise PipelineError(f"teaser picture {s['picture']} missing",
                                user_message="A picture this teaser uses has gone from the storyboard. "
                                             "Write the teasers again.")
        sources.append(production_folder / rel)
    found = vertical.focus(sources)
    return {i: vertical.tall(src, folder / f"tall_{i:02d}.jpg", left, right)
            for i, (src, (left, right)) in enumerate(zip(sources, found))}


def checked(teasers_: list) -> list:
    """The teasers' lines through the same fact check as the film's
    (decision 106): the first ocean teaser claimed "a complete map of
    Mars", which the film had corrected. One call for all of them; a
    failed check keeps them as written (logged)."""
    from pipeline.documentary import editor
    flat = [s for t in teasers_ for s in t["scenes"]]
    if not flat:
        return teasers_
    try:
        fixed, notes = editor.fact_check({"scenes": flat})
    except PipelineError as exc:
        log.warning(f"  [teasers] couldn't fact-check the teasers ({exc}); kept as written")
        return teasers_
    out, n = [], 0
    for t in teasers_:
        count = len(t["scenes"])
        out.append({**t, "scenes": fixed["scenes"][n:n + count]})
        n += count
    for note in notes:
        log.info(f"  [teasers] fact check: {note['problem'][:160]}")
    return out


def recent_lines(teaser_sets: list) -> list:
    """The first and last lines of earlier teasers, for `write` to avoid."""
    out = []
    for scripts_ in teaser_sets:
        for t in scripts_ or []:
            scenes = t.get("scenes") or []
            if scenes:
                out.append(f"opened \"{scenes[0]['narration'][:120]}\" ... closed \"{scenes[-1]['narration'][:120]}\"")
    return out


def _render(channel, teaser: dict, pictures: dict, long_title: str, number: int, long_url: str = "",
            film: str = "") -> Path:
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
                                   speed=channel.speed, say_as=say_as, close=True)

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
        audio = audio + music_bed(channel, audio, voice.fps, stem, credits, seamless=True)
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
        description += f"\n\nThe full story: {long_title}" + (f"\n{long_url}" if long_url else "")
    if credits:
        description += "\n\n" + "\n".join(credits)
    gallery.save_title_and_description(video_path, teaser["title"], description.strip())
    gallery.save_report(video_path, {
        "teaser": True, "teaser_of": long_title, "teaser_of_video": film,
        "video_seconds": round(segments[-1].end, 1),
        "gate": {"passed": False, "reasons": [
            f"A teaser for “{long_title}”: it does most for the channel once the full "
            f"video is out."]}})
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    return video_path


def summary(paths: list) -> SimpleNamespace:
    return SimpleNamespace(video_path=paths[0] if paths else None, warnings=[], similarity=None)
