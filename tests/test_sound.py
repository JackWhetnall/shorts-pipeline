"""
pipeline.sound: the music bed and the scene effects. Everything here is
synthesised, so nothing needs a file but the stand-in music track each
test writes for itself.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from core.channels import ChannelConfig, channel_from_dict, channel_to_sparse_dict
from pipeline import sound
from pipeline.plan import Segment

FPS = 44100


def test_effects_are_the_same_every_time_and_never_louder_than_each_other():
    for kind in ("pop", "whoosh", "tick", "chime", "clink"):
        a, b = sound.synth(kind, FPS), sound.synth(kind, FPS)
        assert np.array_equal(a, b), kind
        assert np.abs(a).max() == pytest.approx(1.0), kind


def _plan_with_scene(tmp_path, actions):
    clip = tmp_path / "scene_1.mp4"
    clip.with_suffix(".json").write_text(json.dumps({"actions": actions}), encoding="utf-8")
    segments = [Segment("one", start=0.0, end=4.0), Segment("two", start=4.0, end=9.0)]
    return SimpleNamespace(scene_clips=[{"first": 1, "last": 1, "clip": str(clip)}],
                           script=SimpleNamespace(segments=segments), stem="v")


def test_scene_moves_become_cues_at_their_moment_in_the_narration(tmp_path):
    plan = _plan_with_scene(tmp_path, [
        {"target": "t", "do": "appear", "at": 0.5, "dur": 0.4},
        {"target": "t", "do": "appear", "at": 0.55, "dur": 0.4},      # too close: dropped
        {"target": "t", "do": "count", "at": 1.0, "dur": 2},          # no sound
        {"target": "c", "do": "stack", "at": 2.0, "dur": 2.0, "count": 2},
    ])
    cues = sound.scene_cues(plan)
    assert [(round(t, 2), k) for t, k, _ in cues] == [(4.5, "pop"), (6.7, "clink"), (7.7, "clink")]


def test_the_music_ducks_under_speech_and_rises_in_the_pauses(tmp_path):
    voice = np.zeros((FPS * 6, 2))
    t = np.arange(FPS * 2) / FPS
    voice[FPS * 2:FPS * 4] = 0.5 * np.sin(2 * np.pi * 200 * t)[:, None]  # speech from 2 s to 4 s
    track = tmp_path / "bed.wav"
    _write_tone(track, seconds=6)
    bed = sound.music_bed(track, len(voice), FPS, 2, voice, level=0.2)

    def level(a, b):
        return float(np.sqrt((bed[int(a * FPS):int(b * FPS)] ** 2).mean()))

    pause, speaking = level(1.0, 1.8), level(3.0, 3.8)
    assert speaking < pause * 0.5                  # well under the voice
    assert level(0.0, 0.1) < pause                 # fades in
    assert level(5.9, 6.0) < pause * 0.2           # and out


def test_no_music_anywhere_means_no_music_and_nothing_breaks(tmp_path, monkeypatch):
    from core import music_library
    monkeypatch.setattr(sound, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(sound, "SHARED_MUSIC_DIR", tmp_path / "music")
    asked = []
    monkeypatch.setattr(music_library, "auto_fill", lambda channel: asked.append(channel.key) or [])
    channel = ChannelConfig(key="c")
    voice = np.full((FPS, 2), 0.1)
    out = sound.mix(voice, FPS, channel, SimpleNamespace(scene_clips=[], stem="v"), lambda t: t)
    assert np.array_equal(out, voice)
    assert asked == ["c"]                         # it tried to fetch some first


def test_the_channels_own_music_comes_before_the_shared_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(sound, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(sound, "SHARED_MUSIC_DIR", tmp_path / "music")
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "shared.mp3").write_bytes(b"x")
    assert [p.name for p in sound.music_tracks("c")] == ["shared.mp3"]
    (tmp_path / "channels" / "c" / "music").mkdir(parents=True)
    (tmp_path / "channels" / "c" / "music" / "own.mp3").write_bytes(b"x")
    assert [p.name for p in sound.music_tracks("c")] == ["own.mp3"]


def test_the_mix_never_clips(tmp_path, monkeypatch):
    monkeypatch.setattr(sound, "CHANNELS_DIR", tmp_path / "channels")
    folder = tmp_path / "channels" / "c" / "music"
    folder.mkdir(parents=True)
    _write_tone(folder / "loud.wav", seconds=2, amplitude=0.99)
    channel = ChannelConfig(key="c")
    channel.sound.music_level = 1.0
    voice = np.full((FPS * 2, 2), 0.95)
    out = sound.mix(voice, FPS, channel, SimpleNamespace(scene_clips=[], stem="v"), lambda t: t)
    assert np.abs(out).max() <= 0.98 + 1e-9


def test_sound_settings_round_trip():
    channel = ChannelConfig(key="c")
    channel.sound.music = False
    channel.sound.effects_level = 0.5
    raw = channel_to_sparse_dict(channel)
    assert raw["sound"] == {"music": False, "effects_level": 0.5}
    assert channel_from_dict("c", raw).sound.effects_level == 0.5


def _write_tone(path, seconds, amplitude=0.5):
    import subprocess
    import imageio_ffmpeg
    t = np.arange(FPS * seconds) / FPS
    wave = amplitude * np.sin(2 * np.pi * 330 * t)
    pcm = (np.stack([wave, wave], 1) * 32767).astype(np.int16).tobytes()
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error", "-f", "s16le",
                    "-ar", str(FPS), "-ac", "2", "-i", "-", str(path)], input=pcm, check=True)


def test_the_settings_form_saves_sound_and_leaves_it_alone_when_absent():
    from web.forms import apply_channel_form
    channel = ChannelConfig(key="c")
    apply_channel_form(channel, {"sound_present": "1", "sound_effects": "on",
                                 "sound_music_level": "0.9", "sound_effects_level": "0.4"})
    assert channel.sound.music is False and channel.sound.effects is True
    assert channel.sound.music_level == 0.4 and channel.sound.effects_level == 0.4
    apply_channel_form(channel, {})
    assert channel.sound.effects is True
