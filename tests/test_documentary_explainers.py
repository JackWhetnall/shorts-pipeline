"""
Explainers, gentler depth and sound that fits the picture (decision 089).

The owner, on the remade plague film: the depth "really churns the
pictures up ... panning up close is horrible"; the fire sound was "loud
and harsh and goes on through many pictured scenes, inconsistent with
what is on show"; and the film "doesn't ask or answer any questions that
a viewer might have". So:

- a pan gets depth only across the whole of a wide picture, and the
  background no longer slides the other way;
- a chapter's bed plays only under scenes that show its place, quieter,
  its crackles capped;
- a documentary channel can make explainers, whose writers are told to
  answer the viewer's questions, while story channels' prompts are
  exactly what they were.
"""

from __future__ import annotations

from types import SimpleNamespace as N

import numpy as np
import pytest

from core.channels import ChannelConfig, ConfigError
from pipeline.documentary import ambience, depth, editor, kinds, outline, script
from pipeline.documentary.render import chapter_sounds


def _channel(kind):
    return N(documentary=N(kind=kind))


def test_close_pans_move_flat_and_wide_ones_keep_depth():
    assert depth.suits("push_in", "close-up", whole=False)          # zooms looked fine
    assert depth.suits("pan_left", "wide", whole=True)
    assert not depth.suits("pan_left", "close-up", whole=True)      # faces tore
    assert not depth.suits("pan_right", "wide", whole=False)        # a crop is a close look


def test_far_things_no_longer_slide_the_wrong_way(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(depth, "FRAME", (64, 36))
    still = tmp_path / "s.jpg"
    Image.fromarray(np.random.default_rng(0).integers(0, 255, (36, 64, 3), dtype=np.uint8)).save(still)
    near = np.zeros((36, 64), dtype=np.float32)
    assert (1 + depth.PAN_SPREAD * (near - 0.5)).min() > 0              # every point moves with the camera
    assert len(list(depth.frames(still, near, 0.2, "pan_left"))) >= 2


def test_a_bed_plays_only_under_scenes_that_show_its_place():
    plan = {"chapters": [{"title": "A", "sound": "interior_fire"}]}
    scenes = [{"chapter": 1, "direction": "The baker feeds the oven at dawn"},
              {"chapter": 1, "direction": "A close-up of the boy's frightened face"},
              {"chapter": 1, "direction": "x", "medium": "card"}]
    segments = [N(start=i * 10.0, end=i * 10.0 + 10) for i in range(3)]
    assert [k for _, _, k in chapter_sounds(scenes, segments, plan)] == ["interior_fire", "none"]
    assert ambience.UNDER_DB >= 20


def test_a_crackle_is_capped(monkeypatch, tmp_path):
    loud = np.full((48000, 2), 0.01, dtype=np.float32)
    loud[100] = 1.0                                                     # one sharp crack
    monkeypatch.setattr(ambience, "make", lambda key: tmp_path / "x.mp3")
    monkeypatch.setattr("pipeline.tts.decode_audio_file", lambda path, fps: loud)
    out, problem = ambience.bed([(0, 1, "interior_fire")], 48000, 48000, voice_rms=0.1)
    target = 0.1 * 10 ** (-ambience.UNDER_DB / 20)
    assert not problem and np.abs(out).max() <= ambience.CREST * target * 1.01


def test_explainers_are_asked_for_questions_and_stories_are_unchanged():
    story, explainer = _channel("story"), _channel("explainer")
    assert "Make it a story, not a tour" in script.system_text(story)
    assert "{shape}" not in script.system_text(story) and "{cards}" not in script.system_text(story)
    text = script.system_text(explainer)
    assert "Make it a story" not in text and "next question" in text
    assert "the viewer's question" in outline.system_text(explainer)
    assert "what the person at the centre wants today" in outline.system_text(story)
    assert "{" + "momentum}" not in editor.critic_text("explainer")
    assert kinds.of(N()) == "story"


def test_a_channel_names_a_kind_it_can_make():
    channel = ChannelConfig(key="x", format="documentary", voice="EXAVITQu4vr4xnSDxMaL")
    channel.documentary.kind = "musical"
    with pytest.raises(ConfigError):
        channel.validate()


def test_a_contraction_is_not_a_word_the_title_must_name():
    from pipeline.documentary import pitch
    assert pitch.subject_words("Why Can't We Dig to the Centre of the Earth?") == {"centre", "earth"}
