"""
Making a video again from what it was made of (decision 056).

"Remake as is" keeps a made video's script, voice, footage and every
paid-for picture, and redoes only what's asked: one animated shot that
came back wrong from the video model, an illustration, or nothing (just
render again, to pick up a fix to the board or the captions). A quiz
remade with questions swapped (pipeline.quiz_review) goes the same way,
with its new script and only the changed lines voiced.

How: a finished job's checkpoints (the same files a retry resumes from)
are kept beside the video as its kit (`<stem>_remake/`), and its working
folder of made pictures (`<stem>_scenes/`) is kept too. A remake is a new
job whose checkpoints are filled from the kit before it starts, less
whatever is to be made again. The kit goes once the video has gone out,
or a week after it was discarded, or after a month (`sweep`).
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from datetime import date
from pathlib import Path

from core import job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import JOB_STATE_DIR, PROJECT_ROOT, slugify, unique_stem

log = get_logger(__name__)

KEEP_DAYS = 30
DISCARDED_DAYS = 7
NOT_KEPT = {"progress.json", "voiced_segments.json"}   # where it landed; this job's own record


def kit_dir(video: Path) -> Path:
    video = Path(video)
    return video.with_name(f"{video.stem}_remake")


def scenes_dir(video: Path) -> Path:
    video = Path(video)
    return video.with_name(f"{video.stem}_scenes")


def keep(job_id: str, video: Path, seed: dict) -> None:
    """Move a finished job's checkpoints beside its video."""
    source = JOB_STATE_DIR / job_id / job_context.CHECKPOINT_SUBDIR
    if not source.is_dir():
        return
    kit = kit_dir(video)
    if kit.exists():
        shutil.rmtree(kit, ignore_errors=True)
    shutil.move(str(source), str(kit))
    for name in NOT_KEPT:
        (kit / name).unlink(missing_ok=True)
    (kit / "seed.json").write_text(json.dumps(seed), encoding="utf-8")


def forget(video: Path) -> None:
    for folder in (kit_dir(video), scenes_dir(video)):
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None


# --- what a remake would keep --------------------------------------------------

def _script(channel, video: Path) -> dict:
    kit = _read(kit_dir(video) / "script.json")
    if kit:
        return kit
    if channel.format == "quiz":
        from pipeline import quiz_review
        return quiz_review.made_script(channel, video)
    from pipeline import quiz
    return _read(quiz.script_sidecar(video))


def _seed(channel, video: Path) -> dict:
    """What the video was made from: kept with its kit, or for a short on
    a topic plan, its subtopic."""
    seed = _read(kit_dir(video) / "seed.json")
    if seed:
        return dict(seed)
    from core import curriculum
    if curriculum.exists(channel.key):
        row = next((s for s in curriculum.subtopics(channel.key) if s.get("video_stem") == video.stem), None)
        if row:
            return {"type": "topic", "topic": row["title"], "topic_id": row["id"]}
    return None


def parts(video: Path) -> list:
    """What's on screen that was made for this video and could be made
    again: [{id, label, kind, segments, picture?}]. An animation is offered
    shot by shot, with each shot's keyframe to recognise it by."""
    scenes = _read(kit_dir(video) / "scenes.json") or {}
    folder = scenes_dir(video)
    out = []
    for clip in scenes.get("clips") or []:
        kind, first, last = clip.get("kind", ""), clip["first"], clip["last"]
        where = f"segment {first + 1}" if first == last else f"segments {first + 1}-{last + 1}"
        if kind == "animation":
            continue
        out.append({"id": f"seg{first}", "kind": kind, "label": f"{kind.capitalize()}, {where}",
                    "segments": list(range(first, last + 1))})
    board = _read(folder / "animation" / "storyboard.json") or {}
    for shot in board.get("shots") or []:
        n = shot["index"]
        picture = folder / "animation" / f"kf_{n:02d}.jpg"
        out.append({"id": f"shot{n}", "kind": "shot", "label": f"Animated shot {n + 1}",
                    "picture": str(picture) if picture.exists() else "",
                    "caption": (shot.get("image") or shot.get("motion") or "")[:140]})
    return out


def summary(channel, video: Path) -> dict:
    """Whether this video can be remade, and what would be kept."""
    video = Path(video)
    script, seed = _script(channel, video), _seed(channel, video)
    if not script or not seed:
        return {"possible": False, "why": (
            "This video was made before videos kept what a remake needs. Make it again from "
            "Create video instead.")}
    kit = kit_dir(video)
    voice_kept = (kit / "voiceover.json").exists() and (kit / "voiceover.mp3").exists()
    return {"possible": True, "voice_kept": voice_kept,
            "voice_characters": 0 if voice_kept else _to_voice(channel, script),
            "footage_kept": (kit / "footage_picks.json").exists(),
            "parts": parts(video), "quiz": bool(script.get("quiz"))}


def _to_voice(channel, script: dict) -> int:
    from pipeline import tts
    from pipeline.plan import Script
    s = Script.from_jsonable(script)
    say_as = {**tts._symbol_respellings(s), **(getattr(channel, "pronunciations", None) or {})}
    return tts.characters_to_voice(s.segments, s.citation, channel.pacing, getattr(s, "source_index", 0),
                                   channel.voice, channel.speed, say_as, reuse=True)


# --- making it again ---------------------------------------------------------

