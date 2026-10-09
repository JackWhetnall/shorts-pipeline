"""
A quiz short's thumbnail is its opening screen once the category and
difficulty are stamped (pipeline.thumbnails, decision 082), set on
YouTube when it goes out, and for those already out on request.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pipeline import thumbnails


def test_the_moment_is_the_boards_own_when_it_was_recorded(tmp_path):
    video = tmp_path / "science_easy.mp4"
    (tmp_path / "science_easy_quiz.json").write_text(json.dumps({"thumbnail_at": 3.235}))
    assert thumbnails.stamp_moment(video) == 3.235


def test_an_older_short_works_it_out_from_its_script(tmp_path):
    video = tmp_path / "space_hard.mp4"
    (tmp_path / "space_hard_quiz.json").write_text("{}")
    (tmp_path / "space_hard_script.json").write_text(json.dumps({
        "quiz": {"hook": "Space quiz, ready?"},
        "segments": [{"text": "Space quiz, ready?", "start": 0.0, "end": 3.0, "pause_after": None}]}))
    # Its last word at 2.6 (the 0.4 s pause), the stamp 0.15 later, settled 0.55 after.
    assert thumbnails.stamp_moment(video) == pytest.approx(2.6 + 0.15 + 0.55)


def test_with_no_record_it_looks_for_the_stamp(tmp_path):
    from moviepy.editor import VideoClip
    cream, ink = np.array([240, 232, 215]), np.array([180, 100, 50])

    def frame(t):
        image = np.tile(cream, (192, 108, 1)).astype(np.uint8)
        if t >= 2.0:                                  # the stamp lands in the middle band
            image[100:125, 20:88] = ink
        if t >= 5.0:                                  # and the hook screen clears
            image[:] = cream
        return image
    video = tmp_path / "old.mp4"
    VideoClip(frame, duration=6.5).write_videofile(str(video), fps=10, logger=None, codec="libx264")
    at = thumbnails.find_stamp(video)
    assert 2.2 <= at <= 2.8


def test_every_quiz_short_gets_a_cover_used_as_its_poster_too(tmp_path, monkeypatch):
    from core import gallery
    day = tmp_path / "2026-10-01"
    day.mkdir()
    for stem in ("science_easy", "minute_short"):
        (day / f"{stem}.mp4").write_bytes(b"x")
    (day / "science_easy_quiz.json").write_text(json.dumps({"thumbnail_at": 3.0}))
    monkeypatch.setattr(gallery, "resolve_output_dir", lambda d: tmp_path)
    taken = []

    def fake_frame(video, at, out):
        taken.append((Path(video).stem, at))
        Path(out).write_bytes(b"jpeg")
        return Path(out)
    monkeypatch.setattr(thumbnails, "frame", fake_frame)
    channel = SimpleNamespace(output_dir="pqb", pacing=SimpleNamespace(pause_between_segments=0.4))
    assert thumbnails.channel_covers(channel) == 1                      # only the quiz short
    assert taken == [("science_easy", 3.0)]
    assert (day / "science_easy_thumb.jpg").read_bytes() == b"jpeg"
    assert thumbnails.channel_covers(channel) == 0                      # made already


def test_covers_go_on_youtube_once_and_again_if_they_change(tmp_path, monkeypatch):
    import os
    import time
    from core import gallery, publish_queue, youtube
    day = tmp_path / "2026-10-01"
    day.mkdir()
    (day / "a.mp4").write_bytes(b"x")
    (day / "a_cover.jpg").write_bytes(b"jpeg")
    (day / "b.mp4").write_bytes(b"x")                                   # not on YouTube
    (day / "b_cover.jpg").write_bytes(b"jpeg")
    monkeypatch.setattr(gallery, "resolve_output_dir", lambda d: tmp_path)
    links = {"a": "https://www.youtube.com/shorts/abc123DEF45", "b": ""}
    monkeypatch.setattr(gallery, "load_publish_info", lambda v: {"youtube_url": links[Path(v).stem], "title": "A"})
    sent = []
    monkeypatch.setattr(youtube, "set_thumbnail", lambda key, video_id, path: sent.append((video_id, path.name)))
    channel = SimpleNamespace(key="pqb", output_dir="pqb")
    assert [v.stem for v in publish_queue.covers_to_set(channel)] == ["a"]
    assert publish_queue.set_covers(channel) == {"set": 1, "failed": []}
    assert sent == [("abc123DEF45", "a_cover.jpg")]
    assert publish_queue.covers_to_set(channel) == []
    later = time.time() + 10
    os.utime(day / "a_cover.jpg", (later, later))
    assert [v.stem for v in publish_queue.covers_to_set(channel)] == ["a"]


def test_a_refusal_is_said_and_stops_the_rest(tmp_path, monkeypatch):
    from core import gallery, publish_queue, youtube
    from core.errors import PipelineError
    day = tmp_path / "d"
    day.mkdir()
    for stem in ("a", "b"):
        (day / f"{stem}.mp4").write_bytes(b"x")
        (day / f"{stem}_cover.jpg").write_bytes(b"jpeg")
    monkeypatch.setattr(gallery, "resolve_output_dir", lambda d: tmp_path)
    monkeypatch.setattr(gallery, "load_publish_info", lambda v: {"youtube_url": "https://youtu.be/x1x1x1x1x1x", "title": "T"})

    def refuse(key, video_id, path):
        raise PipelineError("403", user_message="The account needs verifying before custom thumbnails.")
    monkeypatch.setattr(youtube, "set_thumbnail", refuse)
    result = publish_queue.set_covers(SimpleNamespace(key="pqb", output_dir="pqb"))
    assert result["set"] == 0 and len(result["failed"]) == 1
