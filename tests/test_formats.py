"""
Animation formats (decision 052): the registry, the compositor's layouts
and timing, the beats storyboard made safe, the kit, the composited
pipeline, the paper theatre's captions and the director's side of it.

Models and services are faked; the one real render is marked slow.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.channels import ChannelConfig
from pipeline.animation import beats, compose, formats, kit, look as looks, stage, storyboard
from pipeline.animation.compositor import layouts, script
from pipeline.plan import Segment, WordTiming


def words_for(text: str, start: float = 0.0, step: float = 0.4) -> list:
    return [WordTiming(w, round(start + i * step, 2), round(start + i * step + 0.3, 2))
            for i, w in enumerate(text.split())]


# --- the registry ---------------------------------------------------------------

class TestRegistry:
    def test_every_format_is_complete_and_its_looks_exist(self):
        for key, fmt in formats.formats().items():
            assert {"key", "label", "engine", "description", "suits", "looks", "cost"} <= set(fmt)
            assert fmt["engine"] in ("generated", "compositor"), key
            assert all(look in looks.presets() for look in fmt["looks"]), key
            if formats.composited(fmt):
                assert {"labels", "kit_view", "guide", "continuity", "entrance"} <= set(fmt), key
                assert fmt["continuity"] in ("move", "persist")

    def test_the_four_formats(self):
        assert list(formats.formats()) == ["tabletop", "canvas", "story", "theatre"]
        assert formats.resolve("nope")["key"] == formats.DEFAULT_FORMAT == "story"

    def test_a_look_gives_the_format_its_inks_and_rate(self):
        felt = looks.resolve(SimpleNamespace(look="felt_craft"))
        style = formats.style_for(formats.resolve("tabletop"), felt)
        assert style["step"] == pytest.approx(1 / 12) and style["jitter"] > 0
        assert style["labels"]["color"] == "#3D3A4B"          # the palette's darkest
        flat = looks.resolve(SimpleNamespace(look="flat_minimal"))
        style = formats.style_for(formats.resolve("canvas"), flat)
        assert style["step"] == 0 and style["jitter"] == 0
        assert style["surface"] == {"color": "#F2EFE8"}

    def test_every_format_has_its_three_examples(self):
        from web.blueprints.animation import FORMAT_EXAMPLES
        missing = [(k, n) for k in formats.formats() for n in (1, 2, 3)
                   if not (FORMAT_EXAMPLES / f"{k}_{n}.jpg").exists()]
        assert not missing


# --- layouts -------------------------------------------------------------------------

def item(key, label="a label", count=1, highlight=False, **more):
    return {"key": key, "label": label, "count": count, "highlight": highlight, **more}


CASES = {
    "hero": [item("brain")], "pair": [item("a"), item("b")], "row": [item("a"), item("b"), item("c")],
    "grid": [item(k) for k in "abcdef"], "steps": [item(k) for k in "abcd"],
    "cycle": [item(k) for k in "abcde"], "group": [item("coin", count=30, highlight=True)],
    "travel": [item("yawn"), item("face"), item("dog")], "scale": [item(k) for k in "abcd"],
    "statement": [item("a")], "presenter": [item("a")],
}


class TestLayouts:
    @pytest.mark.parametrize("layout", sorted(CASES))
    @pytest.mark.parametrize("aspect", [0.45, 1.0, 2.2])
    def test_everything_stays_in_the_frame_and_above_the_captions(self, layout, aspect):
        its = CASES[layout]
        placed, marks = layouts.arrange(layout, its, {i["key"]: aspect for i in its},
                                        relation="arrow", title="A title here")
        assert placed or layout == "statement"
        for p in placed:
            assert p["x"] - p["w"] / 2 >= -1 and p["x"] + p["w"] / 2 <= 1081, (layout, p)
            assert p["y"] - p["h"] / 2 >= 280 and p["y"] + p["h"] / 2 <= 1300, (layout, p)
        for m in marks:
            if m["kind"] == "label":
                assert 40 <= m["x"] <= 1040 and m["y"] <= 1340, (layout, m)

    def test_a_joined_pair_leaves_room_for_what_joins_it(self):
        placed, marks = layouts.arrange("pair", [item("a"), item("b")], {"a": 1.0, "b": 1.0},
                                        relation="arrow")
        a, b = placed
        assert (b["x"] - b["w"] / 2) - (a["x"] + a["w"] / 2) >= 180
        assert [m["kind"] for m in marks if m["role"] == "relation"] == ["arrow"]

    def test_a_group_circles_the_highlighted_one(self):
        placed, marks = layouts.arrange("group", [item("coin", "1 in 10", count=10,
                                                       highlight=True)], {"coin": 1.0})
        assert len(placed) == 10 and [m["kind"] for m in marks].count("ring") == 1

    def test_a_traveller_goes_from_its_start_to_its_end(self):
        placed, _ = layouts.arrange("travel", [item("yawn"), item("you", place="end")],
                                    {"yawn": 1, "you": 1})
        mover = placed[0]
        assert mover["from"][1] > mover["y"]        # sets off low, arrives high (towards the end)
        end = next(p for p in placed if p["key"] == "you")
        assert end["y"] < 700                         # the end sits at the top right

    def test_areas_offset_everything(self):
        placed, marks = layouts.arrange("hero", [item("a")], {"a": 1.0}, origin=(2000, 3000))
        assert placed[0]["x"] == 2540 and all(m["x"] > 2000 for m in marks)


# --- the script: timing, continuity, exits -------------------------------------------

TABLETOP = formats.resolve("tabletop")
CANVAS = formats.resolve("canvas")
STYLE = {"step": 1 / 12, "jitter": 1.0, "surface": {"color": "#fff"},
         "shadow": {"mode": "none"}, "labels": {"font": "Ink Free"}}


def beat(start, end, layout, its, **more):
    return {"start": start, "end": end, "layout": layout, "items": its, "title": "",
            "relation": "", "avatar": "", **more}


WORDS = words_for(" ".join(f"w{i}" for i in range(60)), step=0.5)       # 30 seconds


def keys_of(stage_data, sprite_id):
    return next(s for s in stage_data["sprites"] if s["id"] == sprite_id)["keys"]


class TestScript:
    def test_objects_arrive_on_their_words(self):
        st = script.build([beat(0, 10, "pair", [item("a", on_word=2), item("b", on_word=8)])],
                          WORDS, 0.0, 10, {"a": 1, "b": 1}, TABLETOP, STYLE)
        a, b = keys_of(st, "a_0_0"), keys_of(st, "b_0_0")
        assert a[1]["t"] == pytest.approx(0.88)          # word 2 at 1.0s, a moment ahead
        assert b[1]["t"] == pytest.approx(3.88)

    def test_the_first_object_never_leaves_the_table_empty(self):
        st = script.build([beat(0, 8, "hero", [item("a", on_word=15)])], WORDS, 0.0, 8,
                          {"a": 1}, TABLETOP, STYLE)
        assert keys_of(st, "a_0_0")[1]["t"] <= 2.0 + 1e-6      # capped at a quarter of the beat

    def test_a_carried_object_moves_instead_of_arriving_again(self):
        st = script.build([beat(0, 5, "hero", [item("a")]), beat(5, 10, "pair", [item("a"), item("b")])],
                          WORDS, 0.0, 10, {"a": 1, "b": 1}, TABLETOP, STYLE)
        a = keys_of(st, "a_0_0")
        assert [k.get("lift") for k in a if k.get("lift") == 1] == [1, 1]   # one arrival only
        assert any(k.get("ease") == "inout" and k.get("hop") for k in a)     # it walks over

    def test_a_leaving_object_is_fully_there_until_it_goes(self):
        """Regression: an exit without a visible key spread its fade over
        the object's whole time on the table; short-lived objects barely
        showed."""
        st = script.build([beat(0, 5, "hero", [item("a")]), beat(5, 10, "hero", [item("b")])],
                          WORDS, 0.0, 10, {"a": 1, "b": 1}, TABLETOP, STYLE)
        a = keys_of(st, "a_0_0")
        exit_start = next(k for k in a if k["t"] == pytest.approx(4.95))
        assert exit_start["alpha"] == 1 and a[-1]["alpha"] == 0

    def test_an_object_that_comes_back_is_the_same_object_again(self):
        """Regression: re-entering overwrote the sprite, losing its first
        appearance."""
        st = script.build([beat(0, 4, "hero", [item("a")]), beat(4, 8, "hero", [item("b")]),
                           beat(8, 12, "hero", [item("a")])],
                          WORDS, 0.0, 12, {"a": 1, "b": 1}, TABLETOP, STYLE)
        ids = [s["id"] for s in st["sprites"]]
        assert ids.count("a_0_0") == 1
        a = keys_of(st, "a_0_0")
        assert a[0]["t"] == 0 and max(k["t"] for k in a) > 8           # both appearances

    def test_a_canvas_keeps_each_beat_in_its_own_area_and_travels_there(self):
        st = script.build([beat(0, 5, "hero", [item("a")]), beat(5, 10, "hero", [item("a")])],
                          WORDS, 0.0, 10, {"a": 1}, CANVAS, dict(STYLE, step=0, jitter=0))
        assert {s["id"] for s in st["sprites"]} == {"a_0_0", "a_0_1"}
        xs = [k["x"] for k in st["camera"]]
        assert min(xs) == 540 and max(xs) == 540 + 1080 + script.AREA_GAP
        assert st["world"]["w"] == 2 * 1080 + script.AREA_GAP

    def test_the_narrator_talks_only_on_presenter_beats(self):
        style = dict(STYLE, avatar={"poses": {"talk": "n_talk"}, "x": 300, "y": 1270, "h": 900})
        st = script.build([beat(0, 5, "presenter", [], avatar="talk"), beat(5, 10, "hero", [item("a")])],
                          WORDS, 0.0, 10, {"a": 1}, CANVAS, style)
        assert [k["pose"] for k in st["avatar"]["keys"]] == ["talk", None]
        assert st["avatar"]["talk"] and all(b <= 5 for _, b in st["avatar"]["talk"])

    def test_marks_follow_their_objects(self):
        st = script.build([beat(0, 10, "pair", [item("a", "left", on_word=0), item("b", "right", on_word=8)],
                                relation="arrow", title="Hello")],
                          WORDS, 0.0, 10, {"a": 1, "b": 1}, TABLETOP, STYLE)
        by = {m.get("text") or m["kind"]: m for m in st["marks"]}
        assert by["Hello"]["t0"] < by["left"]["t0"] < by["right"]["t0"]
        assert by["arrow"]["t0"] >= by["right"]["t0"] - 0.2


# --- the beats storyboard made safe -------------------------------------------------

def windows_and_words():
    words = words_for("one two three four five six seven eight nine ten eleven twelve", step=1.0)
    segments = [Segment(text="x", start=0.0, end=6.0), Segment(text="y", start=6.0, end=12.3)]
    return segments, words, storyboard.spans(segments, [(0, 1)], words)


def raw_beat(word, layout="hero", its=None, **more):
    return {"start_word": word, "layout": layout, "title": "", "relation": "", "avatar": "",
            "items": its if its is not None else [{"key": "Brain", "label": "the brain",
                                                   "on_word": word, "count": 1, "highlight": False}],
            "why": "", **more}


class TestSettle:
    def settle(self, raw_beats, fmt=TABLETOP, kit=None):
        segments, words, windows = windows_and_words()
        raw = {"concept": "c", "kit": kit or [{"key": "Brain", "name": "Brain", "description": "pink"}],
               "beats": raw_beats}
        return beats.settle(raw, windows, words, fmt)

    def test_the_first_beat_opens_the_window_and_times_come_from_words(self):
        settled, kit_used, _ = self.settle([raw_beat(3), raw_beat(7)])
        assert settled[0]["start"] == 0.0 and settled[1]["start"] == pytest.approx(6.9)
        assert settled[0]["end"] == settled[1]["start"] and settled[-1]["end"] == 12.3
        assert kit_used == {"brain": {"name": "Brain", "description": "pink"}}

    def test_a_layout_that_cannot_take_its_objects_is_changed(self):
        its = [{"key": k, "label": k, "on_word": 0, "count": 1, "highlight": False} for k in "abcd"]
        settled, _, _ = self.settle([raw_beat(0, "hero", its)])
        assert settled[0]["layout"] == "grid"

    def test_no_narrator_means_no_presenter(self):
        settled, _, _ = self.settle([raw_beat(0, "presenter", [], avatar="talk")])
        assert settled[0]["layout"] == "statement" and settled[0]["avatar"] == ""
        settled, _, _ = self.settle([raw_beat(0, "presenter", [], avatar="talk")], fmt=CANVAS)
        assert settled[0]["layout"] == "presenter" and settled[0]["avatar"] == "talk"

    def test_a_beat_too_short_to_read_gives_way_to_the_next(self):
        settled, _, _ = self.settle([raw_beat(0), raw_beat(1), raw_beat(7)])
        assert [b["start_word"] for b in settled] == [0, 7]
        assert settled[0]["items"][0]["on_word"] == 1          # the next beat's, opening earlier

    def test_a_word_outside_its_beat_is_dropped(self):
        its = [{"key": "brain", "label": "x", "on_word": 11, "count": 1, "highlight": False}]
        settled, _, _ = self.settle([raw_beat(0, its=its), raw_beat(7)])
        assert settled[0]["items"][0]["on_word"] == -1

    def test_a_traveller_keeps_its_start_and_end_when_a_repeat_is_dropped(self):
        its = [{"key": k, "label": k, "on_word": 0, "count": 1, "highlight": False}
               for k in ("yawn", "yawn", "you")]
        settled, _, _ = self.settle([raw_beat(0, "travel", its)])
        assert [(i["key"], i.get("place")) for i in settled[0]["items"]] == [("yawn", None),
                                                                            ("you", "end")]

    def test_labels_and_counts_are_bounded(self):
        its = [{"key": "coin", "label": "a very long label that goes on and on", "on_word": 0,
                "count": 500, "highlight": True}]
        settled, _, _ = self.settle([raw_beat(0, "group", its)])
        it = settled[0]["items"][0]
        assert len(it["label"]) <= 28 and it["count"] == layouts.MAX_COUNT


# --- the kit -----------------------------------------------------------------------

def png(path: Path, size=(400, 300)):
    from PIL import Image
    Image.new("RGBA", (1024, 1024), (0, 0, 0, 0)).save(path)
    im = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    for x in range(300, 300 + size[0]):
        for y in range(400, 400 + size[1], 4):
            im.putpixel((x, y), (200, 50, 50, 255))
    im.save(path)
    return path


class TestKit:
    @pytest.fixture
    def channel(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.paths.CHANNELS_DIR", tmp_path)
        drawn = []

        def fake_draw(prompt, out, model, **kw):
            drawn.append((Path(out).name, kw.get("transparent"), kw.get("references")))
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            if str(out).endswith(".jpg"):
                from PIL import Image
                Image.new("RGB", (1008, 1792), (240, 235, 225)).save(out)
            else:
                png(Path(out))
            return Path(out)
        monkeypatch.setattr(kit.images, "draw", fake_draw)
        channel = ChannelConfig(key="demo")
        channel.animation.look = "felt_craft"
        return SimpleNamespace(channel=channel, drawn=drawn,
                               look=looks.resolve(channel.animation))

    def test_objects_are_drawn_once_and_reused(self, channel):
        wanted = {"brain": {"name": "Brain", "description": "pink"}}
        first = kit.objects(channel.channel, channel.look, TABLETOP, wanted)
        again = kit.objects(channel.channel, channel.look, TABLETOP, wanted)
        assert first == again and len(channel.drawn) == 1 and channel.drawn[0][1] is True
        assert kit.index("demo", channel.look, "top")["brain"]["name"] == "Brain"
        assert kit.aspects(first)["brain"] > 1          # trimmed to the object

    def test_a_canvas_draws_its_objects_face_on_separately(self, channel):
        wanted = {"brain": {"name": "Brain", "description": "pink"}}
        kit.objects(channel.channel, channel.look, TABLETOP, wanted)
        kit.objects(channel.channel, channel.look, CANVAS, wanted)
        assert len(channel.drawn) == 2

    def test_the_surface_is_drawn_once_at_frame_size(self, channel):
        from PIL import Image
        first = kit.surface(channel.channel, channel.look, TABLETOP)
        assert kit.surface(channel.channel, channel.look, TABLETOP) == first
        assert Image.open(first).size == (1080, 1920) and len(channel.drawn) == 1

    def test_the_narrator_has_every_pose_open_and_closed_cropped_together(self, channel):
        from PIL import Image
        poses = kit.narrator(channel.channel, channel.look, CANVAS)
        assert set(poses) == {p + s for p in kit.POSES for s in ("", "_open")}
        sizes = {Image.open(p).size for p in poses.values()}
        assert len(sizes) == 1                                    # one shared box
        edits = [d for d in channel.drawn if d[2]]
        assert len(edits) == len(poses) - 1                       # all but the first from a reference


# --- the composited pipeline -----------------------------------------------------

class TestCompose:
    def test_a_video_is_beats_kit_stage_render(self, monkeypatch, tmp_path):
        from pipeline.animation.compositor import render
        segments = [Segment(text="one two three four", start=0.0, end=4.0)]
        words = words_for("one two three four", step=1.0)
        channel = ChannelConfig(key="demo")
        channel.animation.format = "tabletop"
        channel.animation.look = "felt_craft"
        plan = SimpleNamespace(channel=channel, seed=SimpleNamespace(title="demo"),
                               script=SimpleNamespace(segments=segments),
                               voiceover=SimpleNamespace(word_timings=words))
        monkeypatch.setattr(beats, "write", lambda *a, **k: {
            "concept": "c", "kit": [{"key": "brain", "name": "Brain", "description": "pink"},
                                    {"key": "ghost", "name": "Ghost", "description": ""}],
            "beats": [raw_beat(0, "pair", [
                {"key": "brain", "label": "brain", "on_word": 0, "count": 1, "highlight": False},
                {"key": "ghost", "label": "ghost", "on_word": 2, "count": 1, "highlight": False}])]})
        monkeypatch.setattr(kit, "index", lambda *a: {})
        pic = png(tmp_path / "brain.png")
        monkeypatch.setattr(kit, "objects", lambda ch, lk, fmt, wanted: {"brain": pic})
        monkeypatch.setattr(kit, "surface", lambda *a: tmp_path / "surface.jpg")
        rendered = []
        monkeypatch.setattr(render, "render", lambda st, assets, out: rendered.append((st, assets))
                            or Path(out))
        monkeypatch.setattr(compose.finish, "grade", lambda src, out, look: Path(out))
        result = stage.make(plan, [0], {}, tmp_path / "work", tail=0.5)
        assert [c["kind"] for c in result.clips] == ["animation"]
        st, assets = rendered[0]
        assert st["surface"] == {"image": "surface"} and set(assets) == {"brain", "surface"}
        assert [s["src"] for s in st["sprites"]] == ["brain"]          # the ghost was left out
        assert any("couldn't be drawn" in n for n in result.notes)
        assert st["duration"] == pytest.approx(4.5)
        assert json.loads((tmp_path / "work" / "beats.json").read_text())["format"] == "tabletop"


# --- the paper theatre -----------------------------------------------------------

class TestTheatre:
    def test_its_shots_carry_captions(self):
        shot = storyboard.schema(captions=True)["properties"]["shots"]["items"]
        assert "caption" in shot["required"]
        assert "caption" not in storyboard.schema()["properties"]["shots"]["items"]["properties"]

    def test_captions_are_laid_over_the_shots_that_have_them(self, monkeypatch, tmp_path):
        from pipeline.animation.compositor import render
        made, laid = [], []
        monkeypatch.setattr(render, "caption_png", lambda text, labels, out: made.append(text) or out)
        monkeypatch.setattr(stage.finish, "overlay_captions",
                            lambda clip, caps, out: laid.append(caps) or out)
        shots = [{"index": 0, "start": 10.0, "end": 14.0, "caption": "Moses"},
                 {"index": 1, "start": 14.0, "end": 16.0, "caption": ""}]
        out = stage._captions(tmp_path / "a.mp4", shots, {"start": 10.0},
                              formats.resolve("theatre"),
                              looks.resolve(SimpleNamespace(look="paper_puppet")), tmp_path)
        assert made == ["Moses"] and out.name == "a_c.mp4"
        (_, start, end), = laid[0]
        assert start == pytest.approx(0.35) and end == pytest.approx(3.75)


# --- the director ----------------------------------------------------------------

class TestDirector:
    def test_a_format_that_draws_its_own_diagrams_is_offered_no_templates(self, monkeypatch):
        from pipeline import director
        seen = {}

        def fake_call(system, user, schema, **kw):
            seen["enum"] = schema["properties"]["segments"]["items"]["properties"]["medium"]["enum"]
            return {"segments": []}
        monkeypatch.setattr(director, "call_json", fake_call)
        director.direct([Segment(text="t", start=0, end=3)], "s", 100, animation=True,
                        own_diagrams=True)
        assert "template" not in seen["enum"] and "diagram" not in seen["enum"]
        director.direct([Segment(text="t", start=0, end=3)], "s", 100, animation=True)
        assert "template" in seen["enum"]


# --- the settings page -----------------------------------------------------------

from tests.test_web import client, config_path, csrf  # noqa: E402,F401  (fixtures)


class TestSettingsPage:
    def test_the_formats_are_offered_with_examples(self, client):
        body = client.get("/channels/test_channel/settings").get_data(as_text=True)
        for fmt in formats.formats().values():
            assert f'data-anim-format-card="{fmt["key"]}"' in body
        assert "/animation/formats/tabletop/1.jpg" in body
        assert client.get("/animation/formats/tabletop/1.jpg").status_code == 200
        assert client.get("/animation/formats/tabletop/9.jpg").status_code == 404

    def test_saving_the_format(self, client, config_path):
        from core.channels import load_channels
        client.post("/channels/test_channel/settings", data={
            "csrf_token": csrf(client), "content_mode": "topic", "voice": "21m00Tcm4TlvDq8ikWAM",
            "style_prompt": "Write something.", "topics": "coffee", "anim_present": "1",
            "anim_format": "canvas", "anim_look": "flat_minimal"})
        a = load_channels(config_path)["test_channel"].animation
        assert (a.format, a.look) == ("canvas", "flat_minimal")


# --- the real thing ----------------------------------------------------------------

@pytest.mark.slow
def test_a_stage_renders_in_chrome(tmp_path):
    from PIL import Image
    from pipeline.animation.compositor import render
    pic = png(tmp_path / "a.png")
    style = formats.style_for(TABLETOP, looks.resolve(SimpleNamespace(look="felt_craft")))
    st = script.build([beat(0, 2, "hero", [item("a", "a label")], title="Hello")],
                      WORDS, 0.0, 2.0, {"a": 4 / 3}, TABLETOP, style)
    frame = render.still(st, {"a": pic}, 1.8, tmp_path / "f.jpg")
    assert Image.open(tmp_path / "f.jpg").size == (1080, 1920) and frame


def test_a_composited_format_animates_without_a_fal_key(monkeypatch, tmp_path):
    """Tabletop and canvas have no video model, so a missing FAL_KEY must
    not turn them into still illustrations (it briefly did)."""
    from pipeline import director, visuals
    from pipeline.animation import stage as animation_stage
    from tests.test_animation import visuals_plan
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(visuals.stage, "_restore", lambda: None)
    monkeypatch.setattr(visuals.stage, "_save", lambda plan: None)
    seen = {}

    def fake_direct(segments, *a, **k):
        seen.update(k)
        return [{"index": i, "medium": "animation", "template": "", "brief": "b", "need": 9,
                 "reason": "r"} for i in range(len(segments))]
    monkeypatch.setattr(director, "direct", fake_direct)
    result = animation_stage.Result()
    result.clips = [{"first": 0, "last": 1, "clip": str(tmp_path / "a.mp4"), "kind": "animation"}]
    monkeypatch.setattr(animation_stage, "make", lambda *a, **k: result)
    plan = visuals_plan(tmp_path)
    plan.channel.animation.format = "tabletop"
    plan = visuals.run(plan)
    assert seen["animation"] is True and seen["own_diagrams"] is True
    assert plan.scene_clips == result.clips
    assert not any("FAL_KEY" in n for n in plan.scene_notes)
