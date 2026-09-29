"""
Generated animation (pipeline.animation, decision 051): the look, the
model registry's arithmetic, the storyboard made safe, the budget, the
finish, the two HTTP clients and the wiring into the visuals stage.

Every model and service is faked; nothing here spends money.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.channels import ChannelConfig, channel_from_dict, channel_to_sparse_dict
from core.errors import ConfigError, ExternalServiceError, MissingCredentialError
from pipeline.animation import fal, finish, images, look as looks, models, stage, storyboard
from pipeline.plan import Segment, WordTiming


def words_for(text: str, start: float = 0.0, step: float = 0.4) -> list:
    return [WordTiming(w, round(start + i * step, 2), round(start + i * step + 0.3, 2))
            for i, w in enumerate(text.split())]


# --- channel settings -----------------------------------------------------------

class TestChannelSetting:
    def test_off_by_default_and_not_stored(self):
        channel = ChannelConfig(key="x")
        assert channel.animation.enabled is False
        assert "animation" not in channel_to_sparse_dict(channel)

    def test_round_trips_only_what_changed(self):
        channel = ChannelConfig(key="x")
        channel.animation.enabled = True
        channel.animation.look = "paper_cutout"
        channel.animation.cast = [{"name": "Wren", "description": "a young witch"}]
        raw = channel_to_sparse_dict(channel)
        assert raw["animation"] == {"enabled": True, "look": "paper_cutout",
                                    "cast": [{"name": "Wren", "description": "a young witch"}]}
        again = channel_from_dict("x", raw)
        assert again.animation.look == "paper_cutout" and again.animation.pace == 50

    @pytest.mark.parametrize("field,value,message", [
        ("energy", 140, "0 to 100"), ("quality", "ultra", "quality"),
        ("cadence", "fours", "cadence"), ("budget", -1.0, "budget")])
    def test_bad_values_are_refused_by_name(self, field, value, message):
        channel = ChannelConfig(key="x", voice="a" * 20, style_prompt="p", topics=["t"])
        setattr(channel.animation, field, value)
        with pytest.raises(ConfigError, match=message):
            channel.validate()

    def test_a_cast_member_needs_a_name(self):
        channel = ChannelConfig(key="x", voice="a" * 20, style_prompt="p", topics=["t"])
        channel.animation.cast = [{"name": " ", "description": "someone"}]
        with pytest.raises(ConfigError, match="no name"):
            channel.validate()


# --- the look -------------------------------------------------------------------

class TestLook:
    def test_every_preset_is_complete(self):
        needed = {"key", "label", "description", "suits", "image", "light", "camera", "motion",
                  "palette", "avoid", "cadence", "grade"}
        for key, preset in looks.presets().items():
            assert needed <= set(preset), key
            assert preset["cadence"] in looks.CADENCE_FPS, key
            assert all(looks.HEX_RE.match(c) for c in preset["palette"]), key

    def test_channel_notes_palette_and_cadence_apply(self):
        look = looks.resolve(SimpleNamespace(look="risograph", style_notes="  mostly  pink ",
                                             palette=["#112233", "red"], cadence="threes"))
        assert look["notes"] == "mostly pink"
        assert look["palette"] == ["#112233"]
        assert look["cadence"] == "threes"
        assert "mostly pink" in looks.style_text(look)

    def test_an_unknown_look_falls_back(self):
        assert looks.resolve(SimpleNamespace(look="nope"))["key"] == looks.DEFAULT_LOOK

    def test_finish_zero_is_a_neutral_grade(self):
        look = looks.resolve(SimpleNamespace(look="graphic_noir", finish=0))
        assert look["grade"]["contrast"] == 1.0 and look["grade"]["grain"] == 0.0
        assert finish.grade_filters(look) == [] and finish.texture_filters(look) == []

    def test_style_frames_are_redrawn_only_when_the_look_changes(self):
        a = looks.resolve(SimpleNamespace(look="clean_cel", energy=10, pace=90))
        b = looks.resolve(SimpleNamespace(look="clean_cel", energy=90, pace=10))
        c = looks.resolve(SimpleNamespace(look="clean_cel", style_notes="thicker lines"))
        assert a["identity"] == b["identity"] != c["identity"]

    def test_paper_looks_keep_their_texture_still(self):
        paper = looks.resolve(SimpleNamespace(look="storybook_gouache"))
        film = looks.resolve(SimpleNamespace(look="graphic_noir"))
        assert "t+u" not in finish.texture_filters(paper)[0]
        assert "t+u" in finish.texture_filters(film)[0]


# --- models -----------------------------------------------------------------------

class TestModels:
    def test_the_cheapest_length_that_retimes_onto_the_shot(self):
        h3 = models.VIDEO_MODELS["h3_max"]
        assert h3.seconds_for(2.0) == 5          # shortest, trimmed
        assert h3.seconds_for(6.25) == 5         # 5s sped up by a quarter
        assert h3.seconds_for(6.3) == 6
        assert h3.seconds_for(40) == 15
        veo = models.VIDEO_MODELS["veo31_lite"]
        assert veo.seconds_for(5.1) == 6 and veo.seconds_for(5.0) == 4

    def test_fit_never_retimes_past_a_quarter(self):
        assert models.fit(4.0, 5.0) == (1.25, 5.0)
        assert models.fit(2.0, 5.0) == (1.25, 2.5)            # trimmed to what's shown
        assert models.fit(6.0, 5.0) == (0.8333, 5.0)

    def test_requests_are_shaped_per_model(self):
        h3 = models.VIDEO_MODELS["h3_max"].request("p", "data:x", 6, "standard", seed=3)
        assert h3 == {"prompt": "p", "image_url": "data:x", "duration": 6, "resolution": "768P",
                      "prompt_expansion_mode": "disabled", "seed": 3}
        veo = models.VIDEO_MODELS["veo31_lite"].request("p", "data:x", 6, "draft")
        assert veo["duration"] == "6s" and veo["generate_audio"] is False
        assert veo["aspect_ratio"] == "9:16" and veo["resolution"] == "720p"

    def test_estimate_counts_the_video_model_and_the_pictures(self):
        est = models.estimate(50, 5.5, models.VIDEO_MODELS["h3_max"],
                              models.IMAGE_MODELS["gpt_image_flare"], "standard")
        assert est.shots == 9 and est.generated == 45
        assert est.video_usd == pytest.approx(3.60)
        assert est.total == pytest.approx(3.60 + est.image_usd + est.other_usd, abs=0.01)

    def test_unknown_models_fall_back_to_the_defaults(self):
        assert models.video_model("gone").key == models.DEFAULT_VIDEO_MODEL
        assert models.image_model("gone").key == models.DEFAULT_IMAGE_MODEL


# --- the storyboard made safe ------------------------------------------------------

TEXT = ("You see someone yawn and boom you are yawning too but why does a mouth "
        "stretching open on a screen hijack your own face")


def narration():
    words = words_for(TEXT + " " + TEXT)
    half = len(words) // 2
    segments = [Segment(text=TEXT, start=0.0, end=words[half].start),
                Segment(text=TEXT, start=words[half].start, end=words[-1].end + 0.3)]
    return segments, words


def raw_shot(word, **over):
    base = {"start_word": word, "framing": "close-up", "image": f"frame {word}",
            "motion": "she yawns", "camera": "slow push-in", "elements": ["maya"],
            "continues": False, "why": "the hook"}
    base.update(over)
    return base


def settle(shots, ranges=((0, 1),), budget=10.0, model="h3_max", cast=(), elements=None):
    segments, words = narration()
    windows = storyboard.spans(segments, list(ranges), words)
    raw = {"concept": "c", "colour_script": "cool to warm",
           "elements": elements if elements is not None else [
               {"key": "Maya", "kind": "character", "name": "Maya", "description": "grey hoodie"}],
           "shots": shots}
    return storyboard.settle(raw, windows, words, models.VIDEO_MODELS[model], "standard",
                             budget, list(cast))


class TestSettle:
    def test_the_first_shot_opens_the_window_and_cuts_lead_their_word(self):
        board, _ = settle([raw_shot(3), raw_shot(12)])
        first, second = board["shots"]
        assert first["start"] == 0.0                         # moved onto the first word
        assert second["start"] == pytest.approx(12 * 0.4 - storyboard.LEAD)
        assert first["end"] == second["start"]
        assert board["elements"]["maya"]["name"] == "Maya"

    def test_cuts_outside_the_animation_are_dropped(self):
        segments, words = narration()
        half = len(words) // 2
        board, notes = settle([raw_shot(0), raw_shot(half + 3)], ranges=((0, 0),))
        assert len(board["shots"]) == 1 and any("outside" in n for n in notes)

    def test_a_window_with_no_shot_gets_one(self):
        segments, words = narration()
        board, notes = settle([raw_shot(0)], ranges=((0, 0), (1, 1)))
        assert [s["window"] for s in board["shots"]] == [0, 1]
        assert board["shots"][1].get("missing")

    def test_a_shot_too_short_to_read_merges(self):
        board, _ = settle([raw_shot(0), raw_shot(10), raw_shot(12)])
        assert [s["start_word"] for s in board["shots"]] == [0, 12]

    def test_a_shot_longer_than_the_model_becomes_a_continued_take(self):
        board, _ = settle([raw_shot(0)], model="veo31_lite")    # one 17s shot; veo's max is 10
        shots = board["shots"]
        assert len(shots) == 2 and shots[1]["continues"] and not shots[0]["continues"]
        assert shots[1]["start"] == pytest.approx(shots[0]["end"])
        assert all(s["duration"] <= 8 * models.RETIME_MAX for s in shots)

    def test_the_budget_is_met_by_merging_neighbours(self):
        shots = [raw_shot(w) for w in (0, 6, 12, 18, 24, 30, 36)]      # 7 x 5s = $2.80
        board, notes = settle(shots, budget=1.3)
        assert storyboard.cost(board["shots"], models.VIDEO_MODELS["h3_max"], "standard") <= 1.3
        assert len(board["shots"]) < 7 and any("budget" in n for n in notes)

    def test_an_impossible_budget_still_leaves_shots_the_model_can_make(self):
        board, _ = settle([raw_shot(w) for w in (0, 6, 12, 18, 24, 30, 36)], budget=0.1)
        longest = 15 * models.RETIME_MAX
        assert board["shots"] and all(s["duration"] <= longest for s in board["shots"])

    def test_a_cast_member_keeps_the_channels_description(self):
        cast = [{"name": "Maya", "description": "the channel's Maya"}]
        board, _ = settle([raw_shot(0)], cast=cast)
        assert board["elements"]["maya"] == {"kind": "character", "name": "Maya",
                                             "description": "the channel's Maya", "cast": True}

    def test_unknown_elements_are_dropped_from_shots(self):
        board, _ = settle([raw_shot(0, elements=["maya", "ghost"])])
        assert board["shots"][0]["elements"] == ["maya"]

    def test_every_shot_knows_what_to_generate(self):
        board, _ = settle([raw_shot(0), raw_shot(20)])
        for s in board["shots"]:
            assert s["generate"] == models.VIDEO_MODELS["h3_max"].seconds_for(s["duration"])


class TestLimits:
    def test_the_pace_slider_sets_the_average_shot(self):
        assert models.mean_shot_seconds(0) == 7.5
        assert models.mean_shot_seconds(100) == 3.5

    def test_the_budget_caps_the_shot_count(self):
        h3 = models.VIDEO_MODELS["h3_max"]
        limits = storyboard.shot_limits(50, 100, h3, max_video_usd=1.2, quality="standard")
        assert limits["most"] == 3                       # $0.40 a shot at the least


# --- the stage's arithmetic ------------------------------------------------------

class TestStage:
    def test_runs(self):
        assert stage.runs([4, 0, 1, 2, 6]) == [(0, 2), (4, 4), (6, 6)]

    def test_what_the_budget_cannot_cover_goes_back_from_the_end(self):
        segments = [Segment(text="x", start=i * 10.0, end=(i + 1) * 10.0) for i in range(5)]
        kept, dropped = stage.affordable([(0, 4)], segments, 2.5, models.VIDEO_MODELS["h3_max"],
                                         models.IMAGE_MODELS["gpt_image_flare"], "standard", 50)
        assert kept and kept[0][0] == 0 and dropped and dropped[-1][1] == 4

    def test_a_generous_budget_keeps_everything(self):
        segments = [Segment(text="x", start=0.0, end=10.0)]
        kept, dropped = stage.affordable([(0, 0)], segments, 50, models.VIDEO_MODELS["h3_max"],
                                         models.IMAGE_MODELS["gpt_image_flare"], "standard", 50)
        assert kept == [(0, 0)] and dropped == []


class TestFinish:
    def test_the_cadence_holds_frames_before_scaling(self):
        vf = finish.shot_filter(looks.resolve(SimpleNamespace(look="stop_motion_clay")), 1.1)
        assert vf.startswith("setpts=PTS/1.10000,fps=8,scale=1080:1920")
        assert vf.endswith("fps=30,format=yuv420p")

    def test_on_ones_nothing_is_held(self):
        vf = finish.shot_filter(looks.resolve(SimpleNamespace(look="soft_3d")), 1.0)
        assert "fps=24" not in vf and "fps=12" not in vf


# --- clients -----------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)
        self.headers = headers or {}

    def json(self):
        return self._body


class TestFal:
    def test_no_key_is_a_named_missing_credential(self, monkeypatch):
        monkeypatch.delenv("FAL_KEY", raising=False)
        with pytest.raises(MissingCredentialError, match="FAL_KEY"):
            fal.run("m/x", {})

    def test_queue_poll_fetch(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "k")
        monkeypatch.setattr(fal, "POLL_SECONDS", 0)
        calls = []
        replies = iter([
            FakeResponse(body={"request_id": "r", "status_url": "https://q/s",
                               "response_url": "https://q/r"}),
            FakeResponse(body={"status": "IN_PROGRESS"}),
            FakeResponse(body={"status": "COMPLETED"}),
            FakeResponse(body={"video": {"url": "https://cdn/v.mp4"}}),
        ])

        def fake(method, url, headers=None, timeout=None, **kw):
            calls.append((method, url, headers["Authorization"]))
            return next(replies)
        monkeypatch.setattr(fal.requests, "request", fake)
        result = fal.run("minimax/h3-max/image-to-video", {"prompt": "p"})
        assert models.VideoModel.video_url(result) == "https://cdn/v.mp4"
        assert calls[0] == ("POST", "https://queue.fal.run/minimax/h3-max/image-to-video", "Key k")
        assert [c[1] for c in calls[1:]] == ["https://q/s", "https://q/s", "https://q/r"]

    def test_a_failed_generation_says_so(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "k")
        replies = iter([FakeResponse(body={"request_id": "r", "status_url": "s",
                                           "response_url": "r"}),
                        FakeResponse(body={"status": "COMPLETED", "error": "bad frame",
                                           "error_type": "x"})])
        monkeypatch.setattr(fal.requests, "request", lambda *a, **k: next(replies))
        with pytest.raises(ExternalServiceError) as exc:
            fal.run("m/x", {}, what="shot 2")
        assert "shot 2" in exc.value.user_message

    @pytest.mark.parametrize("status,body,phrase", [
        (401, "Unauthorized", "FAL_KEY was rejected"),
        (403, "User is locked. Reason: Exhausted balance", "out of credit"),
        (422, "content policy violation", "safety filter")])
    def test_errors_become_sentences(self, monkeypatch, status, body, phrase):
        monkeypatch.setenv("FAL_KEY", "k")
        response = FakeResponse(status=status)
        response.text = body
        monkeypatch.setattr(fal.requests, "request", lambda *a, **k: response)
        with pytest.raises(ExternalServiceError) as exc:
            fal.run("m/x", {})
        assert phrase in exc.value.user_message


def png_bytes(size=(8, 8)) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", size, (200, 100, 50)).save(out, format="PNG")
    return out.getvalue()


class TestImages:
    def test_references_go_to_the_edits_endpoint_and_the_real_cost_is_recorded(
            self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        ref = tmp_path / "ref.png"
        ref.write_bytes(png_bytes())
        seen, recorded = {}, []

        def fake_post(url, headers=None, data=None, files=None, json=None, timeout=None):
            seen.update(url=url, data=data, files=files)
            return FakeResponse(body={"data": [{"b64_json": base64.b64encode(b"img").decode()}],
                                      "usage": {"input_tokens": 1000, "output_tokens": 300,
                                                "input_tokens_details": {"image_tokens": 900,
                                                                         "text_tokens": 100}}})
        monkeypatch.setattr(images.requests, "post", fake_post)
        monkeypatch.setattr(images.costs, "_write", recorded.append)
        out = images.draw("a frame", tmp_path / "kf.jpg", models.IMAGE_MODELS["gpt_image_flare"],
                          references=[ref])
        assert out.read_bytes() == b"img"
        assert seen["url"] == images.EDITS and seen["data"]["size"] == "864x1536"
        assert seen["data"]["output_format"] == "jpeg"
        assert [f[0] for f in seen["files"]] == ["image[]"]
        assert recorded[0].cost_usd == pytest.approx((100 * 5 + 900 * 8 + 300 * 30) / 1e6)

    def test_no_references_is_a_plain_generation(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        seen = {}

        def fake_post(url, headers=None, data=None, files=None, json=None, timeout=None):
            seen.update(url=url, json=json)
            return FakeResponse(body={"data": [{"b64_json": base64.b64encode(b"x").decode()}]})
        monkeypatch.setattr(images.requests, "post", fake_post)
        monkeypatch.setattr(images.costs, "_write", lambda r: None)
        images.draw("p", tmp_path / "f.png", models.IMAGE_MODELS["gpt_image_sunburst"])
        assert seen["url"] == images.GENERATIONS and seen["json"]["output_format"] == "png"

    def test_a_moderation_refusal_is_a_sentence(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setattr(images.requests, "post", lambda *a, **k: FakeResponse(
            status=400, body={"error": {"code": "moderation_blocked"}}))
        with pytest.raises(ExternalServiceError) as exc:
            images.draw("p", tmp_path / "f.png", models.IMAGE_MODELS["gpt_image_flare"])
        assert "safety" in exc.value.user_message


# --- wiring: the director and the visuals stage ---------------------------------------

class TestDirector:
    def test_animation_replaces_illustration(self, monkeypatch):
        from pipeline import director
        seen = {}

        def fake_call(system, user, schema, **kw):
            seen["enum"] = schema["properties"]["segments"]["items"]["properties"]["medium"]["enum"]
            seen["guide"] = system[0].text
            return {"segments": [{"index": 0, "medium": "animation", "template": "",
                                  "brief": "a yawn", "need": 9, "reason": "r"}]}
        monkeypatch.setattr(director, "call_json", fake_call)
        out = director.direct([Segment(text="t", start=0, end=3)], "yawns", 100, animation=True)
        assert out[0]["medium"] == "animation"
        assert "animation" in seen["enum"] and "illustration" not in seen["enum"]
        assert "- animation:" in seen["guide"] and "- illustration:" not in seen["guide"]

    def test_without_animation_nothing_changes(self, monkeypatch):
        from pipeline import director
        seen = {}

        def fake_call(system, user, schema, **kw):
            seen["enum"] = schema["properties"]["segments"]["items"]["properties"]["medium"]["enum"]
            return {"segments": [{"index": 0, "medium": "footage", "template": "", "brief": "b",
                                  "need": 0, "reason": "r"}]}
        monkeypatch.setattr(director, "call_json", fake_call)
        out = director.direct([Segment(text="t", start=0, end=3)], "s", 100)
        assert out[0]["medium"] == "illustration"             # always graphics: never footage
        assert "animation" not in seen["enum"]


def visuals_plan(tmp_path, enabled=True):
    channel = ChannelConfig(key="demo")
    channel.scenes.share = 100
    channel.animation.enabled = enabled
    segments = [Segment(text="one two three", start=0.0, end=3.0),
                Segment(text="four five six", start=3.0, end=6.0)]
    return SimpleNamespace(
        channel=channel, seed=SimpleNamespace(title="demo"), out_dir=tmp_path, stem="demo",
        script=SimpleNamespace(segments=segments, screen_hook=""),
        voiceover=SimpleNamespace(word_timings=words_for("one two three four five six",
                                                         step=1.0)),
        scene_clips=[], scenes_fell_back=0, scene_notes=[], animation={})


class TestVisualsWiring:
    def _direct_all_animation(self, monkeypatch):
        from pipeline import director, visuals
        monkeypatch.setattr(visuals.stage, "_restore", lambda: None)
        monkeypatch.setattr(visuals.stage, "_save", lambda plan: None)
        monkeypatch.setattr(director, "direct", lambda segments, *a, **k: [
            {"index": i, "medium": "animation" if k.get("animation") else "illustration",
             "template": "", "brief": "b", "need": 9, "reason": "r"}
            for i in range(len(segments))])
        return visuals

    def test_without_a_key_it_says_so_and_draws_illustrations(self, monkeypatch, tmp_path):
        visuals = self._direct_all_animation(monkeypatch)
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.setattr(visuals, "_make", lambda d, *a, **k: (tmp_path / "i.mp4", []))
        plan = visuals.run(visuals_plan(tmp_path))
        assert any("FAL_KEY" in n for n in plan.scene_notes)
        assert [c["kind"] for c in plan.scene_clips] == ["illustration", "illustration"]

    def test_animation_clips_join_the_plan(self, monkeypatch, tmp_path):
        visuals = self._direct_all_animation(monkeypatch)
        monkeypatch.setenv("FAL_KEY", "k")
        from pipeline.animation import stage as animation_stage
        result = animation_stage.Result()
        result.clips = [{"first": 0, "last": 1, "clip": str(tmp_path / "a.mp4"),
                         "kind": "animation"}]
        result.summary = {"shots": 3}
        monkeypatch.setattr(animation_stage, "make", lambda plan, idx, briefs, folder, tail:
                            result if idx == [0, 1] else None)
        plan = visuals.run(visuals_plan(tmp_path))
        assert plan.scene_clips == result.clips and plan.animation == {"shots": 3}

    def test_a_failed_animation_falls_back_and_is_flagged(self, monkeypatch, tmp_path):
        visuals = self._direct_all_animation(monkeypatch)
        monkeypatch.setenv("FAL_KEY", "k")
        from pipeline.animation import stage as animation_stage

        def boom(*a, **k):
            raise ExternalServiceError("fal", "down", user_message="fal is down")
        monkeypatch.setattr(animation_stage, "make", boom)
        plan = visuals.run(visuals_plan(tmp_path))
        assert plan.scene_clips == [] and plan.scenes_fell_back == 2
        assert any("fal is down" in n for n in plan.scene_notes)


# --- the settings page, its endpoints, and preview jobs ------------------------------

from tests.test_web import client, config_path, csrf  # noqa: E402,F401  (fixtures)


class TestSettingsPage:
    def test_the_section_renders_with_every_look(self, client):
        body = client.get("/channels/test_channel/settings").get_data(as_text=True)
        assert 'id="section-animation"' in body
        for preset in looks.presets().values():
            assert preset["label"] in body

    def test_a_quiz_channel_has_no_animation_section(self, client, config_path):
        from core.channels import load_channels, save_channel
        channel = load_channels(config_path)["test_channel"]
        channel.format = "quiz"
        save_channel(channel, config_path)
        body = client.get("/channels/test_channel/settings").get_data(as_text=True)
        assert 'id="section-animation"' not in body

    def test_saving_the_form_stores_the_animation(self, client, config_path):
        from core.channels import load_channels
        response = client.post("/channels/test_channel/settings", data={
            "csrf_token": csrf(client), "content_mode": "topic", "voice": "21m00Tcm4TlvDq8ikWAM",
            "style_prompt": "Write something.", "topics": "coffee",
            "anim_present": "1", "anim_enabled": "on", "anim_look": "paper_cutout",
            "anim_style_notes": "  always   dusk ", "anim_energy": "70", "anim_pace": "30",
            "anim_finish": "80", "anim_cadence": "threes", "anim_quality": "draft",
            "anim_video_model": "veo31_lite", "anim_image_model": "gpt_image_2",
            "anim_budget": "3.5", "anim_cast_name_0": "Wren", "anim_cast_desc_0": "a witch",
            "anim_cast_name_1": "", "anim_palette_custom": "on",
            **{f"anim_palette_{i}": "#10203" + str(i) for i in range(6)},
        })
        assert response.status_code == 302
        a = load_channels(config_path)["test_channel"].animation
        assert (a.enabled, a.look, a.style_notes, a.energy, a.pace, a.finish) == (
            True, "paper_cutout", "always dusk", 70, 30, 80)
        assert (a.cadence, a.quality, a.video_model, a.image_model, a.budget) == (
            "threes", "draft", "veo31_lite", "gpt_image_2", 3.5)
        assert a.cast == [{"name": "Wren", "description": "a witch"}]
        assert a.palette == [f"#10203{i}" for i in range(6)]

    def test_a_form_without_the_section_leaves_animation_alone(self, client, config_path):
        from core.channels import load_channels, save_channel
        channel = load_channels(config_path)["test_channel"]
        channel.animation.enabled = True
        save_channel(channel, config_path)
        client.post("/channels/test_channel/settings", data={
            "csrf_token": csrf(client), "content_mode": "topic", "voice": "21m00Tcm4TlvDq8ikWAM",
            "style_prompt": "Write something.", "topics": "coffee"})
        assert load_channels(config_path)["test_channel"].animation.enabled is True

    def test_the_estimate(self, client):
        data = client.get("/api/animation/estimate?quality=standard&video_model=h3_max"
                          "&image_model=gpt_image_flare&pace=50&budget=1").get_json()
        assert "50-second" in data["text"] and data["over"] is True

    def test_the_bible_for_an_unsaved_look(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("core.paths.CHANNELS_DIR", tmp_path / "channels")
        response = client.post("/api/channels/test_channel/animation/bible",
                               headers={"X-CSRF-Token": csrf(client)},
                               json={"look": "risograph", "style_notes": "pink"})
        assert response.get_json() == {"frames": [], "chosen": 0, "cast": {}, "prompts": [],
                                       "stale": False}

    def test_bible_files_cannot_escape(self, client):
        assert client.get("/channels/test_channel/animation/file/clean_cel/..%2F..%2F"
                          "config%2Fchannels.json").status_code in (400, 404)
        assert client.get("/channels/test_channel/animation/file/nope/x.png").status_code == 404

    def test_a_preview_starts_a_job_on_a_real_video(self, client, tmp_path, monkeypatch):
        video = tmp_path / "out" / "test_channel" / "2026-09-01" / "v.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"x")
        monkeypatch.setattr("core.paths.OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr("web.blueprints.animation.OUTPUT_DIR", tmp_path / "out")
        started = []
        monkeypatch.setattr("web.blueprints.animation.jobs.start_job",
                            lambda key, seed: started.append((key, seed)) or "job1")
        response = client.post("/api/channels/test_channel/animation/preview",
                               headers={"X-CSRF-Token": csrf(client)},
                               json={"video": "test_channel/2026-09-01/v.mp4"})
        assert response.get_json() == {"job_id": "job1"}
        assert started[0][1]["type"] == "animation_preview" and started[0][1]["animate"] is False

    def test_animating_a_preview_needs_the_key(self, client, tmp_path, monkeypatch):
        monkeypatch.delenv("FAL_KEY", raising=False)
        video = tmp_path / "out" / "v.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"x")
        monkeypatch.setattr("web.blueprints.animation.OUTPUT_DIR", tmp_path / "out")
        response = client.post("/api/channels/test_channel/animation/preview",
                               headers={"X-CSRF-Token": csrf(client)},
                               json={"video": "v.mp4", "animate": True})
        assert response.status_code == 400 and "FAL_KEY" in response.get_json()["error"]


class TestPreviewJob:
    def test_it_runs_the_preview_and_never_publishes(self, monkeypatch, tmp_path):
        from core import jobs
        channel = ChannelConfig(key="demo")
        monkeypatch.setattr("core.channels.load_channels", lambda *a, **k: {"demo": channel})
        monkeypatch.setattr("core.paths.OUTPUT_DIR", tmp_path)
        (tmp_path / "v.mp4").write_bytes(b"x")
        ran = []
        from pipeline.animation import preview
        monkeypatch.setattr(preview, "run", lambda ch, video, animate: ran.append(
            (ch.key, video.name, animate)) or tmp_path / "v_animatic.mp4")
        monkeypatch.setattr(jobs, "_autopilot", lambda *a: pytest.fail("a preview never publishes"))
        monkeypatch.setattr(jobs, "_persist", lambda job_id: None)
        monkeypatch.setattr(jobs, "_advance_queue", lambda: None)
        monkeypatch.setattr(jobs, "_refuse_if_stale", lambda: None)
        jobs._jobs["p1"] = jobs.Job(id="p1", channel_key="demo",
                                    seed={"type": "animation_preview", "video": "v.mp4"})
        try:
            # On its own thread, as jobs run for real: _run sets the job id
            # in its context, and on the test's thread that id would leak
            # into every later test's checkpoints and cost records.
            import threading
            worker = threading.Thread(target=jobs._run, args=("p1", "demo",
                                                              jobs._jobs["p1"].seed))
            worker.start()
            worker.join(30)
            job = jobs._jobs["p1"]
            assert job.status == "done", job.error_traceback
            assert ran == [("demo", "v.mp4", False)] and "Animatic ready" in job.notes[0]
        finally:
            jobs._jobs.pop("p1", None)

    def test_preview_jobs_teach_the_eta_nothing(self):
        from core import job_eta
        job = {"status": "done", "seed": {"type": "animation_preview"}, "finished_at": 10,
               "stage_entered": {"1": 1}}
        assert job_eta._durations(job) == {}
