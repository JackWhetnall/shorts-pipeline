"""
Animated scenes in the pipeline: a channel's art direction, the scene
writer's checks, how scenes become shots, and the stage's fallbacks.

The model and the browser are faked here; tests/test_scenes.py drives
the real engine (slow).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.channels import ChannelConfig, channel_from_dict, channel_to_sparse_dict
from core.errors import ConfigError, ExternalServiceError
from pipeline.plan import Segment, WordTiming
from pipeline.scenes import art, stage, writer

WORDS = [(w, round(i * 0.4, 2)) for i, w in enumerate(
    "Take any right angled triangle and build a square on each side".split())]


# --- art direction -----------------------------------------------------------

class TestArt:
    def test_a_channel_stores_only_what_differs_from_its_preset(self):
        chalk = art.editable({"preset": "chalkboard"})
        form = dict(chalk, accent1="#FF0000")
        assert art.sparse(form) == {"preset": "chalkboard", "accent1": "#FF0000"}

    def test_overrides_are_laid_over_the_preset(self):
        style = art.resolve({"preset": "neon", "accent2": "#123456", "font_display": "Georgia"})
        assert style["colors"]["accent2"] == "#123456"
        assert style["font_display"] == "Georgia"
        assert style["glow"] == art.presets()["neon"]["glow"]      # untouched keys kept

    def test_bad_values_fall_back_to_the_preset(self):
        cleaned = art.clean({"preset": "nope", "ink": "red", "font_text": "Papyrus Deluxe",
                             "stroke_width": "900", "pattern": "plaid"})
        assert cleaned == {"preset": art.DEFAULT_PRESET, "stroke_width": 20}

    def test_every_preset_has_every_editable_value(self):
        for key in art.presets():
            values = art.editable({"preset": key})
            assert all(values[k] for k in art.COLOR_KEYS), key
            assert values["font_display"] in art.FONTS and values["font_text"] in art.FONTS


class TestChannelSetting:
    def test_scenes_round_trip_through_the_config_file(self):
        channel = ChannelConfig(key="maths")
        channel.scenes.share = 100
        channel.scenes.art = {"preset": "chalkboard"}
        raw = channel_to_sparse_dict(channel)
        assert raw["scenes"] == {"share": 100, "art": {"preset": "chalkboard"}}
        assert channel_from_dict("maths", raw).scenes.share == 100

    def test_a_channel_without_scenes_is_stock_only(self):
        assert ChannelConfig(key="x").scenes.share == 0
        assert "scenes" not in channel_to_sparse_dict(ChannelConfig(key="x"))

    def test_a_share_outside_0_to_100_is_refused(self):
        channel = ChannelConfig(key="x", voice="a" * 20, style_prompt="p", topics=["t"])
        channel.scenes.share = 140
        with pytest.raises(ConfigError, match="0 to 100"):
            channel.validate()


# --- the writer's checks -------------------------------------------------------

def scene(**over):
    base = {
        "props": [],
        "elements": [
            {"id": "tri", "type": "poly", "vertices": [[300, 800], [800, 800], [300, 400]]},
            {"id": "sq", "type": "shape", "kind": "square", "on": {"of": "tri", "edge": 0}},
            {"id": "a", "type": "label", "text": "a", "anchor": {"of": "tri", "edge": 2, "offset": 60},
             "color": "hot pink"},
        ],
        "actions": [
            {"target": "tri", "do": "draw", "word": 4, "dur": 1.2},
            {"target": "sq", "do": "draw", "word": 7, "delay": 0.2, "dur": 30},
            {"target": "a", "do": "appear", "word": 11, "dur": 0.5},
        ],
    }
    base.update(over)
    return base


class TestValidate:
    def test_word_anchors_become_seconds_and_overruns_are_trimmed(self):
        out, problems = writer.validate(scene(), WORDS, duration=5.0)
        assert problems == []
        tri, sq, a = out["actions"]
        assert tri["at"] == pytest.approx(1.6)                  # word 4 at 0.4s each
        assert sq["at"] == pytest.approx(3.0)                   # word 7 + 0.2s delay
        assert sq["dur"] == pytest.approx(2.0)                  # trimmed to the scene's end
        assert "word" not in tri and "delay" not in sq

    def test_shape_shorthand_is_accepted_and_unknown_colours_become_tokens(self):
        out, _ = writer.validate(scene(), WORDS, duration=5.0)
        tri, _, label = out["elements"]
        assert (tri["type"], tri["kind"]) == ("shape", "poly")
        assert label["color"] == "ink"

    def test_structural_mistakes_are_problems(self):
        bad = scene(actions=[{"target": "ghost", "do": "appear", "word": 0, "dur": 1},
                             {"target": "tri", "do": "draw", "word": 99, "dur": 1}],
                    elements=scene()["elements"] + [
                        {"id": "pig", "type": "prop", "asset": "piggy", "x": 1, "y": 1},
                        {"id": "blob", "type": "sprite"}])
        _, problems = writer.validate(bad, WORDS, duration=5.0)
        text = " ".join(problems)
        assert "doesn't exist" in text and "word 99" in text
        assert "isn't declared in props" in text and "'sprite'" in text

    def test_an_element_that_never_enters_is_a_problem_unless_hidden(self):
        raw = scene(actions=[{"target": "tri", "do": "draw", "word": 0, "dur": 1}])
        _, problems = writer.validate(raw, WORDS, 5.0)
        assert [p.split("'")[1] for p in problems] == ["sq", "a"]
        raw["elements"][1]["hidden"] = True
        raw["elements"][2]["hidden"] = True
        assert writer.validate(raw, WORDS, 5.0)[1] == []

    def test_a_square_must_stand_on_a_shape_with_corners_before_it(self):
        elements = [{"id": "sq", "type": "shape", "kind": "square", "on": {"of": "tri", "edge": 0}},
                    {"id": "tri", "type": "poly", "vertices": [[0, 0], [1, 0], [0, 1]]}]
        _, problems = writer.validate(scene(elements=elements, actions=[]), WORDS, 5.0)
        assert any("with corners listed before it" in p for p in problems)

    def test_a_stacked_prop_becomes_a_template_and_move_takes_to_xy(self):
        raw = scene(props=[{"key": "coin", "name": "gold coin", "detail": ""}],
                    elements=[{"id": "coin", "type": "prop", "asset": "coin", "x": 1, "y": 1, "w": 90},
                              {"id": "pig", "type": "prop", "asset": "coin", "x": 1, "y": 1}],
                    actions=[{"target": "coin", "do": "stack", "into": "pig", "word": 0, "dur": 3,
                              "count": 40},
                             {"target": "pig", "do": "appear", "word": 0, "dur": 0.5},
                             {"target": "pig", "do": "move", "to_xy": [500, 600], "word": 1, "dur": 1}])
        out, problems = writer.validate(raw, WORDS, 5.0)
        assert problems == []
        assert out["elements"][0]["template"] is True
        assert out["actions"][0]["count"] == 9
        assert out["actions"][2]["to"] == [500, 600]
        assert out["props"] == {"coin": {"key": "coin", "name": "gold coin", "detail": ""}}


class TestLayoutProblems:
    def test_off_screen_caption_space_overlap_and_straddle_are_reported(self):
        frame = [
            {"id": "wide", "type": "label", "kind": "", "box": [-40, 200, 300, 260]},
            {"id": "low", "type": "counter", "kind": "", "box": [400, 1300, 600, 1400]},
            {"id": "one", "type": "label", "kind": "", "box": [100, 500, 300, 560]},
            {"id": "two", "type": "label", "kind": "", "box": [120, 510, 320, 570]},
            {"id": "sq", "type": "shape", "kind": "square", "box": [500, 600, 900, 1000]},
            {"id": "edge", "type": "label", "kind": "", "box": [450, 700, 550, 760]},
            {"id": "inside", "type": "label", "kind": "", "box": [650, 750, 750, 810]},
        ]
        problems = " ".join(writer.layout_problems([(1.0, frame), (2.0, frame)]))
        assert "'wide' goes off the edge" in problems
        assert "'low' reaches y 1400" in problems
        assert "'one' and 'two' overlap" in problems
        assert "'edge' sits across the edge of 'sq'" in problems
        assert "'inside'" not in problems
        assert problems.count("'wide' goes off") == 1            # reported once, not per frame


# --- scenes become shots -------------------------------------------------------

def test_scenes_replace_the_shots_of_the_segments_they_cover():
    from pipeline.assemble import plan_shots

    segments = [Segment(text=str(i), start=i * 6.0, end=(i + 1) * 6.0) for i in range(4)]
    shots = plan_shots(segments, [{"first": 1, "last": 2, "clip": "s.mp4"}], max_seconds=5)
    assert [(s.segment_index, s.scene) for s in shots] == [
        (0, False), (0, False), (1, True), (3, False), (3, False)]
    scene_shot = shots[2]
    assert (scene_shot.start, scene_shot.end, scene_shot.clip_path) == (6.0, 18.0, Path("s.mp4"))


# --- the stage -------------------------------------------------------------------

@pytest.fixture
def plan(tmp_path):
    channel = ChannelConfig(key="maths")
    channel.scenes.share = 100
    segments = [Segment(text="one two", start=0.0, end=2.0),
                Segment(text="three four", start=2.0, end=4.0)]
    timings = [WordTiming(w, i * 1.0, i * 1.0 + 0.5) for i, w in enumerate("one two three four".split())]
    return SimpleNamespace(channel=channel, script=SimpleNamespace(segments=segments),
                           voiceover=SimpleNamespace(word_timings=timings),
                           seed=SimpleNamespace(title="Pythagoras"), out_dir=tmp_path, stem="v")


@pytest.fixture(autouse=True)
def no_checkpoints(monkeypatch):
    monkeypatch.setattr(stage.job_context, "load_json_checkpoint", lambda name: None)
    monkeypatch.setattr(stage.job_context, "save_json_checkpoint", lambda name, data: None)


def test_a_stock_only_channel_never_calls_the_model(plan, monkeypatch):
    plan.channel.scenes.share = 0
    monkeypatch.setattr(writer, "plan", lambda *a: pytest.fail("planned scenes"))
    stage.run(plan)
    assert plan.scene_clips == [] and plan.scenes_fell_back == 0


def test_a_scene_that_cannot_be_made_falls_back_to_stock_and_says_so(plan, monkeypatch):
    monkeypatch.setattr(writer, "plan", lambda *a: [{"first": 0, "last": 0, "idea": "a"},
                                                    {"first": 1, "last": 1, "idea": "b"}])

    def make(idea, *args, **kwargs):
        if idea == "a":
            raise ExternalServiceError("Claude", "boom", user_message="The AI service failed.")
        return Path("b.mp4"), ["'x' and 'y' overlap (at 1.0s)."]

    monkeypatch.setattr(stage, "_make", make)
    stage.run(plan)
    assert plan.scene_clips == [{"first": 1, "last": 1, "clip": "b.mp4"}]
    assert plan.scenes_fell_back == 1
    assert any("replaced by stock footage" in n for n in plan.scene_notes)
    assert any("overlap" in n for n in plan.scene_notes)


def test_a_failed_plan_leaves_the_whole_video_to_stock(plan, monkeypatch):
    def fail(*a):
        raise ExternalServiceError("Claude", "down", user_message="The AI service failed.")
    monkeypatch.setattr(writer, "plan", fail)
    stage.run(plan)
    assert plan.scene_clips == [] and plan.scenes_fell_back == 1


def test_a_scene_is_repaired_once_with_its_problems(plan, monkeypatch, tmp_path):
    calls = []

    def write(idea, words, duration, style, library, previous=None, problems=None, **kw):
        calls.append(problems)
        return {"version": len(calls)}

    checks = iter([(scene(), ["'a' and 'b' overlap"], {}), (scene(), [], {})])
    monkeypatch.setattr(writer, "write", write)
    looks = []
    monkeypatch.setattr(stage, "_check", lambda *a, look=False: looks.append(look) or next(checks))
    monkeypatch.setattr(stage.render, "render", lambda sc, st, assets, out: out)
    clip, notes = stage._make("idea", WORDS, 4.0, art.resolve({}), tmp_path, {},
                              tmp_path / "scene_1", 0.5, [0])
    assert calls == [None, ["'a' and 'b' overlap"]]
    assert looks == [True, False]            # the picture check runs once, before the repair
    assert notes == [] and clip.suffix == ".mp4"
    assert (tmp_path / "scene_1.json").exists()


def test_a_scene_still_broken_after_repair_is_not_rendered(plan, monkeypatch, tmp_path):
    monkeypatch.setattr(writer, "write", lambda *a, **k: {})
    monkeypatch.setattr(stage, "_check", lambda *a, **k: (None, ["no elements"], {}))
    monkeypatch.setattr(stage.render, "render", lambda *a: pytest.fail("rendered a broken scene"))
    with pytest.raises(Exception, match="no elements"):
        stage._make("idea", WORDS, 4.0, art.resolve({}), tmp_path, {}, tmp_path / "s", 0.5, [0])


def test_new_props_are_capped_per_video(monkeypatch, tmp_path):
    raw = scene(props=[{"key": "p", "name": "wooden ladder", "detail": ""}],
                elements=[{"id": "l", "type": "prop", "asset": "p", "x": 540, "y": 600, "w": 300}],
                actions=[{"target": "l", "do": "appear", "word": 0, "dur": 0.5}])
    monkeypatch.setattr(stage.props, "get", lambda *a: pytest.fail("drew past the cap"))
    out, problems, _ = stage._check(raw, WORDS, 4.0, art.resolve({}), tmp_path,
                                    [stage.MAX_NEW_PROPS_PER_VIDEO])
    assert out is None and "already drawn" in problems[0]


# --- unconstrained JSON from the model ----------------------------------------------

def test_an_unconstrained_answer_is_read_without_a_schema(monkeypatch):
    from unittest.mock import MagicMock
    from pipeline import llm
    from tests.test_llm import FakeResponse

    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return FakeResponse('Here it is:\n```json\n{"elements": []}\n```')

    client = MagicMock()
    client.messages.create.side_effect = create
    monkeypatch.setattr(llm, "client", lambda: client)
    monkeypatch.setattr(llm.costs, "record_claude", lambda *a, **k: None)
    assert llm.call_json("s", "u", None, operation="scene_write", effort="medium") == {"elements": []}
    assert seen["output_config"] == {"effort": "medium"}


# --- the frame check reads the words under the frame --------------------------------

def test_the_frame_check_judges_a_scene_frame_by_the_words_spoken_then(monkeypatch):
    from pipeline import editor_check
    from pipeline.plan import Shot

    segments = [Segment(text="first words", shot_brief="b1", start=0, end=4),
                Segment(text="second words", shot_brief="b2", start=4, end=10)]
    plan = SimpleNamespace(shots=[Shot(start=0, end=10, segment_index=0, scene=True)],
                           script=SimpleNamespace(segments=segments),
                           channel=SimpleNamespace(avoid_imagery=[]),
                           title_card_seconds=0, title_card_at=0)
    monkeypatch.setattr(editor_check, "_frames_at", lambda path, times: ["img"])
    sent = {}
    monkeypatch.setattr(editor_check, "_run", lambda system, content, op: sent.setdefault("c", content))
    editor_check.check_frames(Path("v.mp4"), plan)
    assert "second words" in sent["c"][0]["text"]            # the middle of the shot is at 5s
    # Regression: judged against the stock-footage brief ("tape measure on
    # grass"), the Pythagoras demo's diagrams were blocked for not being
    # footage. A scene is judged against the words.
    assert "b2" not in sent["c"][0]["text"] and "animated explanation" in sent["c"][0]["text"]


class TestPlan:
    """The slider is a threshold on each segment's need for a picture, not a
    quota of the video (decision 037)."""
    SEGMENTS = [Segment(text=f"line {i}", shot_brief=f"brief {i}", start=i * 5.0, end=(i + 1) * 5.0)
                for i in range(4)]
    RATED = [{"index": 0, "need": 2, "idea": "a hook", "builds_on_previous": False},
             {"index": 1, "need": 10, "idea": "the triangle", "builds_on_previous": False},
             {"index": 2, "need": 7, "idea": "its squares", "builds_on_previous": True},
             {"index": 3, "need": 5, "idea": "the answer", "builds_on_previous": False}]

    def _plan(self, monkeypatch, share, rated=None):
        calls = []
        monkeypatch.setattr(writer, "call_json",
                            lambda *a, **k: calls.append(a) or {"segments": rated or self.RATED})
        return writer.plan(self.SEGMENTS, share, "Pythagoras"), calls

    def _spans(self, scenes):
        return [(s["first"], s["last"]) for s in scenes]

    def test_fully_stock_never_asks(self, monkeypatch):
        scenes, calls = self._plan(monkeypatch, 0)
        assert scenes == [] and calls == []

    def test_fully_animated_animates_every_segment_whatever_its_score(self, monkeypatch):
        scenes, _ = self._plan(monkeypatch, 100)
        assert self._spans(scenes) == [(0, 0), (1, 2), (3, 3)]

    def test_near_the_stock_end_only_essential_segments_are_animated(self, monkeypatch):
        scenes, _ = self._plan(monkeypatch, 10)                   # bar: 9
        assert self._spans(scenes) == [(1, 1)]
        assert scenes[0]["idea"] == "the triangle"

    def test_in_the_middle_anything_a_picture_helps_is_animated(self, monkeypatch):
        scenes, _ = self._plan(monkeypatch, 50)                   # bar: 5
        assert self._spans(scenes) == [(1, 2), (3, 3)]
        assert scenes[0]["idea"] == "the triangle Then: its squares"

    def test_the_bar_moves_the_same_way_as_the_slider(self):
        bars = [writer.need_threshold(s) for s in (5, 30, 50, 80, 95)]
        assert bars == sorted(bars, reverse=True)
        assert writer.need_threshold(0) is None and writer.need_threshold(100) == 0

    def test_the_model_is_never_told_the_slider(self, monkeypatch):
        # The score must be the segment's own, so the same script scores
        # the same whatever the channel's setting.
        _, calls = self._plan(monkeypatch, 30)
        assert "30" not in calls[0][1] and "%" not in calls[0][1]

    def test_a_segment_left_unscored_counts_as_no_need(self, monkeypatch):
        scenes, _ = self._plan(monkeypatch, 60, rated=[self.RATED[1]])
        assert self._spans(scenes) == [(1, 1)]



def test_every_scene_is_written_with_the_whole_narration(plan, monkeypatch):
    # Regression: written with only its own lines, the Pythagoras demo's
    # third scene labelled the wall 6 (it was 8) and showed the answer
    # before the narration reached it.
    monkeypatch.setattr(writer, "plan", lambda *a: [{"first": 1, "last": 1, "idea": "b"}])
    seen = {}

    def make(idea, words, duration, style, library, context, *rest):
        seen.update(context)
        return Path("b.mp4"), []

    monkeypatch.setattr(stage, "_make", make)
    stage.run(plan)
    assert seen["narration"] == "[0] one two\n[1] three four"


# --- props: the free library first, and laid on exact points --------------------

class TestIconLibrary:
    def test_names_are_tried_most_specific_first(self):
        from pipeline.scenes import iconlib
        assert iconlib.candidates("Wooden ladder") == ["wooden-ladder", "ladder", "wooden"]
        assert iconlib.candidates("a coin") == ["coin"]

    def test_only_an_exact_name_counts(self, monkeypatch):
        from pipeline.scenes import iconlib

        class Response:
            status_code = 200
            def __init__(self, icons): self._icons = icons
            def json(self): return {"icons": self._icons}

        seen = []

        def fake_get(url, params=None, timeout=None):
            seen.append(params["query"])
            return Response({"brick-wall": [], "wall": ["fluent-emoji-flat:wall-clock"],
                             "brick": ["fluent-emoji-flat:brick"]}[params["query"]])

        monkeypatch.setattr(iconlib.requests, "get", fake_get)
        # "wall" must not become a wall clock; "brick" is an exact match.
        assert iconlib.find("brick wall", "fluent-emoji-flat") == "fluent-emoji-flat:brick"
        assert seen == ["brick-wall", "wall", "brick"]

    def test_an_unreachable_library_falls_back_to_generating(self, monkeypatch, tmp_path):
        from pipeline.scenes import iconlib, props

        def down(*a, **k):
            raise iconlib.requests.ConnectionError("offline")

        monkeypatch.setattr(iconlib.requests, "get", down)
        drawn = []
        monkeypatch.setattr(props, "_generate", lambda prompt: drawn.append(prompt) or _png_bytes())
        path = props.get(tmp_path, "candle", "chalk", icons={"set": "fluent-emoji-flat"})
        assert path.exists() and len(drawn) == 1

    def test_a_library_prop_is_kept_with_its_licence(self, monkeypatch, tmp_path):
        from pipeline.scenes import iconlib, props
        monkeypatch.setattr(iconlib, "find", lambda name, s: "fluent-emoji-flat:candle")
        tints = []
        monkeypatch.setattr(iconlib, "fetch_svg", lambda icon, tint="": tints.append(tint) or "<svg/>")
        monkeypatch.setattr(iconlib, "rasterize", lambda svg: _png_bytes())
        monkeypatch.setattr(props, "_generate", lambda prompt: pytest.fail("paid for a free prop"))
        path = props.get(tmp_path, "candle", "chalk",
                         icons={"set": "fluent-emoji-flat", "tint": "#F4F1E8"})
        import json
        note = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        assert note["licence"] == "MIT" and note["source"] == "iconify:fluent-emoji-flat:candle"
        assert tints == ["#F4F1E8"]

    def test_a_line_style_tints_its_props_in_the_channels_ink(self):
        icons = stage._icons(art.resolve({"preset": "chalkboard", "ink": "#ABCDEF"}))
        assert icons == {"set": "fluent-emoji-high-contrast", "tint": "#ABCDEF"}


def _png_bytes(size=(200, 200)):
    import io
    from PIL import Image
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    image.paste(Image.new("RGBA", size, (200, 120, 40, 255)), (100, 100))
    out = io.BytesIO(); image.save(out, format="PNG")
    return out.getvalue()


def test_a_props_long_axis_is_found_whatever_angle_it_was_drawn_at(tmp_path):
    from PIL import Image, ImageDraw
    from pipeline.scenes import props
    import math
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(image).line([(80, 320), (320, 80)], fill=(0, 0, 0, 255), width=24)  # foot bottom-left
    path = tmp_path / "pole.png"; image.save(path)
    meta = props.axis(path)
    assert math.degrees(meta["angle"]) == pytest.approx(-45, abs=3)     # pointing up and right
    assert meta["length"] == pytest.approx(340, abs=25)
    assert (meta["cx"], meta["cy"]) == (pytest.approx(200, abs=6), pytest.approx(200, abs=6))


def test_the_draft_gives_a_new_channel_its_hook_style(tmp_path, monkeypatch):
    from core import drafts
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", tmp_path / "channels.json")
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(drafts.channel_admin, "create_channel", lambda channel, complete: None)
    drafts.save({"id": "d1", "pitch": "p", "outline": [], "channel": {
        "name_options": ["Hooked"], "content_mode": "static_corpus", "corpus_source": "bible",
        "voice_ids": ["a" * 20], "style_prompt": "Warm.", "hook_style": "Open on a quiet question.",
        "avoid_imagery": [], "speed": 1.0, "target_seconds": 45, "segment_count": 3,
        "palette_key": "warm_gold", "custom_quotes": [], "subject": ""}})
    channel = drafts.accept("d1", {})
    assert channel.hook_style == "Open on a quiet question."


def test_a_picture_huddled_in_a_corner_is_sent_back_to_be_drawn_bigger():
    small = [(5.0, [{"id": "tri", "type": "shape", "kind": "poly", "box": [300, 200, 600, 500]}])]
    big = [(5.0, [{"id": "tri", "type": "shape", "kind": "poly", "box": [120, 200, 960, 1100]}])]
    assert "Draw it bigger" in writer.too_small(small)[0]
    assert writer.too_small(big) == []


def test_the_picture_check_turns_what_it_sees_into_repair_notes(monkeypatch):
    # Regression: the ladder "against a wall" was drawn with no wall; boxes
    # can't see that, a look at the stills can.
    seen = {}

    def fake(system, content, schema, **kwargs):
        seen["content"], seen["kwargs"] = content, kwargs
        return {"problems": ["The words say the ladder leans on a wall, but no wall is drawn."]}

    monkeypatch.setattr(writer, "call_json", fake)
    notes = writer.picture_problems([b"jpeg1", b"jpeg2"], ["lean a ladder", "against a wall"],
                                    "lean a ladder against a wall")
    assert notes == ["Picture check: The words say the ladder leans on a wall, but no wall is drawn."]
    assert sum(1 for c in seen["content"] if c["type"] == "image") == 2
    assert seen["kwargs"]["model"] == writer.PICTURE_MODEL


def test_a_picture_check_that_cannot_run_finds_nothing(monkeypatch):
    def down(*a, **k):
        raise ExternalServiceError("Claude", "down", user_message="The AI service failed.")
    monkeypatch.setattr(writer, "call_json", down)
    assert writer.picture_problems([b"x"], ["y"], "z") == []


def test_the_frame_check_judges_a_scene_once_it_is_built(monkeypatch):
    # Regression: sampled mid-way, a scene is always "incomplete", and the
    # frame check blocked the Pythagoras video for it.
    from pipeline import editor_check
    from pipeline.plan import Shot

    segments = [Segment(text="all of it", shot_brief="b", start=0, end=10)]
    plan = SimpleNamespace(shots=[Shot(start=0, end=10, segment_index=0, scene=True),
                                  Shot(start=10, end=14, segment_index=0)],
                           script=SimpleNamespace(segments=segments),
                           channel=SimpleNamespace(avoid_imagery=[]),
                           title_card_seconds=0, title_card_at=0)
    asked = {}
    monkeypatch.setattr(editor_check, "_frames_at", lambda path, times: asked.setdefault("t", times))
    monkeypatch.setattr(editor_check, "_run", lambda *a: None)
    editor_check.check_frames(Path("v.mp4"), plan)
    assert asked["t"] == [pytest.approx(9.0), pytest.approx(12.0)]


def test_maths_elements_are_checked_like_the_rest():
    raw = {"props": [], "elements": [
        {"id": "m", "type": "math", "tex": r"\frac{a}{b", "x": 1, "y": 1},
        {"id": "p", "type": "plot", "x": 1, "y": 1, "x_range": [5, 1], "y_range": [0, 1]},
        {"id": "n", "type": "numberline", "x": 1, "y": 1, "from": 3, "to": 3},
    ], "actions": [{"target": t, "do": "draw", "word": 0, "dur": 1} for t in "mpn"] +
                  [{"target": "m", "do": "rotate", "word": 0, "dur": 1}]}
    _, problems = writer.validate(raw, WORDS, 5.0)
    text = " ".join(problems)
    assert "unbalanced braces" in text and "x_range" in text and "from < to" in text
    assert "has no angle" in text
