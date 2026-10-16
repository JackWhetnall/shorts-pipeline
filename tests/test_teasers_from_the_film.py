"""
Teasers made from the film's own pictures, cut tall around their subject
(decision 106).
"""

from __future__ import annotations

from PIL import Image

from core.errors import PipelineError
from pipeline.documentary import vertical


def _wide(path, colour_at):
    image = Image.new("RGB", (1536, 864), (20, 20, 80))
    for x in range(colour_at - 40, colour_at + 40):
        for y in range(380, 480):
            image.putpixel((x, y), (250, 200, 0))
    image.save(path)
    return path


def test_a_narrow_subject_fills_the_frame_cut_around_it(tmp_path):
    src = _wide(tmp_path / "a.jpg", 1300)                     # the subject far right
    out = vertical.tall(src, tmp_path / "t.jpg", left=1260 / 1536, right=1340 / 1536)
    image = Image.open(out)
    assert image.size == vertical.SIZE
    r, g, b = image.getpixel((vertical.SIZE[0] // 2, vertical.SIZE[1] // 2))
    assert r > 200 and g > 150                                 # it's in the middle of the frame


def test_a_wide_subject_is_kept_whole_over_a_blurred_copy(tmp_path):
    src = _wide(tmp_path / "a.jpg", 768)
    out = vertical.tall(src, tmp_path / "t.jpg", left=0.1, right=0.9)
    image = Image.open(out)
    assert image.size == vertical.SIZE
    top = image.getpixel((10, 10))
    assert sum(top) < sum((20, 20, 80)) + 30                   # the dim backdrop above the picture


def test_a_failed_look_shows_every_picture_whole(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise PipelineError("x", user_message="x")
    monkeypatch.setattr("pipeline.llm.call_json", boom)
    paths = [_wide(tmp_path / f"{n}.jpg", 768) for n in range(2)]
    assert vertical.focus(paths) == [(0.0, 1.0), (0.0, 1.0)]


def test_teasers_are_edited_against_the_films_narration(monkeypatch):
    from pipeline.documentary import teasers
    seen = {}
    two = [{"title": "A", "scenes": [{"narration": "About a half marathon down."}, {"narration": "x"}]},
           {"title": "B", "scenes": [{"narration": "y"}]}]

    def fake(system, user, schema, **kw):
        seen["user"] = user
        return {"fixes": [{"teaser": 0, "line": 0, "problem": "invented comparison",
                           "narration": "Twelve kilometres down."},
                          {"teaser": 5, "line": 0, "problem": "no such teaser", "narration": "z"}]}
    monkeypatch.setattr(teasers, "call_json", fake)
    out = teasers.checked(two, {"scenes": [{"narration": "The hole is twelve kilometres deep."}]})
    assert out[0]["scenes"][0]["narration"] == "Twelve kilometres down." and out[1] == two[1]
    assert "twelve kilometres deep" in seen["user"] and two[0]["scenes"][0]["narration"].startswith("About")
