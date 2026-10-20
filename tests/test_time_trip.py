"""
A time trip (decision 124): the owner's format for History's Bottom
Drawer. Emily, the channel's star, answers one cheeky question by
travelling through time and trying it herself; a narrator, and real
people only where they matter.

- the kind reaches its writers, has its own dialogue rules, and its
  facts are checked like any film that teaches;
- the channel's recurring cast is in every outline, as the channel
  describes them, whatever the writer made of them;
- a recurring character keeps one voice in every film; everyone else
  still gets a voice of their own, never the narrator's;
- shortlisted Voice Library voices are listed with their previews, and
  can't be test-voiced until they're in the account.
"""

from __future__ import annotations

import json

from core.channels import ChannelConfig
from pipeline.documentary import kinds, outline, render, script

STAR = {"name": "Emily", "description": "the channel's star: a woman in her mid-twenties, chestnut hair"}


def _channel():
    channel = ChannelConfig(key="c", channel_display_name="C", format="documentary", voice="narrator")
    channel.documentary.kind = "time_trip"
    channel.documentary.dialogue = True
    channel.animation.cast = [STAR]
    return channel


def test_the_kind_reaches_its_writers_and_is_fact_checked():
    channel = _channel()
    assert "bottom drawer" in outline.system_text(channel) and "journey" in script.system_text(channel)
    assert kinds.fact_checked("time_trip") and not kinds.fact_checked("story")
    assert kinds.family("time_trip") == "story"
    system = " ".join(b.text for b in script._system(channel))
    assert "the star talks all the way through" in " ".join(system.split())
    channel.documentary.kind = "story"
    assert "the person the viewer plays never does" in " ".join(" ".join(b.text for b in script._system(channel)).split())


def test_the_star_is_in_every_outline_as_the_channel_describes_her():
    data = {"settings": [{"name": "Brighton beach"}, {"name": "Roman villa"}],
            "cast": [{"name": "emily", "kind": "character", "description": "a girl with red hair"},
                     {"name": "Louis Réard", "kind": "character", "description": "a Frenchman"}]}
    out = outline.with_recurring(data, outline.recurring(_channel()))
    assert out["cast"][0] == {"name": "Emily", "kind": "character", "description": STAR["description"],
                              "settings": ["Brighton beach", "Roman villa"]}
    assert [m["name"] for m in out["cast"]] == ["Emily", "Louis Réard"]
    assert outline.with_recurring(data, []) == data


def test_a_recurring_character_keeps_her_voice_and_others_get_their_own():
    channel = _channel()
    channel.documentary.voices = {"Emily": "emily-voice"}
    scenes = [{"speaker": "Louis Réard"}, {"speaker": "Emily"}, {"speaker": ""}, {"speaker": "Annette Kellerman"}]
    plan = {"cast": [{"name": "Annette Kellerman", "description": "a swimmer, she"}]}
    voices = render.voices_for(channel, plan, scenes)
    assert voices["Emily"] == "emily-voice"
    assert len(set(voices.values())) == 3 and "narrator" not in voices.values()
    assert voices["Annette Kellerman"] in render.FEMALE_VOICES and voices["Louis Réard"] in render.MALE_VOICES


def test_shortlisted_library_voices_are_listed_and_need_adding_before_a_test(tmp_path, monkeypatch):
    from core import voice_lab
    monkeypatch.setattr(voice_lab, "VOICES_CACHE_PATH", tmp_path / "voices.json")
    monkeypatch.setattr(voice_lab, "LIBRARY_PATH", tmp_path / "library.json")
    (tmp_path / "voices.json").write_text(json.dumps([{"voice_id": "p1", "name": "Premade", "category": "premade"}]))
    voice_lab.shortlist([{"voice_id": "lib1", "name": "Emily - Soft & Sweet", "preview_url": "https://x/1.mp3"},
                         {"voice_id": "p1", "name": "Premade again"}])
    listed = voice_lab.get_cached_voices()
    assert [v["voice_id"] for v in listed] == ["p1", "lib1"] and listed[1]["category"] == voice_lab.LIBRARY
    assert listed[1]["preview_url"] == "https://x/1.mp3"
    assert [v["voice_id"] for v in voice_lab.get_cached_voices(library=False)] == ["p1"]
    from tests.test_web import csrf
    from web import create_app
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        refused = client.post("/api/voice-lab/test", json={"voice_id": "lib1", "preset": "natural", "speed": 1},
                              headers={"X-CSRF-Token": csrf(client)})
    assert refused.status_code == 400 and "Add this voice in ElevenLabs first" in refused.get_json()["error"]


def test_a_star_is_drawn_from_her_face_and_dressed_as_each_picture_says():
    # Found on 20 Oct: a full-length sheet gave Emily a cardigan and jeans,
    # copied into a Roman villa and a Rio beach; and two pictures whose
    # direction named her, but whose cast didn't, drew a stranger.
    from pipeline.animation import bible, keyframes
    from pipeline.documentary import stills
    from core.channels import Animation
    from pipeline.animation import style
    look = style.compile(Animation(enabled=True, style={"approach": "acted", "stage": "animated_film",
                                                        "material": "cel_2d", "people": "cartoon"}), frame="wide")[1]
    sheet = bible.sheet_prompt("star", "Emily", "a woman with chestnut hair", look)
    assert "head-and-shoulders" in sheet and "no clothing in view" in sheet
    board = {"elements": {"emily": {"kind": "character", "name": "Emily", "description": "d", "star": True},
                          "reard": {"kind": "character", "name": "Louis Réard", "description": "d"}}}
    shot = {"framing": "medium", "image": "Emily in a string bikini", "elements": ["emily", "reard"]}
    prompt = keyframes.prompt_for(shot, board, look, [("emily", board["elements"]["emily"]),
                                                      ("reard", board["elements"]["reard"])])
    assert "Emily: the same face, hair, colouring and figure, dressed as this frame says" in prompt
    assert "Louis Réard: draw them exactly as shown there, with the same face, hair, clothes" in prompt
    found = stills.shots([{"direction": "Emily in a neon swimsuit on the sand", "cast": []},
                          {"direction": "A drawer glowing", "cast": []}], ["Emily"])
    assert found[0]["elements"] == ["emily"] and found[1]["elements"] == []
