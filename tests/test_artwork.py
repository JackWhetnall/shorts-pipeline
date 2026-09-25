"""
pipeline.artwork: public-domain paintings under the passage. The museums
and the vision call are faked; nothing leaves the machine.
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


def _plan(tmp_path, mode="passage", query="Samson Delilah"):
    channel = ChannelConfig(key="c")
    channel.artwork.mode = mode
    script = Script(segments=[Segment("hook", start=0, end=2), Segment("verse", start=2, end=8),
                              Segment("notes", start=8, end=12)],
                    citation="Judges 16:8", source_index=1, art_query=query)
    return SimpleNamespace(channel=channel, script=script, out_dir=tmp_path, stem="v", scene_clips=[])


def test_the_painting_goes_under_the_passage_and_is_credited(tmp_path, monkeypatch):
    work = {"title": "The Capture of Samson", "artist": "Rubens", "date": "1609",
            "museum": "Art Institute of Chicago"}
    monkeypatch.setattr(artwork, "search", lambda q: [work])
    monkeypatch.setattr(artwork, "pick", lambda found, passage: found[0])
    monkeypatch.setattr(artwork, "_download", lambda w: "image")
    made = {}
    monkeypatch.setattr(artwork, "ken_burns", lambda image, seconds, out: made.update(s=seconds) or out)
    plan = artwork.run(_plan(tmp_path))
    assert plan.scene_clips == [{"first": 1, "last": 1, "clip": str(tmp_path / "v_art.mp4"),
                                 "kind": "artwork"}]
    assert made["s"] == pytest.approx(6.0 + plan.channel.pacing.crossfade)
    assert plan.art_credits == ["Art: The Capture of Samson, Rubens (1609). Art Institute of Chicago, public domain."]


def test_off_or_nothing_to_search_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "search", lambda q: pytest.fail("searched"))
    assert artwork.run(_plan(tmp_path, mode="off")).scene_clips == []
    assert artwork.run(_plan(tmp_path, query="")).scene_clips == []


def test_a_failure_keeps_the_footage(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "search", lambda q: [{"title": "x"}])
    monkeypatch.setattr(artwork, "pick", lambda found, passage: found[0])

    def broken(work):
        raise artwork.PipelineError("no", user_message="A painting couldn't be downloaded.")

    monkeypatch.setattr(artwork, "_download", broken)
    plan = artwork.run(_plan(tmp_path))
    assert plan.scene_clips == [] and plan.art_credits == []




def test_the_description_carries_the_credit():
    from pipeline import run
    assert run._with_credits("About this.", ["Art: X, Y. Z, public domain."]) == \
        "About this.\n\nArt: X, Y. Z, public domain."
    assert run._with_credits("About this.", []) == "About this."
