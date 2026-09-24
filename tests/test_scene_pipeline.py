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
    monkeypatch.setattr(stage, "_check", lambda *a: next(checks))
    monkeypatch.setattr(stage.render, "render", lambda sc, st, assets, out: out)
    clip, notes = stage._make("idea", WORDS, 4.0, art.resolve({}), tmp_path, {},
                              tmp_path / "scene_1", 0.5, [0])
    assert calls == [None, ["'a' and 'b' overlap"]]
    assert notes == [] and clip.suffix == ".mp4"
    assert (tmp_path / "scene_1.json").exists()


def test_a_scene_still_broken_after_repair_is_not_rendered(plan, monkeypatch, tmp_path):
    monkeypatch.setattr(writer, "write", lambda *a, **k: {})
    monkeypatch.setattr(stage, "_check", lambda *a: (None, ["no elements"], {}))
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
    SEGMENTS = [Segment(text=f"line {i}", shot_brief=f"brief {i}", start=i * 5.0, end=(i + 1) * 5.0)
                for i in range(4)]

    def _plan(self, monkeypatch, scenes, share):
        monkeypatch.setattr(writer, "call_json", lambda *a, **k: {"scenes": scenes})
        return writer.plan(self.SEGMENTS, share, "Pythagoras")

    def test_overlapping_ranges_are_trimmed_not_dropped(self, monkeypatch):
        out = self._plan(monkeypatch, [{"first": 0, "last": 1, "idea": "a"},
                                       {"first": 1, "last": 2, "idea": "b"},
                                       {"first": 2, "last": 9, "idea": "c"}], share=50)
        assert [(s["first"], s["last"]) for s in out] == [(0, 1), (2, 2), (3, 3)]

    def test_at_100_percent_every_segment_gets_a_scene(self, monkeypatch):
        # Regression: the Pythagoras demo's plan covered one segment of
        # four, so a channel set to animate throughout got mostly stock.
        out = self._plan(monkeypatch, [{"first": 1, "last": 1, "idea": "ladder"}], share=100)
        assert [(s["first"], s["last"]) for s in out] == [(0, 0), (1, 1), (2, 2), (3, 3)]
        assert out[0]["idea"] == "brief 0" and out[1]["idea"] == "ladder"

    def test_below_100_percent_gaps_stay_stock(self, monkeypatch):
        out = self._plan(monkeypatch, [{"first": 1, "last": 1, "idea": "ladder"}], share=40)
        assert [(s["first"], s["last"]) for s in out] == [(1, 1)]


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
