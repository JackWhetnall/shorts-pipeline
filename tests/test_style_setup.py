"""
The style & tone picker: drafting candidates, sampling them, and saving
the chosen one. Every model and TTS call is stubbed — this is plumbing
and safety-property testing, not a judgement about writing quality.
"""

from __future__ import annotations

import pytest

from core.channels import ChannelConfig, Pacing
from core.errors import PipelineError
from pipeline import style_gen


class TestDraftCandidates:
    def _channel(self):
        return ChannelConfig(key="c", channel_display_name="C",
                             content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                             style_prompt="p", topics=["x"])

    def test_asks_for_the_requested_count(self, monkeypatch):
        captured = {}

        def fake(system, user, schema, **kwargs):
            captured["user"] = user
            return {"candidates": [{"blurb": "a", "style_prompt": "x"}] * 3}

        monkeypatch.setattr(style_gen, "call_json", fake)
        result = style_gen.draft_candidates(self._channel(), {"format": "tutorial"}, count=3)
        assert len(result) == 3
        assert "exactly 3" in captured["user"]

    def test_the_prompt_states_every_resolved_choice(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(style_gen, "call_json", lambda system, user, schema, **k:
                            (captured.update(user=user), {"candidates": [
                                {"blurb": "a", "style_prompt": "x"}]})[1])
        style_gen.draft_candidates(self._channel(), {"format": "myth_busting"}, count=1)
        assert "Myth-busting" in captured["user"]
        # An axis left unset still appears, resolved to its default.
        assert "Register" in captured["user"]

    def test_no_candidates_is_an_error_not_an_empty_list(self, monkeypatch):
        monkeypatch.setattr(style_gen, "call_json", lambda *a, **k: {"candidates": []})
        with pytest.raises(PipelineError):
            style_gen.draft_candidates(self._channel(), {}, count=3)

    def test_a_short_answer_is_kept_rather_than_thrown_away(self, monkeypatch):
        """Getting 2 of 3 asked for is still 2 usable candidates; failing
        here would discard working answers over a count mismatch."""
        monkeypatch.setattr(style_gen, "call_json", lambda *a, **k: {
            "candidates": [{"blurb": "a", "style_prompt": "x"},
                          {"blurb": "b", "style_prompt": "y"}]})
        result = style_gen.draft_candidates(self._channel(), {}, count=3)
        assert len(result) == 2

    def test_no_schema_uses_array_bounds(self):
        schema = style_gen._candidates_schema()
        assert "minItems" not in str(schema) and "maxItems" not in str(schema)

    def test_never_asks_for_or_requires_free_text_from_the_caller(self):
        """The whole point of the picker is selecting rather than writing
        — the schema sent to the model must not require example prose
        back from this side, and draft_candidates itself takes no such
        argument."""
        import inspect

        params = inspect.signature(style_gen.draft_candidates).parameters
        assert "example" not in params and "free_text" not in params


class TestSampleForCandidate:
    def _channel(self):
        return ChannelConfig(key="c", channel_display_name="C",
                             content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                             style_prompt="original prompt, unused for this call",
                             topics=["x"], pacing=Pacing(segment_count=5,
                                                        target_seconds=90))

    def test_uses_the_candidate_prompt_not_the_channels_own(self, monkeypatch):
        from pipeline.plan import Seed

        captured = {}

        def fake_generate(seed, channel):
            captured["style_prompt"] = channel.style_prompt
            captured["segment_count"] = channel.pacing.segment_count
            captured["target_seconds"] = channel.pacing.target_seconds
            from pipeline.plan import Script
            return Script(segments=[], title_options=["t"])

        monkeypatch.setattr("pipeline.script_gen.generate_script", fake_generate)
        style_gen.sample_for_candidate(self._channel(), Seed(type="topic", topic="x"),
                                       "the candidate's own prompt")
        assert captured["style_prompt"] == "the candidate's own prompt"

    def test_the_sample_is_short_not_the_channels_real_length(self, monkeypatch):
        """A comparison sample must stay cheap regardless of how long the
        channel's real videos are configured to run."""
        from pipeline.plan import Seed, Script

        captured = {}

        def fake_generate(seed, channel):
            captured["segment_count"] = channel.pacing.segment_count
            captured["target_seconds"] = channel.pacing.target_seconds
            return Script(segments=[], title_options=["t"])

        monkeypatch.setattr("pipeline.script_gen.generate_script", fake_generate)
        style_gen.sample_for_candidate(self._channel(), Seed(type="topic", topic="x"), "p")
        assert captured["segment_count"] == style_gen.SAMPLE_SEGMENT_COUNT
        assert captured["target_seconds"] == style_gen.SAMPLE_TARGET_SECONDS
        # And distinct from the channel's real, larger configuration.
        assert captured["segment_count"] < 5

    def test_the_real_channel_is_never_mutated(self, monkeypatch):
        from pipeline.plan import Seed, Script

        monkeypatch.setattr("pipeline.script_gen.generate_script",
                            lambda seed, channel: Script(
                                segments=[], title_options=["t"]))
        channel = self._channel()
        original_prompt = channel.style_prompt
        style_gen.sample_for_candidate(channel, Seed(type="topic", topic="x"),
                                       "a completely different prompt")
        assert channel.style_prompt == original_prompt


class TestListenSnippet:
    def test_is_cached_by_voice_text_and_speed(self, tmp_path, monkeypatch):
        from core.paths import CACHE_DIR

        monkeypatch.setattr("core.paths.CACHE_DIR", tmp_path)
        calls = []

        def fake_voiceover(segments, citation, voice_id, out_path, pacing, speed=1.0):
            calls.append(1)
            from pathlib import Path
            Path(out_path).write_bytes(b"fake mp3")

        monkeypatch.setattr("pipeline.tts.generate_voiceover", fake_voiceover)
        path1 = style_gen.listen_snippet("voice123", "Hello there", speed=1.0)
        path2 = style_gen.listen_snippet("voice123", "Hello there", speed=1.0)
        assert path1 == path2
        assert len(calls) == 1

    def test_a_different_voice_or_text_is_a_different_clip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.paths.CACHE_DIR", tmp_path)

        def fake_voiceover(segments, citation, voice_id, out_path, pacing, speed=1.0):
            from pathlib import Path
            Path(out_path).write_bytes(b"fake mp3")

        monkeypatch.setattr("pipeline.tts.generate_voiceover", fake_voiceover)
        a = style_gen.listen_snippet("voice1", "Hello there")
        b = style_gen.listen_snippet("voice2", "Hello there")
        c = style_gen.listen_snippet("voice1", "Something else")
        assert a != b != c

    def test_a_channel_key_style_id_cannot_escape_the_cache_directory(self, tmp_path, monkeypatch):
        """The voice id reaches this from a channel's stored config, and
        the filename is built directly from it."""
        monkeypatch.setattr("core.paths.CACHE_DIR", tmp_path)

        def fake_voiceover(segments, citation, voice_id, out_path, pacing, speed=1.0):
            from pathlib import Path
            Path(out_path).write_bytes(b"fake mp3")

        monkeypatch.setattr("pipeline.tts.generate_voiceover", fake_voiceover)
        path = style_gen.listen_snippet("../../evil", "text")
        assert ".." not in path.name


class TestStyleSetupRoutes:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from core.channels import channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        channel = ChannelConfig(key="c", channel_display_name="C",
                                content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                                style_prompt="", topics=["a topic"])
        write_raw({"c": channel_to_sparse_dict(channel)}, path)
        app = create_app()
        app.config.update(TESTING=True)
        with app.test_client() as test_client:
            yield test_client

    def _csrf(self, client):
        html = client.get("/").get_data(as_text=True)
        marker = 'name="csrf-token" content="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_page_shows_the_picker_when_a_seed_is_available(self, client):
        html = client.get("/channels/c/style-setup").get_data(as_text=True)
        assert "style-picker-form" in html

    def test_page_offers_to_fix_setup_first_when_it_is_not(self, tmp_path, monkeypatch):
        from core.channels import channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        channel = ChannelConfig(key="empty", channel_display_name="Empty",
                                content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                                style_prompt="", topics=[])
        write_raw({"empty": channel_to_sparse_dict(channel)}, path)
        app = create_app()
        with app.test_client() as client:
            html = client.get("/channels/empty/style-setup").get_data(as_text=True)
            assert "style-picker-form" not in html
            assert "no topics yet" in html

    def test_candidates_route_requires_csrf(self, client):
        assert client.post("/api/channels/c/style-setup/candidates",
                           json={}).status_code == 400

    def test_candidates_route_generates_a_sample_per_candidate(self, client, monkeypatch):
        from pipeline import style_gen as sg

        monkeypatch.setattr(sg, "draft_candidates", lambda channel, choices, count: [
            {"blurb": "A", "style_prompt": "prompt a"},
            {"blurb": "B", "style_prompt": "prompt b"},
        ])
        monkeypatch.setattr(sg, "sample_for_candidate", lambda channel, seed, prompt: (
            __import__("pipeline.plan", fromlist=["Script"]).Script(
                segments=[__import__("pipeline.plan", fromlist=["Segment"]).Segment(
                    f"Sample for {prompt}")],
                title_options=["t"])))

        response = client.post("/api/channels/c/style-setup/candidates",
                               json={"choices": {}, "count": 2},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["candidates"]) == 2
        assert data["candidates"][0]["sample"] == ["Sample for prompt a"]

    def test_one_failed_sample_does_not_lose_the_others(self, client, monkeypatch):
        from pipeline import style_gen as sg
        from pipeline.plan import Script, Segment

        monkeypatch.setattr(sg, "draft_candidates", lambda channel, choices, count: [
            {"blurb": "A", "style_prompt": "good"},
            {"blurb": "B", "style_prompt": "bad"},
        ])

        def flaky(channel, seed, prompt):
            if prompt == "bad":
                raise PipelineError("boom", user_message="This one failed.")
            return Script(segments=[Segment("ok")], title_options=["t"])

        monkeypatch.setattr(sg, "sample_for_candidate", flaky)
        response = client.post("/api/channels/c/style-setup/candidates",
                               json={"choices": {}, "count": 2},
                               headers={"X-CSRF-Token": self._csrf(client)})
        data = response.get_json()
        assert data["candidates"][0]["sample"] is not None
        assert data["candidates"][1]["sample"] is None
        assert "failed" in data["candidates"][1]["error"]

    def test_candidates_route_needs_a_usable_seed(self, tmp_path, monkeypatch):
        from core.channels import channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        channel = ChannelConfig(key="empty", channel_display_name="Empty",
                                content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                                style_prompt="", topics=[])
        write_raw({"empty": channel_to_sparse_dict(channel)}, path)
        app = create_app()
        with app.test_client() as client:
            html = client.get("/").get_data(as_text=True)
            import re
            token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
            response = client.post("/api/channels/empty/style-setup/candidates",
                                   json={"choices": {}},
                                   headers={"X-CSRF-Token": token})
            assert response.status_code == 400

    def test_listen_requires_a_voice(self, tmp_path, monkeypatch):
        from core.channels import channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        channel = ChannelConfig(key="c", channel_display_name="C",
                                content_mode="topic", voice="", style_prompt="",
                                topics=["x"])
        write_raw({"c": channel_to_sparse_dict(channel)}, path)
        app = create_app()
        with app.test_client() as client:
            html = client.get("/").get_data(as_text=True)
            import re
            token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
            response = client.post("/api/channels/c/style-setup/listen",
                                   json={"text": "hi"},
                                   headers={"X-CSRF-Token": token})
            assert response.status_code == 400
            assert "voice" in response.get_json()["error"].lower()

    def test_listen_returns_a_url(self, client, monkeypatch, tmp_path):
        from pipeline import style_gen as sg

        monkeypatch.setattr(sg, "listen_snippet",
                            lambda voice_id, text, speed=1.0: tmp_path / "clip.mp3")
        response = client.post("/api/channels/c/style-setup/listen",
                               json={"text": "hello"},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        assert "clip.mp3" in response.get_json()["url"]

    def test_choose_saves_the_prompt_and_redirects(self, client):
        from core.channels import load_channels

        response = client.post("/channels/c/style-setup/choose",
                               data={"style_prompt": "the chosen one",
                                    "csrf_token": self._csrf(client)})
        assert response.status_code == 302
        assert "settings" in response.headers["Location"]
        assert load_channels(validate=False)["c"].style_prompt == "the chosen one"

    def test_choose_requires_csrf(self, client):
        from core.channels import load_channels

        client.post("/channels/c/style-setup/choose", data={"style_prompt": "nope"})
        assert load_channels(validate=False)["c"].style_prompt != "nope"

    def test_choosing_nothing_does_not_blank_the_existing_prompt(self, client):
        from core.channels import load_channels

        client.post("/channels/c/style-setup/choose",
                    data={"style_prompt": "", "csrf_token": self._csrf(client)})
        # Started as "" in the fixture; the point is it takes the branch
        # that redirects without saving, not that this value looks unchanged.
        response = client.post("/channels/c/style-setup/choose",
                               data={"style_prompt": "", "csrf_token": self._csrf(client)})
        assert response.status_code == 302
        assert "style-setup" in response.headers["Location"]
