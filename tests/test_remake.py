"""
Remaking a made video (core.remake, decision 056). The owner: keep the
script and the voice, and make again only what came out wrong (an
animated shot from the video model, say), or nothing: just film it again.

- a finished job's checkpoints are kept beside its video;
- a remake's job starts with them, under a new name, less what's picked
  to make again: a shot animated again (its picture too if asked), an
  illustration made again, everything else as it was;
- a quiz's board is always filmed again (it's free);
- the visuals stage makes only the parts taken out;
- kits are cleared once their video has gone out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import job_context, remake
from core.channels import ChannelConfig


@pytest.fixture
def world(monkeypatch, tmp_path):
    from core import paths
    output = tmp_path / "output"
    monkeypatch.setattr(paths, "OUTPUT_DIR", output)
    monkeypatch.setattr(remake, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(remake, "JOB_STATE_DIR", tmp_path / "jobs")
    monkeypatch.setattr(job_context, "JOB_STATE_DIR", tmp_path / "jobs")
    channel = ChannelConfig(key="wren", output_dir="output/wren")
    day = output / "wren" / "2026-09-30"
    day.mkdir(parents=True)
    video = day / "moon_rituals.mp4"
    video.write_bytes(b"video")
    return channel, video, tmp_path


def _kit(video: Path, quiz: bool = False):
    kit = remake.kit_dir(video)
    kit.mkdir()
    scenes = remake.scenes_dir(video)
    (scenes / "animation").mkdir(parents=True)
    for name in ("seg2_illustration.mp4", "animation/animation_0_1.mp4", "animation/kf_00.jpg",
                 "animation/kf_01.jpg", "animation/shot_00.mp4", "animation/shot_01.mp4"):
        (scenes / name).write_bytes(b"x")
    (scenes / "animation" / "storyboard.json").write_text(json.dumps(
        {"shots": [{"index": 0, "image": "A moon over water"}, {"index": 1, "motion": "Candles flicker"}]}))
    clips = ([{"first": 0, "last": 9, "clip": str(scenes / "board.mp4"), "kind": "quiz"}] if quiz else
             [{"first": 0, "last": 1, "clip": str(scenes / "animation" / "animation_0_1.mp4"), "kind": "animation"},
              {"first": 2, "last": 2, "clip": str(scenes / "seg2_illustration.mp4"), "kind": "illustration"}])
    (kit / "scenes.json").write_text(json.dumps({"clips": clips, "directions": [
        {"index": 0, "medium": "animation"}, {"index": 1, "medium": "animation"},
        {"index": 2, "medium": "illustration", "brief": "a candle"}]}))
    (kit / "script.json").write_text(json.dumps({"segments": [{"text": "One."}, {"text": "Two."},
                                                              {"text": "Three."}]}))
    (kit / "voiceover.json").write_text(json.dumps({"fps": 44100, "word_timings": [], "segments": []}))
    (kit / "voiceover.mp3").write_bytes(b"mp3")
    (kit / "footage_picks.json").write_text(json.dumps({"shot_counts": [1], "picks": [["a.mp4"]]}))
    (kit / "seed.json").write_text(json.dumps({"type": "topic", "topic": "Moon rituals", "topic_id": "t3"}))


def _checkpoint(job_id: str, name: str):
    path = job_context.JOB_STATE_DIR / job_id / job_context.CHECKPOINT_SUBDIR / name
    return json.loads(path.read_text()) if path.exists() else None


def test_a_finished_jobs_checkpoints_go_beside_its_video(world):
    channel, video, tmp = world
    ck = tmp / "jobs" / "job1" / "checkpoints"
    ck.mkdir(parents=True)
    for name in ("script.json", "progress.json", "voiceover.json", "voiced_segments.json"):
        (ck / name).write_text("{}")
    remake.keep("job1", video, {"type": "topic", "topic": "Moon rituals"})
    kit = remake.kit_dir(video)
    assert sorted(p.name for p in kit.iterdir()) == ["script.json", "seed.json", "voiceover.json"]
    assert not ck.exists()


def test_remaking_as_is_keeps_everything_under_a_new_name(world):
    channel, video, tmp = world
    _kit(video)
    job_id, seed = remake.prepare(channel, video)
    assert seed["remake_of"] == "wren/2026-09-30/moon_rituals.mp4" and seed["topic_id"] == "t3"
    progress = _checkpoint(job_id, "progress.json")
    assert progress["stem"] == "moon_rituals"                     # a new day's folder
    new_scenes = Path(progress["out_dir"]) / "moon_rituals_scenes"
    scenes = _checkpoint(job_id, "scenes.json")
    assert all(c["clip"].startswith(str(new_scenes)) and Path(c["clip"]).exists() for c in scenes["clips"])
    assert _checkpoint(job_id, "voiceover.json") is not None and _checkpoint(job_id, "footage_picks.json")
    assert _checkpoint(job_id, "remake_visuals.json") is None


def test_a_shot_and_a_picture_picked_are_made_again_and_nothing_else(world):
    channel, video, tmp = world
    _kit(video)
    job_id, _ = remake.prepare(channel, video, redo={"shot1", "seg2"}, redraw={"shot1"})
    progress = _checkpoint(job_id, "progress.json")
    animation = Path(progress["out_dir"]) / "moon_rituals_scenes" / "animation"
    assert not (animation / "shot_01.mp4").exists() and not (animation / "kf_01.jpg").exists()
    assert (animation / "shot_00.mp4").exists() and (animation / "kf_00.jpg").exists()
    plan = _checkpoint(job_id, "remake_visuals.json")
    assert plan["redo"] == [2] and plan["animate"] and plan["keep"] == []
    assert _checkpoint(job_id, "scenes.json") is None


def test_animating_a_shot_again_keeps_its_picture(world):
    channel, video, tmp = world
    _kit(video)
    job_id, _ = remake.prepare(channel, video, redo={"shot0"})
    animation = Path(_checkpoint(job_id, "progress.json")["out_dir"]) / "moon_rituals_scenes" / "animation"
    assert not (animation / "shot_00.mp4").exists() and (animation / "kf_00.jpg").exists()
    kept = _checkpoint(job_id, "remake_visuals.json")["keep"]
    assert [c["kind"] for c in kept] == ["illustration"]


def test_a_round_remade_with_new_questions_voices_line_by_line(world):
    """Its script changed, so the whole voice can't be kept: each line
    that didn't change is reused from the voice cache instead (tts)."""
    channel, video, tmp = world
    _kit(video, quiz=True)
    edited = {"segments": [{"text": "One."}, {"text": "Changed."}], "quiz": {"questions": []}}
    job_id, seed = remake.prepare(channel, video, script=edited)
    assert _checkpoint(job_id, "script.json") == edited
    assert _checkpoint(job_id, "voiceover.json") is None and seed["remake_of"]


