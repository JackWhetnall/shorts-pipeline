"""
Pictures drawn once, faults looked for closely, labels per channel and
titles swapped for free (decision 090).

The owner, on the first Why, Though? film: the depth "is still
distorting shapes in a slightly sickening way"; "this video doesn't need
the bottom-left labels ... a default label that is shared between all
channels"; a drill with a face and a character with three arms got
through; the Earth cutaway "only needed to be generated once"; and the
title could have been a better one from the Angle page.
"""

from __future__ import annotations

import pytest
from PIL import Image

from core import production
from core.channels import ChannelConfig, ConfigError, Documentary
from pipeline.documentary import run, stills
from pipeline.documentary.render import label_overlay
from tests.test_documentary_reuse import _made, _scene, world  # noqa: F401 - the fixture


def test_depth_is_off_unless_a_channel_asks():
    assert Documentary().depth is False


def test_labels_are_a_channel_choice():
    assert Documentary().captions == "corner"
    channel = ChannelConfig(key="x", format="documentary", voice="EXAVITQu4vr4xnSDxMaL")
    channel.documentary.captions = "banner"
    with pytest.raises(ConfigError):
        channel.validate()
    art = {"accent1": "#FF5E5B", "ink": "#1F2A44"}
    corner = label_overlay((640, 360), caption="1970", art=art)
    tag = label_overlay((640, 360), caption="1970", art=art, style="tag")
    assert corner.getbbox()[1] > 250 and tag.getbbox()[3] < 120       # lower left; top left
    assert (255, 94, 91) in {p[:3] for p in tag.getdata() if p[3] == 255}   # the channel's own colour


def _rows(*pairs):
    return {"reuse": [{"scene": a, "same_as": b} for a, b in pairs]}


def test_a_repeated_picture_is_drawn_once_and_only_when_it_truly_repeats(monkeypatch):
    scenes = [_scene("Earth cutaway", cast=()), _scene("A rig"), _scene("Earth cutaway again", cast=()),
              _scene("Earth cutaway, close", cast=(), framing="close-up"), _scene("Earth cutaway", cast=()),
              {**_scene("x"), "medium": "card"}]
    monkeypatch.setattr("pipeline.llm.call_json", lambda *a, **k: _rows(
        (2, 0),        # fine
        (3, 0),        # a different framing: drawn
        (4, 2),        # a reuse of a reuse: drawn
        (1, 0),        # a different cast, and the scene just after: drawn
        (5, 0)))       # a card: not a picture
    assert stills.repeats(scenes, list(range(6))) == {2: 0}


def test_the_stage_copies_a_repeated_picture_instead_of_paying_for_it(world, monkeypatch):  # noqa: F811
    channel, row = world
    scenes = [_scene("Earth cutaway", cast=()), _scene("Gaius runs"), _scene("Earth cutaway", cast=())]
    _made(channel, row, scenes, folder_files=False)
    production.update("doc", row["id"], lambda d: d.update(still_keys={}, stills={}))
    asked = []

    def fake_draw(channel, outline, scenes, folder, frame="wide", only=None, notes=None, check=True):
        asked.append(list(only))
        out = {}
        for i in only:
            out[i] = folder / f"kf_{i:02d}.jpg"
            Image.new("RGB", (16, 9), (i * 50, 0, 0)).save(out[i])
        return out
    monkeypatch.setattr(stills, "draw", fake_draw)
    monkeypatch.setattr(stills, "repeats", lambda scenes, pool: {2: 0})
    run.run_stage(channel, row["id"], "stills")
    data = production.load("doc", row["id"])
    assert asked == [[0, 1]] and data["stills_reused"] == {"2": 0}
    folder = production.folder("doc", row["id"])
    assert Image.open(folder / data["stills"]["2"]).getpixel((0, 0)) == (0, 0, 0)


def test_faults_are_looked_for_closely_and_cheaply(tmp_path, monkeypatch):
    seen = {}
    path = tmp_path / "kf.jpg"
    Image.new("RGB", (1536, 864)).save(path)

    def fake(system, user, schema, **kw):
        seen.update(kw)
        return {"shots": [{"index": 3, "ok": False, "problems": ["The geologist has three arms."]}]}
    monkeypatch.setattr("pipeline.llm.call_json", fake)
    found = stills.flaws([{"index": 3, "image": "the geologist"}], {3: path})
    assert found == {3: ["The geologist has three arms."]}
    assert seen["model"] and "haiku" not in seen["model"]
    assert "a face on something" in stills.FLAWS


def test_another_angles_title_keeps_the_film(world):  # noqa: F811
    channel, row = world
    _made(channel, row, [_scene("Gaius sweeps")])
    angles = [{"title": "First", "thumbnail": {"words": "A"}}, {"title": "Second", "thumbnail": {"words": "B"}}]

    def pitched(d):
        d["pitch"] = {"angles": angles, "chosen": 0}
        production.mark(d, "pitch", "approved")
    production.update("doc", row["id"], pitched)
    data = production.retitle("doc", row["id"], 1)
    assert production.packaging(data)["title"] == "Second"
    assert production.chosen_angle(data)["title"] == "First"              # the film's promise is kept
    assert production.state(data, "stills") == "ready"                   # nothing to make again


def test_a_picture_the_look_calls_fine_isnt_redrawn(tmp_path, monkeypatch):
    path = tmp_path / "kf.jpg"
    Image.new("RGB", (64, 36)).save(path)
    monkeypatch.setattr("pipeline.llm.call_json", lambda *a, **k: {"shots": [{"index": 0, "ok": False, "problems": [
        "The drill bit has bolt-like studs but no actual facial features, so it's fine; no clear fault."]}]})
    assert stills.flaws([{"index": 0, "image": "a drill"}], {0: path}) == {}
