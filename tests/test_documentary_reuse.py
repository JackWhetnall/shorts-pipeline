"""
Pictures kept, redrawn and given depth (decision 088).

The owner: "some pictures seemed to fail generation and there is no way
to fix them individually ... i assume that there is a way to just
generate what is needed after a script change ... this smart-regeneration
should be done automatically". A Redraw with no note handed back the
same picture (the drawer reuses a file that exists), and a storyboard
drawn again threw every picture away.

- a storyboard drawn again keeps each picture whose scene asks for the
  same thing (or only rewords it), in the same look, and draws the rest;
- a redraw, or "draw the missing", draws exactly those, afresh;
- pictures that fail are tried once more before anyone has to ask;
- with the depth model, a shot's move has parallax.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from core import curriculum, production
from core.channels import ChannelConfig
from pipeline.documentary import cast as library
from pipeline.documentary import depth, run, stills


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    monkeypatch.setattr(production, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(library, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(library, "merge", lambda *a, **k: None)
    monkeypatch.setattr(stills, "look_for", lambda channel, frame="wide": {"description": channel.look_name})
    curriculum.start("doc", "Days", [{"title": "Cities", "summary": "", "level": "foundation", "target_subtopics": 5}])
    curriculum.add_subtopics("doc", "u01", [{"title": "A Day in Rome"}])
    channel = ChannelConfig(key="doc", format="documentary", voice="v")
    channel.look_name = "film still"
    return channel, curriculum.subtopics("doc")[0]


OUTLINE = {"chapters": [{"title": "A"}], "cast": [{"name": "Gaius", "kind": "character", "description": "a tall man"}]}


def _scene(direction, cast=("Gaius",), framing="wide", medium="picture"):
    return {"chapter": 1, "direction": direction, "cast": list(cast), "framing": framing, "camera": "push_in",
            "caption": "", "narration": "x", "medium": medium}


def _made(channel, row, scenes, folder_files=True):
    """A storyboard as if drawn for `scenes`."""
    folder = production.folder("doc", row["id"])
    (folder / "stills").mkdir(parents=True, exist_ok=True)
    names, keys = {}, {}
    for i, s in enumerate(scenes):
        path = folder / "stills" / f"kf_{i:02d}.jpg"
        if folder_files:
            Image.new("RGB", (16, 9), (i * 20, 50, 50)).save(path)
        names[str(i)] = f"stills/kf_{i:02d}.jpg"
        keys[str(i)] = stills.description(channel, OUTLINE, s)

    def change(d):
        d["outline"], d["script"] = OUTLINE, {"scenes": scenes, "description": ""}
        d["stills"], d["still_keys"], d["shown"] = names, keys, {k: "drawn" for k in names}
        for stage in ("pitch", "outline", "script"):
            production.mark(d, stage, "approved")
        production.mark(d, "stills", "ready")
    production.update("doc", row["id"], change, row["title"])


def test_a_new_script_keeps_the_pictures_whose_scenes_didnt_change(world):
    channel, row = world
    old = [_scene("Gaius sweeps the forum at dawn"), _scene("A cart in the street", cast=()),
           _scene("Gaius eats bread at noon")]
    _made(channel, row, old)
    new = [_scene("Gaius sweeps the forum at dawn."),            # reworded: kept
           _scene("A cart in the street", cast=(), framing="close-up"),   # reframed: drawn
           _scene("Gaius argues with a soldier at the gate"),    # new: drawn
           _scene("Gaius eats bread at noon")]                    # moved: kept
    keep = stills.reusable(channel, production.load("doc", row["id"]), new)
    assert keep == {0: "stills/kf_00.jpg", 3: "stills/kf_02.jpg"}
    channel.look_name = "watercolour"                             # a new look keeps nothing
    assert stills.reusable(channel, production.load("doc", row["id"]), new) == {}


def test_drawing_again_draws_only_what_changed_and_keeps_the_rest(world, monkeypatch):
    channel, row = world
    _made(channel, row, [_scene("Gaius sweeps the forum at dawn"), _scene("Gaius eats bread at noon")])
    asked = []

    def fake_draw(channel, outline, scenes, folder, frame="wide", only=None, notes=None, check=True):
        asked.append(list(only))
        out = {}
        for i in only:
            path = folder / f"kf_{i:02d}.jpg"
            Image.new("RGB", (16, 9), (255, 0, 0)).save(path)
            out[i] = path
        return out
    monkeypatch.setattr(stills, "draw", fake_draw)
    new = [_scene("Gaius eats bread at noon"), _scene("Gaius runs for the gate")]
    production.update("doc", row["id"], lambda d: d["script"].update(scenes=new))
    run.run_stage(channel, row["id"], "stills")
    data = production.load("doc", row["id"])
    assert asked == [[1]] and data["stills_kept"] == 1
    kept = Image.open(production.folder("doc", row["id"]) / data["stills"]["0"]).getpixel((0, 0))
    assert kept == (20, 50, 50)                                   # the old noon picture, now scene 0's
    assert set(data["still_keys"]) == {"0", "1"}
    assert not (production.folder("doc", row["id"]) / "stills_previous").exists()


def test_a_redraw_draws_afresh_even_without_a_note(world, monkeypatch):
    channel, row = world
    _made(channel, row, [_scene("Gaius sweeps"), _scene("Gaius eats")])
    seen = []

    def fake_draw(channel, outline, scenes, folder, frame="wide", only=None, notes=None, check=True):
        seen.append([(folder / f"kf_{i:02d}.jpg").exists() for i in only])
        path = folder / "kf_01.jpg"
        Image.new("RGB", (16, 9)).save(path)
        return {1: path}
    monkeypatch.setattr(stills, "draw", fake_draw)
    run.run_stage(channel, row["id"], "stills", only=[1])
    assert seen == [[False]]                       # the old picture was out of the way, so a new one is drawn


def test_pictures_that_fail_are_tried_once_more(world, monkeypatch):
    channel, row = world
    _made(channel, row, [_scene("Gaius sweeps")], folder_files=False)
    calls = []

    def flaky(channel, outline, scenes, folder, frame="wide", only=None, notes=None, check=True):
        calls.append(list(only))
        if len(calls) == 1:
            return {}
        path = folder / "kf_00.jpg"
        Image.new("RGB", (16, 9)).save(path)
        return {0: path}
    monkeypatch.setattr(stills, "draw", flaky)
    production.update("doc", row["id"], lambda d: d.update(still_keys={}, stills={}))
    run.run_stage(channel, row["id"], "stills")
    assert calls == [[0], [0]] and production.load("doc", row["id"])["stills"]["0"].endswith("kf_00.jpg")


def test_the_page_offers_to_draw_just_the_missing_ones(world, monkeypatch):
    channel, row = world
    from web import create_app
    _made(channel, row, [_scene("Gaius sweeps"), _scene("Gaius eats")])
    production.update("doc", row["id"], lambda d: (d["stills"].pop("1"), production.mark(d, "stills", "ready")))
    monkeypatch.setattr("web.blueprints.productions._channel", lambda key: channel)
    monkeypatch.setattr("web.blueprints.productions.curriculum.find", lambda key, sid: row)
    channel.animation.style = {"approach": "acted"}
    started = []
    monkeypatch.setattr("core.jobs.start_job", lambda key, seed, ahead=True, behind=False: started.append(seed) or "j")
    client = create_app().test_client()
    client.get("/m/sign-in")
    with client.session_transaction() as s:
        token = s["_csrf_token"]
    client.post(f"/channels/doc/productions/{row['id']}/start/stills", data={"missing": "1"},
                headers={"X-CSRF-Token": token})
    assert started and started[0]["only"] == [1]


# --- depth --------------------------------------------------------------------------------

def test_near_things_move_more_than_far_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(depth, "FRAME", (64, 36))
    still = tmp_path / "s.jpg"
    rng = np.random.default_rng(0)
    Image.fromarray(rng.integers(0, 255, (36, 64, 3), dtype=np.uint8)).save(still)
    near = np.zeros((36, 64), dtype=np.float32)
    near[:, 32:] = 1.0                                                     # the right half is near
    first, *_, last = list(depth.frames(still, near, 0.5, "pan_right"))
    a, b = np.asarray(first, dtype=float), np.asarray(last, dtype=float)
    assert first.shape == (36, 64, 3)
    assert np.abs(b[:, 40:] - a[:, 40:]).mean() > np.abs(b[:, :24] - a[:, :24]).mean()


def test_without_the_model_shots_move_flat(monkeypatch, tmp_path):
    monkeypatch.setattr(depth, "MODEL", tmp_path / "missing.onnx")
    assert depth.available() is False