def test_a_quiz_board_is_always_filmed_again(world):
    channel, video, tmp = world
    _kit(video, quiz=True)
    job_id, _ = remake.prepare(channel, video)
    assert _checkpoint(job_id, "scenes.json") is None and _checkpoint(job_id, "remake_visuals.json") is None


def test_the_parts_offered_are_its_pictures_and_shots(world):
    channel, video, tmp = world
    _kit(video)
    offered = remake.parts(video)
    assert [p["id"] for p in offered] == ["seg2", "shot0", "shot1"]
    assert offered[1]["picture"].endswith("kf_00.jpg") and offered[1]["caption"] == "A moon over water"
    about = remake.summary(channel, video)
    assert about["possible"] and about["voice_kept"] and about["footage_kept"]


def test_a_video_with_nothing_kept_says_so(world):
    channel, video, tmp = world
    assert not remake.summary(channel, video)["possible"]


def test_if_the_remake_cant_start_the_video_is_put_back(world, monkeypatch):
    from core import gallery, jobs
    from core.errors import JobError
    channel, video, tmp = world
    _kit(video)
    marks = []
    monkeypatch.setattr(gallery, "load_publish_info", lambda v: {"discarded": False})
    monkeypatch.setattr(gallery, "set_discarded", lambda v, on, reason=None: marks.append((on, reason)))

    def busy(*a, **k):
        raise JobError("busy", user_message="This channel already has a video being generated.")
    monkeypatch.setattr(jobs, "start_job", busy)
    with pytest.raises(JobError):
        remake.start(channel, video)
    assert marks == [(True, "remade"), (False, None)]


def test_kits_go_once_their_video_has_gone_out(world, monkeypatch):
    from core import gallery
    channel, video, tmp = world
    _kit(video)
    monkeypatch.setattr(gallery, "load_publish_info", lambda v: {"discarded": False, "youtube_url": "x",
                                                                  "published_at": "2026-10-01"})
    monkeypatch.setattr(gallery, "is_out", lambda info: True)
    monkeypatch.setattr(gallery, "resolve_output_dir", lambda d: tmp / d)
    assert remake.sweep({"wren": channel}) == 1
    assert not remake.kit_dir(video).exists() and not remake.scenes_dir(video).exists()


def test_the_visuals_stage_makes_only_what_was_taken_out(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from pipeline import visuals
    made, animated = [], []
    monkeypatch.setattr(visuals, "_segment", lambda plan, d, folder, style, props: made.append(d["index"]))
    monkeypatch.setattr(visuals, "_animate", lambda plan, ds, folder, tail: animated.append([d["index"] for d in ds]))
    monkeypatch.setattr(visuals.stage, "_save", lambda plan: None)
    monkeypatch.setattr(visuals.art, "resolve", lambda art: {"key": "ink"})
    monkeypatch.setattr(visuals, "channel_props_dir", lambda key, style: tmp_path)
    channel = ChannelConfig(key="wren")
    plan = SimpleNamespace(channel=channel, out_dir=tmp_path, stem="moon", script=None)
    keep = [{"first": 3, "last": 3, "clip": "c.mp4", "kind": "template"}]
    visuals._remake(plan, {"directions": [{"index": 0, "medium": "animation"},
                                          {"index": 2, "medium": "illustration"},
                                          {"index": 3, "medium": "template"}],
                           "keep": keep, "redo": [2], "animate": True})
    assert made == [2] and animated == [[0]] and plan.scene_clips == keep
