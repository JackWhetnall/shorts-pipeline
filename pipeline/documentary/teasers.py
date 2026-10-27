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
EFFORT = "high"                 # a few cents more for writing that reads cleanly (decision 110)
WORDS = (85, 130)               # 35-55 seconds spoken

SYSTEM = """
You write teaser shorts for a film on this channel: vertical videos of 35 to 55 seconds,
shown in the Shorts feed to people who have never heard of the film. A teaser's job is to make
them want to watch the full video. It does four things:

1. It hooks in the first line: a surprising true fact, or a question the viewer can't answer
   but wants to. Never a line that only sets the scene.
2. It makes the film's question plain, so the viewer knows what the full video is about.
3. It gives one real, interesting piece of the film, explained clearly, so the short is worth
   watching on its own.
4. It stops before the film's main answer and ends by telling the viewer where to find it.

How it sounds: like the film's own narrator. Clear, warm, curious, plain words, each sentence
making complete literal sense to someone who hasn't seen the film. Clarity beats cleverness.
No slang, no hype words ("wild", "insane", "crazy", "mind-blowing", "here's a weird one"),
no forced casualness, no metaphor the film doesn't use, and nothing that only sounds
impressive. If a line could confuse a first-time viewer, write it plainer.

Facts: the narration below has been fact-checked. Use its figures and comparisons exactly as
it states them, and add no comparisons of your own: a new comparison is where teasers go
wrong ("about the length of a half marathon" for twelve kilometres; a half marathon is
twenty one). Restating one of the narration's comparisons in new words garbles it too, so
keep its shape (Everest dropped into the deepest trench sits more than two kilometres under
water). Where the outline or angle says more than the narration, the narration wins. Claim
nothing the narration doesn't.

{ending}

The teasers must differ from each other in which part of the film they take and how they
hook.

Words: write each sentence fresh rather than copying the narration's sentences (copied
sentences read as reused content), but keep its facts and comparisons as they are. Narration
is read by a voice engine exactly as written: no dashes, no stage directions, numbers said
as words.

Pictures: the film's own. Each teaser has 3 to 6 scenes. Each scene is `narration` (spoken
over it), `picture` (the number of the film's picture shown meanwhile, from the list: one that
shows what the line says, each used at most once in a teaser) and `camera`.

The first picture is what someone scrolling sees while deciding whether to stay, so choose
it for that. Of the film's pictures that belong to the part this teaser takes, open on the
one most likely to stop a thumb: a person large in the frame over an object, a machine, a
map or a landscape; an attractive, expressive person caught mid-action over a small or
distant figure; and where the film has a fitting picture of an attractive woman, her. The first line is said over it, so it must still be true to the film:
never a picture from an unrelated part chosen only for its looks.

`title`: a short, honest title for the short (nothing the film doesn't support).
`description`: one or two sentences that pose the question without answering it.
""".strip()


ENDING_CHANNEL = """The last line tells the viewer, simply, that there's a full video and where it is, as an
invitation. Shapes that work:
- "Check out our channel for the full explanation."
- "Find out in the full video on our channel."
- Two or three short questions the film answers, then: "This and more, explained on our
  channel."
Keep it one plain sentence (or short questions plus one), never slangy, never "the
documentary", never the same wording as another teaser here or the recent ones below, and
never "like and subscribe" or "link in bio"."""

# Decision 114: with the film linked as the Short's "Related video", the
# invitation is to tap that link, the step YouTube says to name.
ENDING_LINK = """The last line tells the viewer, simply, that the full video is one tap away, as an
invitation: the film is linked on this Short. Shapes that work:
- "Tap the link below for the full video."
- "The full explanation is in the link below."
- Two or three short questions the film answers, then: "Tap the link to find out."
Keep it one plain sentence (or short questions plus one), never slangy, never "the
documentary", never the same wording as another teaser here or the recent ones below, and
never "like and subscribe" or "link in bio"."""


def system(channel) -> str:
    """The teaser brief, with the ending that suits how this channel's
    teasers reach their film."""
    linked = bool(getattr(getattr(channel, "documentary", None), "teasers_linked", False))
    return SYSTEM.replace("{ending}", ENDING_LINK if linked else ENDING_CHANNEL)


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
    data = call_json([SystemBlock(system(channel), cacheable=True),
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


EDIT = """
You edit teaser shorts for a film, against the film's own narration (below), before they're
voiced. For every teaser line, fix it if:
- it states a fact, figure or comparison the narration doesn't, or states one differently
  (a comparison reworded until it's wrong or garbled counts);
- it wouldn't make complete literal sense to someone who hasn't seen the film, or reads
  clumsily aloud;
- it uses slang, hype ("wild", "insane", "crazy") or a strained metaphor.
Check every figure and every comparison ("deeper than", "the size of", "like a...") against
the narration's own words: a comparison the narration doesn't make is cut, never swapped for
another one, and one it does make is put back the way the narration says it. A fix keeps the
line's job, in the same clear, warm voice, using only what the narration says; a line can get
shorter. Most lines are fine: leave them out. The last line of each teaser invites the
viewer to the full video on the channel; leave it unless it breaks the rules above. Give each
fix as the teaser's number (from 0), the line's number in it (from 0), the problem in a few
words and the rewritten line, with numbers said as words and no dashes.
""".strip()


def checked(teasers_: list, script: dict = None) -> list:
    """The teasers edited against the film's narration (decision 110): the
    first fact check saw only the teasers' own lines, so a comparison the
    writer invented ("about the length of a half marathon" for twelve
    kilometres) or garbled went through. One call for all of them; a
    failed edit keeps them as written (logged)."""
    if not teasers_:
        return teasers_
    narration = "\n".join(s["narration"] for s in (script or {}).get("scenes") or [])
    listed = "\n\n".join(f"Teaser {n}:\n" + "\n".join(f"{k}. {s['narration']}" for k, s in enumerate(t["scenes"]))
                           for n, t in enumerate(teasers_))
    schema = {"type": "object", "properties": {"fixes": {"type": "array", "items": {
        "type": "object", "properties": {"teaser": {"type": "integer"}, "line": {"type": "integer"},
                                         "problem": {"type": "string"}, "narration": {"type": "string"}},
        "required": ["teaser", "line", "problem", "narration"], "additionalProperties": False}}},
        "required": ["fixes"], "additionalProperties": False}
    try:
        data = call_json(EDIT, f"The film's narration:\n{narration or '(not given)'}\n\nThe teasers:\n{listed}",
                         schema, operation="documentary_teaser_edit", max_tokens=12000, effort="high")
    except PipelineError as exc:
        log.warning(f"  [teasers] couldn't edit the teasers ({exc}); kept as written")
        return teasers_
    out = [{**t, "scenes": [dict(s) for s in t["scenes"]]} for t in teasers_]
    for fix in data.get("fixes") or []:
        n, k = fix.get("teaser"), fix.get("line")
        text = " ".join(str(fix.get("narration") or "").split())
        if isinstance(n, int) and isinstance(k, int) and 0 <= n < len(out) and 0 <= k < len(out[n]["scenes"]) and text:
            out[n]["scenes"][k]["narration"] = text
            log.info(f"  [teasers] edited teaser {n + 1} line {k + 1}: {str(fix.get('problem'))[:120]}")
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
