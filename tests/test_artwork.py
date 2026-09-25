"""
pipeline.artwork: public-domain paintings as one of the director's media.
The museums and the model calls are faked; nothing leaves the machine.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.channels import ChannelConfig
from pipeline import artwork
from pipeline.plan import Script, Segment


class Response:
    def __init__(self, status=200, data=None, content=b"", ctype="application/json"):
        self.status_code, self._data, self.content = status, data or {}, content
        self.headers = {"content-type": ctype}

    def json(self):
        return self._data


def test_search_prefers_paintings_and_skips_works_without_images(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        assert "ShortsPipeline" in headers["User-Agent"]          # the museums ask for this
        if "artic" in url:
            return Response(data={"data": [
                {"id": 1, "title": "An engraving", "image_id": "a", "artwork_type_title": "Print"},
                {"id": 2, "title": "No picture", "image_id": None, "artwork_type_title": "Painting"},
                {"id": 3, "title": "The painting", "image_id": "c", "artwork_type_title": "Painting",
                 "artist_display": "Rubens\nFlemish", "date_display": "1609"}]})
        return Response(data={"objectIDs": []})

    monkeypatch.setattr(artwork.requests, "get", fake_get)
    found = artwork.search("Samson")
    assert [w["title"] for w in found] == ["The painting", "An engraving"]
    assert found[0]["artist"] == "Rubens"
    assert artwork.credit(found[0]) == "Art: The painting, Rubens (1609). Art Institute of Chicago, public domain."


def test_an_unreachable_museum_contributes_nothing(monkeypatch):
    def down(*a, **k):
        raise artwork.requests.ConnectionError("offline")
    monkeypatch.setattr(artwork.requests, "get", down)
    assert artwork.search("Samson") == []


def test_an_error_page_is_never_shown_to_the_picker(monkeypatch):
    # Regression: the image server's 403 page went to the vision model as
    # "artwork", which then rightly rejected everything.
    monkeypatch.setattr(artwork.requests, "get",
                        lambda *a, **k: Response(403, content=b"<html>", ctype="text/html"))
    monkeypatch.setattr("pipeline.llm.call_json", lambda *a, **k: pytest.fail("asked about an error page"))
    assert artwork.pick([{"thumb": "x", "title": "t", "artist": "", "kind": ""}], "passage") is None


def test_the_picker_can_say_none_fit(monkeypatch):
    monkeypatch.setattr(artwork.requests, "get",
                        lambda *a, **k: Response(content=b"jpeg", ctype="image/jpeg"))
    monkeypatch.setattr("pipeline.llm.call_json", lambda *a, **k: {"choice": 0})
    works = [{"thumb": "x", "title": "t", "artist": "", "kind": ""}]
    assert artwork.pick(works, "passage") is None
    monkeypatch.setattr("pipeline.llm.call_json", lambda *a, **k: {"choice": 1})
    assert artwork.pick(works, "passage") is works[0]


WORK = {"title": "The Capture of Samson", "artist": "Rubens", "date": "1609",
        "museum": "Art Institute of Chicago"}


def test_a_painting_is_panned_for_the_segment_and_credited(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "search", lambda q: [WORK])
    monkeypatch.setattr(artwork, "pick", lambda found, words: found[0])
    monkeypatch.setattr(artwork, "_download", lambda w: "image")
    made = {}
    monkeypatch.setattr(artwork, "ken_burns", lambda image, seconds, out: made.update(s=seconds) or out)
    clip, credit = artwork.make("Samson Delilah", "Delilah cut his hair", 6.0, tmp_path / "a.mp4")
    assert clip == tmp_path / "a.mp4" and made["s"] == 6.0
    assert credit == "Art: The Capture of Samson, Rubens (1609). Art Institute of Chicago, public domain."


def test_nothing_fitting_leaves_the_segment_to_footage(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "search", lambda q: [WORK])
    monkeypatch.setattr(artwork, "pick", lambda found, words: None)
    with pytest.raises(artwork.PipelineError):
        artwork.make("Samson Delilah", "words", 6.0, tmp_path / "a.mp4")


def test_the_setting_allows_it_and_the_old_passage_mode_still_counts():
    channel = ChannelConfig(key="c")
    assert not artwork.allowed(channel)
    channel.artwork.mode = "allowed"
    assert artwork.allowed(channel)
    channel.artwork.mode = "passage"
    assert artwork.allowed(channel)


def _segments():
    return [Segment("Delilah betrayed him", shot_brief="scissors", start=0, end=3),
            Segment("and he pulled down the temple", shot_brief="ruins", start=3, end=7)]


def test_the_director_offers_artwork_even_to_a_footage_only_channel(monkeypatch):
    """Regression: paintings were a separate stage that only ever showed
    the passage, which made the setting read as a Bible feature. They are
    a real picture, like footage, so the graphics slider doesn't gate them."""
    from pipeline import director
    seen = {}

    def call_json(system, user, schema, **kwargs):
        seen["media"] = schema["properties"]["segments"]["items"]["properties"]["medium"]["enum"]
        seen["guide"] = system[0].text
        return {"segments": [
            {"index": 0, "medium": "artwork", "template": "", "brief": "Samson Delilah",
             "need": 2, "reason": "a famous scene"},
            {"index": 1, "medium": "illustration", "template": "", "brief": "x", "need": 9,
             "reason": "not allowed here"}]}

    monkeypatch.setattr(director, "call_json", call_json)
    out = director.direct(_segments(), "Samson", share=0, artwork=True)
    assert seen["media"] == ["footage", "artwork"] and "museum" in seen["guide"]
    assert [d["medium"] for d in out] == ["artwork", "footage"]
    # Without it, a footage-only channel costs no call at all.
    monkeypatch.setattr(director, "call_json", lambda *a, **k: pytest.fail("called"))
    assert {d["medium"] for d in director.direct(_segments(), "Samson", share=0)} == {"footage"}


def test_visuals_credit_the_artwork_on_its_clip(tmp_path, monkeypatch):
    from pipeline import visuals
    from pipeline.plan import Voiceover
    channel = ChannelConfig(key="c")
    channel.artwork.mode = "allowed"
    script = Script(segments=_segments())
    plan = SimpleNamespace(channel=channel, script=script, out_dir=tmp_path, stem="v",
                           scene_clips=[], seed=SimpleNamespace(title="Samson"),
                           voiceover=Voiceover(audio_path=None, word_timings=[], samples=None, fps=1))
    monkeypatch.setattr(visuals.stage, "_restore", lambda: None)
    monkeypatch.setattr(visuals.stage, "_save", lambda plan: None)
    monkeypatch.setattr(visuals.stage, "_hook_end", lambda plan: 0.0)
    monkeypatch.setattr(visuals.director, "direct", lambda *a, **k: [
        {"index": 0, "medium": "artwork", "template": "", "brief": "Samson Delilah", "need": 2,
         "reason": ""}, {"index": 1, "medium": "footage", "template": "", "brief": "", "need": 0,
                         "reason": ""}])
    monkeypatch.setattr(visuals.artwork, "make",
                        lambda query, words, seconds, out: (out, "Art: X. Y, public domain."))
    visuals.run(plan)
    assert plan.scene_clips[0]["kind"] == "artwork"
    assert plan.scene_clips[0]["credit"] == "Art: X. Y, public domain."
    assert plan.art_credits == ["Art: X. Y, public domain."]


def test_the_description_carries_the_credit():
    from pipeline import run
    assert run._with_credits("About this.", ["Art: X, Y. Z, public domain."]) == \
        "About this.\n\nArt: X, Y. Z, public domain."
    assert run._with_credits("About this.", []) == "About this."
