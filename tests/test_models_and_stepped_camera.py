"""
Decision 121.

- The newer models for every channel but the frozen ones, which keep the
  models they were made with (decision 075): by channel key while their
  work is done, and around their own pipelines.
- A Haiku 5.5 call is given room to think and runs at low effort; a
  frozen channel's goes to Haiku 4.5 as it was, with no effort.
- A stop-motion look's camera moves in held, hand-nudged steps; every
  other look moves smoothly, as before.
"""

from __future__ import annotations

import re
import subprocess

from PIL import Image

import pytest

from core import costs, job_context
from pipeline import llm
from pipeline.animation import finish


@pytest.fixture(autouse=True)
def no_job():
    token = job_context.set_channel_key(None)
    yield
    job_context._current_channel_key.reset(token)


def _request(model, effort=None, max_tokens=800):
    request = {"model": model, "max_tokens": max_tokens, "messages": []}
    if effort:
        request["output_config"] = {"effort": effort}
    return request


def test_a_fast_call_has_room_to_think_and_runs_at_low_effort():
    pinned = llm._pin(_request(llm.FAST_MODEL))
    assert pinned["model"] == "claude-haiku-5-5" and pinned["output_config"] == {"effort": "low"}
    assert pinned["max_tokens"] > 800 * 1.3 + 1000
    assert llm._pin(_request(llm.FAST_MODEL, "medium"))["output_config"] == {"effort": "medium"}
    assert llm._pin(_request(llm.DEFAULT_MODEL, "low")) == _request("claude-sonnet-5-5", "low")


def test_a_frozen_channels_work_goes_to_the_models_it_was_made_with():
    with llm.for_channel("minute_pastor"):
        assert llm._pin(_request(llm.DEFAULT_MODEL, "low")) == _request("claude-sonnet-5", "low")
        # Haiku 4.5 refuses an effort, and its budget is as it always was.
        assert llm._pin(_request(llm.FAST_MODEL, "low")) == _request("claude-haiku-4-5")
    token = job_context.set_channel_key("pub_quiz_buzz")
    try:
        assert llm._pin(_request(llm.DEFAULT_MODEL))["model"] == "claude-sonnet-5"
        # Named outright, another channel's work isn't pinned by the job's.
        with llm.for_channel("why_though"):
            assert llm._pin(_request(llm.DEFAULT_MODEL))["model"] == "claude-sonnet-5-5"
    finally:
        job_context._current_channel_key.reset(token)


def test_the_new_models_are_priced():
    assert costs.CLAUDE_PRICES["claude-sonnet-5-5"] == costs.CLAUDE_PRICES["claude-sonnet-5"]
    assert costs.CLAUDE_PRICES["claude-haiku-5-5"].input == 0.10


def test_only_a_stop_motion_look_moves_in_steps():
    assert finish.stepped_filters({"cadence": "ones", "jitter": 0}, 1920, 1080) == []
    assert finish.stepped_filters({"cadence": "twos"}, 1920, 1080) == []          # the paper, held still
    stepped = finish.stepped_filters({"cadence": "twos", "jitter": 1.3}, 1920, 1080)
    assert stepped[0] == "fps=12" and stepped[-1] == f"fps={finish.FPS}"
    assert stepped[1].startswith("crop=1914:1074:")


def test_a_stepped_shot_renders(tmp_path):
    image = tmp_path / "still.png"
    Image.new("RGB", (320, 180), (200, 120, 40)).save(image)
    look = {"frame": "wide", "grade": {}, "cadence": "twos", "jitter": 1.3}
    out = finish.camera_shot(image, tmp_path / "shot.mp4", 1.0, look, "push_in")
    found = subprocess.run([finish._ffmpeg(), "-i", str(out), "-map", "0:v", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    assert re.search(r"Video: .*1920x1080", found)
    assert int(re.findall(r"frame=\s*(\d+)", found)[-1]) == finish.FPS
