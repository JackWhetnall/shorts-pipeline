"""
The second attempt at a documentary that holds people (decision 087).

The owner, of the first One Day In History film: "very similar,
watercolours, same voice - also the script voicing isnt very inspiring
... the visuals look a bit like a powerpoint. the pictures are gloomy ...
and then these bright visuals (that are stylistically odd, and some of
the info seems pointless) appear and it is quite jarring."

Measured: its drawn pictures averaged 16% brightness, its cards 76%; both
channels' narrators were premade middle-aged British men; nothing moved
in a picture but the camera; the story was a tour, someone watching.

- the voice: a channel can be voiced with ElevenLabs v4, whose delivery
  cues ([whispers]) are performed, never said, never shown as words;
  characters speak their own lines in their own voices;
- the script: someone wants something, characters speak, chapters end on
  turns; the editor catches a phrase the film keeps restating;
- the pictures: a dark still is lifted towards daylight, embers or dust
  or rain drift over a scene that has them, cuts land on the starts of
  sentences, and a card is drawn over the picture before it;
- the sound: each chapter's background bed, under the voice, when the
  ElevenLabs key may make them.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.channels import ChannelConfig
from pipeline import tts
from pipeline.documentary import ambience, atmosphere, cards, editor, media, render, shots
from pipeline.documentary import outline as outlines
from pipeline.documentary import script as scripts


# --- the voice ---------------------------------------------------------------------------

def test_delivery_cues_are_performed_never_said_or_shown():
    assert tts.strip_tags("[whispers] Get up. [laughs softly] Fine.") == "Get up. Fine."
    alignment = {"characters": list("[tense] Run."), "character_start_times_seconds": [i / 10 for i in range(12)],
                 "character_end_times_seconds": [(i + 1) / 10 for i in range(12)]}
    assert [w.word for w in tts.words_from_alignment(tts.without_tags(alignment))] == ["Run."]


class _Response:
    def __init__(self, text):
        self.headers = {}
        self._text = text

    def json(self):
        chars = list(self._text)
        return {"audio_base64": base64.b64encode(b"fake").decode(),
                "alignment": {"characters": chars, "character_start_times_seconds": [i * .05 for i in range(len(chars))],
                              "character_end_times_seconds": [(i + 1) * .05 for i in range(len(chars))]}}


@pytest.fixture
def engine(monkeypatch):
    sent = []

    def post(voice_id, payload):
        sent.append({"voice": voice_id, **payload})
        return _Response(payload["text"])
    monkeypatch.setattr(tts, "_post_with_backoff", post)
    monkeypatch.setattr(tts, "decode_audio_file", lambda path, fps=44100: np.zeros(4410, dtype=np.float32))
    monkeypatch.setattr(tts, "transcript_match_ratio", lambda text, path: 1.0)
    monkeypatch.setattr(tts.costs, "record_elevenlabs", lambda *a, **k: None)
    return sent


def test_a_tagged_model_gets_its_cues_and_others_never_do(engine, tmp_path):
    tts.synthesize_segment("[whispers] Get up.", "v1", str(tmp_path / "a.mp3"), model="eleven_v4_turbo")
    tts.synthesize_segment("[whispers] Get up.", "v1", str(tmp_path / "b.mp3"))
    assert engine[0]["model_id"] == "eleven_v4_turbo" and engine[0]["text"].startswith("[whispers]")
    assert engine[1]["model_id"] == tts.ELEVENLABS_MODEL and engine[1]["text"] == "Get up."


def test_the_shorts_voice_is_cached_exactly_as_before():
    # The frozen channels' cached lines stay findable: no model named is the old model.
    assert tts.segment_key("Hi.", "v", 1.0) == tts.segment_key("Hi.", "v", 1.0, model=tts.ELEVENLABS_MODEL)
    assert tts.segment_key("Hi.", "v", 1.0) != tts.segment_key("Hi.", "v", 1.0, model="eleven_v4_turbo")


def test_characters_speak_in_their_own_voices(engine, tmp_path, monkeypatch):
    from core.channels import Pacing
    from pipeline.plan import Segment
    monkeypatch.setattr(tts, "VOICE_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(tts, "_stitch", lambda results, segments, out, close=False: ([], np.zeros(10), 44100))
    segments = [Segment(text="You wake."), Segment(text="Up, boy!"), Segment(text="You get up.")]
    tts.generate_voiceover(segments, None, "narrator", str(tmp_path / "v.mp3"), Pacing(), close=True,
                           model="eleven_v4_turbo", voices={1: "master"})
    assert sorted((p["text"], p["voice"]) for p in engine) == [
        ("Up, boy!", "master"), ("You get up.", "narrator"), ("You wake.", "narrator")]


def test_each_speaking_character_gets_a_voice_of_their_own():
    channel = ChannelConfig(key="d", format="documentary", voice="ILYR1zZ55hoDF4bpSxND")
    channel.documentary.dialogue = True
    outline = {"cast": [{"name": "Master Baker", "description": "a stout man in his fifties"},
                        {"name": "Goodwife Allen", "description": "a pale woman at a window"},
                        {"name": "City Watchman", "description": "a weary man with a halberd"}]}
    scenes = [{"speaker": "Goodwife Allen"}, {"speaker": "Master Baker"}, {"speaker": "City Watchman"}, {}]
    voices = render.voices_for(channel, outline, scenes)
    assert voices["Goodwife Allen"] in render.FEMALE_VOICES
    assert voices["Master Baker"] in render.MALE_VOICES and voices["City Watchman"] in render.MALE_VOICES
    assert len(set(voices.values())) == 3 and channel.voice not in voices.values()
    channel.documentary.dialogue = False
    assert render.voices_for(channel, outline, scenes) == {}


# --- the script ------------------------------------------------------------------------------

def _raw(speaker):
    return {"scenes": [{"chapter": 1, "direction": "d", "cast": [], "framing": "wide", "camera": "push_in",
                        "caption": "", "narration": "Up, boy!", "medium": "picture", "art_query": "", "speaker": speaker,
                        "card": {"kind": "none", "heading": "", "value": "", "caption": "", "items": [], "lat": 0, "lon": 0}}],
            "description": ""}


def test_only_a_cast_character_speaks_and_only_when_the_channel_uses_dialogue():
    outline = {"chapters": [{"title": "A"}], "cast": [{"name": "Master Baker", "kind": "character"},
                                                      {"name": "The Bakery", "kind": "place"}]}
    spoken = scripts.clean(_raw("master baker"), outline, dialogue=True)["scenes"][0]
    assert spoken["speaker"] == "Master Baker" and "Master Baker" in spoken["cast"]
    assert "speaker" not in scripts.clean(_raw("The Bakery"), outline, dialogue=True)["scenes"][0]
    assert "speaker" not in scripts.clean(_raw("Master Baker"), outline, dialogue=False)["scenes"][0]


def test_the_editor_hears_a_phrase_the_film_keeps_restating():
    scenes = [{"narration": f"The law that keeps you here is the law that feeds them. Line {i}."} for i in range(3)]
    assert ("the law that", 6) in editor.restated(scenes)


def test_a_cold_open_chapter_is_named_by_its_turn():
    assert outlines.chapter_title("Cold Open", "The gates are shutting, and you are still inside.") == \
        "The gates are shutting, and you are still inside"


# --- the pictures ------------------------------------------------------------------------------

def test_a_dark_still_is_lifted_towards_daylight_but_a_night_scene_less(tmp_path):
    dark = tmp_path / "dark.jpg"
    Image.new("RGB", (64, 36), (40, 34, 30)).save(dark)
    bright = tmp_path / "bright.jpg"
    Image.new("RGB", (64, 36), (180, 170, 160)).save(bright)
    day, night = atmosphere.exposure(dark, "a lane at noon"), atmosphere.exposure(dark, "a candlelit room at night")
    gamma = lambda f: float(f[0].split("gamma=")[1].split(":")[0])        # noqa: E731
    assert day and night and gamma(day) > gamma(night) >= 1.05
    assert atmosphere.exposure(bright, "noon") == []                     # never darkened


def test_air_is_chosen_by_what_the_scene_has_and_loops_without_a_seam():
    assert atmosphere.pick("The apprentice pulls loaves from the glowing oven") == "embers"
    assert atmosphere.pick("A wet street in the rain") == "rain"
    assert atmosphere.pick("Wide shot of a green meadow") is None
    particles = atmosphere._particles("dust", np.random.default_rng(2))
    first = np.asarray(atmosphere._frame("dust", particles, 0.0))
    assert np.abs(first.astype(int) - np.asarray(atmosphere._frame("dust", particles, 1.0)).astype(int)).mean() == 0


def test_a_shot_with_air_and_a_lift_renders(tmp_path):
    from pipeline.animation import finish
    still = tmp_path / "s.jpg"
    Image.new("RGB", (320, 180), (50, 40, 35)).save(still)
    air = tmp_path / "air.mp4"
    finish.camera_shot(still, air, 1.0, {"frame": "wide"})               # stands in for a loop clip
    out = finish.camera_shot(still, tmp_path / "shot.mp4", 1.2, {"frame": "wide"}, "push_in",
                             adjust=["eq=gamma=1.5"], atmosphere=air, atmosphere_strength=0.5)
    assert out.exists() and out.stat().st_size > 1000


def test_cuts_land_on_the_starts_of_sentences():
    from pipeline.tts import WordTiming
    words = [WordTiming("You", 0.0, 0.2), WordTiming("wake.", 0.3, 0.6), WordTiming("It's", 4.6, 4.8),
             WordTiming("cold,", 5.0, 5.3), WordTiming("bitter.", 8.4, 8.8)]
    beats = render.beats_in(words, 0.0, 12.0)
    assert beats == [4.6, 8.4]                     # the words after a full stop or comma
    assert shots._lengths(12.0, 3, beats) == [4.6, 3.8, 3.6]


def test_a_card_is_drawn_over_the_picture_before_it(tmp_path):
    pictures = {0: tmp_path / "a.jpg", 2: tmp_path / "c.jpg"}
    Image.new("RGB", (32, 18), (90, 60, 40)).save(pictures[0])
    scenes = [{"medium": "picture"}, {"medium": "card"}, {"medium": "picture"}]
    assert media.backdrop_for(1, pictures, scenes) == pictures[0]
    style = {"key": "parchment", "colors": {"ink": "#222222", "ink_soft": "#555555", "label_fill": "#FFFFFF",
             **{f"accent{i}": "#E3A93D" for i in range(1, 6)}}, "background": {"color": "#FBF4E6"},
             "font_display": "Palatino Linotype", "font_text": "Palatino Linotype"}
    card = {"kind": "number", "heading": "London", "value": "1 in 5", "caption": "gone"}
    over = cards.build(card, style, 5.0, backdrop=pictures[0])
    assert "bg-photo" in over and "data:image/jpeg;base64," in over and "backdrop-filter" in over
    assert "bg-photo" not in cards.build(card, style, 5.0)


# --- the sound ---------------------------------------------------------------------------------

def test_each_chapter_gets_its_bed_looped_and_crossfaded(tmp_path, monkeypatch):
    fps = 1000
    monkeypatch.setattr(ambience, "make", lambda key: tmp_path / f"{key}.mp3")
    tone = {"interior_fire": np.ones((500, 2), dtype=np.float32), "street_quiet": -np.ones((500, 2), dtype=np.float32)}
    monkeypatch.setattr("pipeline.tts.decode_audio_file", lambda path, fps=1000: tone[Path(path).stem])
    out, problem = ambience.bed([(0, 3, "interior_fire"), (3, 6, "street_quiet"), (6, 7, "none")], fps, 7000, 0.1)
    level = 0.1 * 10 ** (-ambience.UNDER_DB / 20)
    assert problem == "" and out.shape == (7000, 2)
    assert np.isclose(out[1500, 0], level, atol=1e-4) and np.isclose(out[4500, 0], -level, atol=1e-4)
    assert abs(out[6900, 0]) < 1e-6                                      # "none" is silence


def test_without_the_permission_the_film_is_made_without_beds(monkeypatch, tmp_path):
    from core.errors import ExternalServiceError

    def refused(key):
        raise ExternalServiceError("ElevenLabs", "401", user_message="The ElevenLabs key can't make sound effects.")
    monkeypatch.setattr(ambience, "make", refused)
    out, problem = ambience.bed([(0, 1, "rain")], 1000, 1000, 0.1)
    assert not out.any() and "can't make sound effects" in problem


def test_an_outline_chapter_names_its_sound_or_none():
    data = {"chapters": [{"title": "A", "says": "s", "turn": "t", "shows": "w", "sound": "rain", "minutes": 1},
                         {"title": "B", "says": "s", "turn": "t", "shows": "w", "sound": "jazz", "minutes": 1}]}
    assert [c["sound"] for c in outlines.clean(data, 2)["chapters"]] == ["rain", "none"]
