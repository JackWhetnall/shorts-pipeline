"""
A voiceover that hits a hiccup at the voice service (pipeline.tts).

The owner: a video failed because ElevenLabs took too long over one line,
with a message saying retrying usually works; and the retry voiced all
23 lines again. So:
- a request that times out or can't connect is tried again by itself;
- every line voiced is kept as it lands, and retrying the job voices only
  the lines it didn't get.
"""

from __future__ import annotations

import numpy as np
import pytest
import requests

from core import job_context
from core.channels import Pacing
from core.errors import ExternalServiceError
from pipeline import tts
from pipeline.plan import Segment, WordTiming


class _Ok:
    status_code = 200
    headers = {}

    def raise_for_status(self):
        pass


def test_a_request_that_times_out_is_tried_again(monkeypatch):
    calls = []

    def post(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise requests.Timeout("read timed out")
        return _Ok()

    monkeypatch.setattr(tts.requests, "post", post)
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    monkeypatch.setattr(tts, "_api_key", lambda: "k")
    assert isinstance(tts._post_with_backoff("v", {}), _Ok) and len(calls) == 3


def test_a_service_that_never_answers_says_what_is_kept(monkeypatch):
    def post(*a, **k):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(tts.requests, "post", post)
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    monkeypatch.setattr(tts, "_api_key", lambda: "k")
    with pytest.raises(ExternalServiceError) as caught:
        tts._post_with_backoff("v", {})
    assert "already voiced are kept" in caught.value.user_message


@pytest.fixture
def voice(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "VOICE_CACHE_DIR", tmp_path / "voices")
    monkeypatch.setattr(job_context, "checkpoint_dir", lambda job_id: tmp_path / "job" if job_id else None)
    (tmp_path / "job").mkdir()
    monkeypatch.setattr(tts, "decode_audio_file", lambda path, fps: np.zeros((4410, 1)))
    monkeypatch.setattr(tts, "_stitch", lambda results, segments, out: ([], np.zeros((1, 1)), tts.SAMPLE_RATE))
    said, failing = [], set()

    def fake(text, voice_id, out_path, speed=1.0, **kw):
        if text in failing:
            raise ExternalServiceError("The voice service (ElevenLabs)", "timeout", user_message="x")
        said.append(text)
        open(out_path, "wb").write(b"mp3")
        return [WordTiming(text.split()[0], 0.0, 0.5)], np.zeros((4410, 1)), tts.SAMPLE_RATE

    monkeypatch.setattr(tts, "synthesize_segment", fake)
    return said, failing, tmp_path


def test_retrying_a_failed_voiceover_voices_only_what_it_didnt_get(voice):
    said, failing, tmp_path = voice
    lines = [Segment("One line."), Segment("Two line."), Segment("Three line.")]
    token = job_context.set_job_id("job1")
    try:
        failing.add("Two line.")
        with pytest.raises(ExternalServiceError):
            tts.generate_voiceover(lines, None, "v", str(tmp_path / "a.mp3"), Pacing())
        assert sorted(said) == ["One line.", "Three line."]
        said.clear()
        failing.clear()
        assert tts.characters_to_voice(lines, None, Pacing(), 0, "v", 1.0) == len("Two line.")
        tts.generate_voiceover(lines, None, "v", str(tmp_path / "b.mp3"), Pacing())
        assert said == ["Two line."]
    finally:
        job_context._current_job_id.reset(token)


def test_a_new_job_voices_everything_afresh(voice):
    said, _, tmp_path = voice
    lines = [Segment("One line."), Segment("Two line.")]
    token = job_context.set_job_id("job1")
    try:
        tts.generate_voiceover(lines, None, "v", str(tmp_path / "a.mp3"), Pacing())
        for f in (tmp_path / "job").iterdir():
            f.unlink()                                           # another job: no record of these
        said.clear()
        tts.generate_voiceover(lines, None, "v", str(tmp_path / "b.mp3"), Pacing())
        assert len(said) == 2
    finally:
        job_context._current_job_id.reset(token)
