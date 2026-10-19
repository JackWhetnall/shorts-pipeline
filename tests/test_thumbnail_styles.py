"""
Thumbnail styles for films (decision 115): find the style first, then
refine it, then test each film's own words and picture.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from core import thumbnail_tests as tt
from pipeline.documentary import thumb_styles as ts


def _data():
    return {"recipe": {}, "steps": {}, "tried": {}, "rounds": []}


def test_style_rounds_pit_the_champion_against_untried_styles_and_side_by_side_rounds_differ():
    data = _data()
    first = tt.doc_variants(data)
    assert [v["recipe"]["family"] for v in first] == ["panel", "band", "sticker"]
    data["rounds"].append({"kind": "film", "status": "running", "doc": True, "phase": "style", "variants": first})
    second = tt.doc_variants(data)
    assert [v["recipe"]["family"] for v in second] == ["panel", "overlay", "pop"]     # not band and sticker again


def test_a_style_that_wins_becomes_the_champion_and_two_defences_move_on_to_refining():
    data = _data()
    def play(winner_family):
        variants = tt.doc_variants(data)
        round_ = {"kind": "studio", "status": "done", "doc": True, "phase": tt.program(data)["phase"],
                  "variants": variants, "result": {}}
        data["rounds"].append(round_)
        label = next(v["label"] for v in variants if v["recipe"].get("family") == winner_family)
        tt.doc_learn(data, round_, label)
    play("sticker")
    assert tt.program(data)["champion"] == "sticker" and tt.program(data)["phase"] == "style"
    play("sticker")
    play("sticker")
    assert tt.program(data)["phase"] == "refine" and data["doc_recipe"] == {"family": "sticker"}
    refine = tt.doc_variants(data)
    assert refine[0]["recipe"] == {"family": "sticker"} and all(v["change"] for v in refine[1:])


def test_content_rounds_keep_the_house_style_and_vary_words_picture_and_title():
    data = _data()
    tt.program(data)["phase"] = "content"
    data["doc_recipe"] = {"family": "pop", "tilt": 8.0}
    angles = [{"title": "T2", "words": "W2", "subject": "s2"}, {"title": "T3", "words": "W3", "subject": "s3"}]
    v = tt.doc_variants(data, angles)
    assert v[0]["recipe"] == {"family": "pop", "tilt": 8.0}
    assert v[1]["recipe"]["words"] == "W2" and v[1]["title"] == "T2" and "draw_subject" not in v[1]["recipe"]
    assert v[2]["recipe"]["draw_subject"] == "s3" and v[2]["recipe"]["family"] == "pop"


def test_every_style_draws_and_the_original_is_unchanged(tmp_path, monkeypatch):
    art = tmp_path / "art.jpg"
    Image.new("RGB", (1536, 864), (40, 90, 160)).save(art)
    seen = {}
    monkeypatch.setattr("pipeline.documentary.thumbs.compose", lambda p, w, a, r: seen.setdefault("panel", w) and
                        Image.new("RGB", ts.SIZE))
    for name in ts.FAMILIES:
        image = ts.draw(art, art, "Copied from a weed", {"accent1": "#FFB23F", "background": "#101A3A"}, {"family": name})
        assert image.size == ts.SIZE
    assert seen["panel"] == "COPIED FROM A WEED"          # the original look comes from thumbs.compose, as before
    assert ts.describe({"family": "sticker"}).startswith("Sticker")