def prepare(channel, video: Path, redo: set = frozenset(), redraw: set = frozenset(),
            script: dict = None) -> tuple:
    """A new job's id and seed, its checkpoints filled from the video's
    kit. `redo` holds part ids (from `parts`) to make again; `redraw` the
    shots whose picture is drawn again too, not only animated. With
    `script`, that script replaces the video's, and its voice is reused
    line by line instead of whole."""
    from core.paths import OUTPUT_DIR
    video = Path(video)
    seed = _seed(channel, video)
    kept_script = _script(channel, video)
    if not seed or not kept_script:
        raise PipelineError(f"nothing kept for {video.name}", user_message=summary(channel, video).get(
            "why") or "This video can't be remade.")
    kit = kit_dir(video)
    job_id = uuid.uuid4().hex
    target = job_context.checkpoint_dir(job_id)

    out_dir = PROJECT_ROOT / channel.output_dir / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = unique_stem(out_dir, slugify(seed.get("topic") or seed.get("reference") or video.stem,
                                        fallback="video"))
    (target / "progress.json").write_text(json.dumps({"out_dir": str(out_dir), "stem": stem}),
                                          encoding="utf-8")
    (target / "script.json").write_text(json.dumps(script or kept_script), encoding="utf-8")
    if script is None and (kit / "voiceover.json").exists() and (kit / "voiceover.mp3").exists():
        shutil.copyfile(kit / "voiceover.json", target / "voiceover.json")
        shutil.copyfile(kit / "voiceover.mp3", target / "voiceover.mp3")
    if (kit / "footage_picks.json").exists():
        # Checked against the script's shape before it's used (library._load_checkpoint).
        shutil.copyfile(kit / "footage_picks.json", target / "footage_picks.json")
    _visuals(kit, video, out_dir / f"{stem}_scenes", target, set(redo), set(redraw))

    from pipeline import quiz
    number = int((_read(quiz.round_sidecar(video)) or {}).get("number") or 0)
    seed = {**seed, "remake_of": str(video.relative_to(OUTPUT_DIR)).replace("\\", "/")}
    if number:
        seed["number"] = number
    return job_id, seed


def _visuals(kit: Path, video: Path, new_folder: Path, target: Path, redo: set, redraw: set) -> None:
    """The made pictures, copied for the new video, and what's to be made
    again taken out so the visuals stage makes only that."""
    scenes = _read(kit / "scenes.json")
    old_folder = scenes_dir(video)
    clips = [c for c in (scenes or {}).get("clips") or [] if c.get("kind") != "quiz"]
    if not scenes or not clips or not old_folder.is_dir():
        return                     # a quiz board, or footage alone: made again, for free
    shutil.copytree(old_folder, new_folder, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("board.mp4", "board.json"))

    def moved(path: str) -> str:
        return str(new_folder / Path(path).relative_to(old_folder)) if Path(path).is_relative_to(old_folder) \
            else path
    clips = [{**c, "clip": moved(c["clip"])} for c in clips]
    shots = {int(p[4:]) for p in redo if p.startswith("shot")}
    segments = {int(p[3:]) for p in redo if p.startswith("seg")}
    if not shots and not segments:
        (target / "scenes.json").write_text(json.dumps({**scenes, "clips": clips}), encoding="utf-8")
        return
    animation = new_folder / "animation"
    for n in shots:
        (animation / f"shot_{n:02d}.mp4").unlink(missing_ok=True)
        if f"shot{n}" in redraw:
            (animation / f"kf_{n:02d}.jpg").unlink(missing_ok=True)
    keep = [c for c in clips if not (shots and c.get("kind") == "animation")
            and not set(range(c["first"], c["last"] + 1)) & segments]
    (target / "remake_visuals.json").write_text(json.dumps({
        "directions": scenes.get("directions") or [], "keep": keep, "redo": sorted(segments),
        "animate": bool(shots), "notes": [], "animation": scenes.get("animation") or {}}),
        encoding="utf-8")


def start(channel, video: Path, redo: set = frozenset(), redraw: set = frozenset(),
          script: dict = None) -> str:
    """Discard the video and start making it again. Returns the job id.
    If the job can't start, the video is put back as it was."""
    from core import gallery, jobs
    video = Path(video)
    job_id, seed = prepare(channel, video, redo, redraw, script)
    was = gallery.load_publish_info(video)
    gallery.set_discarded(video, True, reason="remade")
    if channel.format == "quiz":
        from pipeline import quiz
        quiz.forget(channel.key, video.stem)
    try:
        jobs.start_job(channel.key, seed, job_id=job_id)
    except PipelineError:
        if not was["discarded"]:
            gallery.set_discarded(video, False)
        job_context.clear_checkpoints(job_id)
        raise
    return job_id


# --- tidying -------------------------------------------------------------------

def sweep(channels: dict) -> int:
    """Remove the kits no remake will use: of a video gone out, discarded
    a week ago, deleted, or a month old. Returns how many."""
    from core import gallery
    removed = 0
    now = time.time()
    for channel in channels.values():
        directory = gallery.resolve_output_dir(channel.output_dir)
        if not directory.exists():
            continue
        for kit in directory.rglob("*_remake"):
            if not kit.is_dir():
                continue
            video = kit.with_name(kit.name[:-len("_remake")] + ".mp4")
            info = gallery.load_publish_info(video) if video.exists() else None
            discarded_at = _when((info or {}).get("discarded_at"))
            stale = (info is None or gallery.is_out(info)
                     or (info["discarded"] and now - (discarded_at or 0) > DISCARDED_DAYS * 86400)
                     or now - kit.stat().st_mtime > KEEP_DAYS * 86400)
            if stale:
                forget(video)
                removed += 1
    return removed


def _when(stamp: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(stamp).timestamp() if stamp else None
    except ValueError:
        return None
