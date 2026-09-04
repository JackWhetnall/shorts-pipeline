"""
What happens when things go wrong.

Every test here is fully mocked. Nothing in this file makes a network
call or spends a cent — the fake responses below are the exact shapes the
SDK returns, constructed locally.

The reason this file exists: a real run died because a schema-constrained
call came back with a thinking block and no text block, and
`json.loads("")` raised a parse error for a response that was never JSON.
The schema guaranteed the shape of a completed answer and nothing about
whether the answer arrived. Every failure mode below is one that either
happened, or sits one step away from something that did.

The governing principle is that failure cost should be proportional to
what is recoverable. By the time footage matching runs, a script and a
voiceover have both been paid for; losing them because a scoring call
came back short is the most expensive possible response to a recoverable
problem.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.errors import ExternalServiceError, MissingCredentialError, PipelineError
from pipeline import llm


# --- fake SDK responses ------------------------------------------------

class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50,
                 cache_read_input_tokens=0, cache_creation_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class FakeBlock:
    def __init__(self, type_, text=None, thinking=None):
        self.type = type_
        self.text = text
        self.thinking = thinking


class FakeResponse:
    def __init__(self, content=None, stop_reason="end_turn", stop_details=None):
        self.content = content if content is not None else []
        self.stop_reason = stop_reason
        self.stop_details = stop_details
        self.usage = FakeUsage()


def text_response(payload: str) -> FakeResponse:
    return FakeResponse([FakeBlock("text", text=payload)])


def thinking_only_response() -> FakeResponse:
    """The exact failure that killed a real render: adaptive thinking
    consumed the entire max_tokens budget, so the response carries
    reasoning and no answer."""
    return FakeResponse([FakeBlock("thinking", thinking="...")],
                        stop_reason="max_tokens")


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}


@pytest.fixture
def no_cost_log(tmp_path, monkeypatch):
    """Keep test runs out of the real cost log."""
    monkeypatch.setattr("core.paths.COST_LOG_PATH", tmp_path / "costs.jsonl")
    monkeypatch.setattr("core.costs.COST_LOG_PATH", tmp_path / "costs.jsonl")


@pytest.fixture
def fake_client(monkeypatch, no_cost_log):
    """Replace the Anthropic client entirely. No key needed, no calls made."""
    client = MagicMock()
    monkeypatch.setattr(llm, "client", lambda: client)
    return client


# --- the bug that started this ----------------------------------------

class TestTruncatedResponses:
    def test_thinking_only_response_is_reported_as_truncation(self, fake_client):
        """Not as a JSON parse error.

        `json.loads("")` says "Expecting value: line 1 column 1", which
        sends you looking at the parser instead of the token budget."""
        fake_client.messages.create.return_value = thinking_only_response()

        with pytest.raises(llm.TruncatedResponse) as exc:
            llm.call_json("sys", "user", SCHEMA, operation="test")

        message = str(exc.value).lower()
        assert "ceiling" in message or "no text" in message
        assert "json" not in message

    def test_truncation_retries_once_with_a_larger_budget(self, fake_client):
        fake_client.messages.create.side_effect = [
            thinking_only_response(),
            text_response('{"ok": true}'),
        ]
        assert llm.call_json("sys", "user", SCHEMA, operation="test",
                             max_tokens=1000) == {"ok": True}

        budgets = [c.kwargs["max_tokens"] for c in fake_client.messages.create.call_args_list]
        assert budgets[0] == 1000
        assert budgets[1] > budgets[0], "the retry must actually ask for more room"

    def test_truncation_twice_gives_up_with_an_actionable_message(self, fake_client):
        fake_client.messages.create.return_value = thinking_only_response()
        with pytest.raises(llm.TruncatedResponse) as exc:
            llm.call_json("sys", "user", SCHEMA, operation="test")
        assert fake_client.messages.create.call_count == llm.MAX_ATTEMPTS
        assert "room" in exc.value.user_message.lower()

    def test_empty_text_block_is_treated_as_truncation(self, fake_client):
        # Finished cleanly, said nothing. Same cause, same fix.
        fake_client.messages.create.return_value = FakeResponse(
            [FakeBlock("text", text="   ")], stop_reason="end_turn")
        with pytest.raises(llm.TruncatedResponse):
            llm.call_json("sys", "user", SCHEMA, operation="test")

    def test_no_content_at_all_is_handled(self, fake_client):
        fake_client.messages.create.return_value = FakeResponse([])
        with pytest.raises(llm.TruncatedResponse):
            llm.call_json("sys", "user", SCHEMA, operation="test")


class TestResponseParsing:
    def test_a_thinking_block_before_the_text_is_ignored(self, fake_client):
        fake_client.messages.create.return_value = FakeResponse([
            FakeBlock("thinking", thinking="reasoning"),
            FakeBlock("text", text='{"ok": true}'),
        ])
        assert llm.call_json("sys", "user", SCHEMA, operation="test") == {"ok": True}

    def test_text_split_across_blocks_is_joined(self, fake_client):
        """Taking only the first text block would silently truncate."""
        fake_client.messages.create.return_value = FakeResponse([
            FakeBlock("text", text='{"ok"'),
            FakeBlock("text", text=": true}"),
        ])
        assert llm.call_json("sys", "user", SCHEMA, operation="test") == {"ok": True}

    def test_malformed_json_retries_then_reports_clearly(self, fake_client):
        fake_client.messages.create.return_value = text_response("not json at all")
        with pytest.raises(ExternalServiceError) as exc:
            llm.call_json("sys", "user", SCHEMA, operation="test")
        assert fake_client.messages.create.call_count == llm.MAX_ATTEMPTS
        assert "malformed" in exc.value.user_message.lower()

    def test_malformed_then_valid_succeeds(self, fake_client):
        fake_client.messages.create.side_effect = [
            text_response("oops"),
            text_response('{"ok": false}'),
        ]
        assert llm.call_json("sys", "user", SCHEMA, operation="test") == {"ok": False}


class TestRefusal:
    def test_a_refusal_is_not_retried(self, fake_client):
        """Retrying identical input gets an identical refusal and costs
        twice as much."""
        details = MagicMock()
        details.category = "cyber"
        fake_client.messages.create.return_value = FakeResponse(
            [], stop_reason="refusal", stop_details=details)

        with pytest.raises(llm.RefusedResponse):
            llm.call_json("sys", "user", SCHEMA, operation="test")
        assert fake_client.messages.create.call_count == 1

    def test_refusal_suggests_rerolling(self, fake_client):
        fake_client.messages.create.return_value = FakeResponse(
            [], stop_reason="refusal")
        with pytest.raises(llm.RefusedResponse) as exc:
            llm.call_json("sys", "user", SCHEMA, operation="test")
        assert "reroll" in exc.value.user_message.lower()


class TestApiErrors:
    @pytest.mark.parametrize("status,expected", [
        (429, "limiting"),
        (401, "rejected"),
        (403, "rejected"),
        (400, "bug in the pipeline"),
        (500, "their end"),
        (503, "their end"),
    ])
    def test_status_codes_become_plain_english(self, fake_client, status, expected):
        error = Exception("raw sdk text")
        error.status_code = status
        fake_client.messages.create.side_effect = error

        with pytest.raises(ExternalServiceError) as exc:
            llm.call_json("sys", "user", SCHEMA, operation="test")
        assert expected in exc.value.user_message.lower()

    def test_no_message_ever_leaks_a_traceback_or_path(self, fake_client):
        error = Exception(r"C:\Users\JackW\secret\path.py line 42")
        error.status_code = 500
        fake_client.messages.create.side_effect = error
        with pytest.raises(ExternalServiceError) as exc:
            llm.call_json("sys", "user", SCHEMA, operation="test")
        assert "C:\\" not in exc.value.user_message
        assert ".py" not in exc.value.user_message

    def test_missing_key_names_the_variable(self, monkeypatch, no_cost_log):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(llm, "_client", None)
        with pytest.raises(MissingCredentialError) as exc:
            llm.client()
        assert "ANTHROPIC_API_KEY" in exc.value.user_message


class TestVisionCalls:
    def test_an_empty_description_is_never_returned(self, fake_client):
        """An empty description written into the library would poison
        every future match for that clip, silently and permanently."""
        fake_client.messages.create.return_value = thinking_only_response()
        with pytest.raises(llm.TruncatedResponse):
            llm.call_vision("describe", [("image/jpeg", "xxx")], operation="describe_clip")

    def test_a_good_description_comes_back_normalised(self, fake_client):
        fake_client.messages.create.return_value = text_response(
            "  A candle\n  burning   in a dark room.  ")
        assert llm.call_vision("d", [("image/jpeg", "x")], operation="describe_clip") \
            == "A candle burning in a dark room."

    def test_the_budget_leaves_room_for_thinking(self):
        # 250 tokens was the original value; adaptive thinking consumes
        # that entirely and returns nothing.
        assert llm.VISION_MAX_TOKENS >= 1000


class TestBudgetsAreSane:
    """Guards against the exact regression: budgets too small for
    thinking plus an answer."""

    def test_default_json_budget_is_generous(self):
        assert llm.DEFAULT_MAX_TOKENS >= 4000

    def test_footage_matching_has_the_largest_budget(self):
        from pipeline.footage.library import MATCH_MAX_TOKENS
        assert MATCH_MAX_TOKENS >= 8000, "the most demanding call needs the most room"

    def test_effort_is_set_so_thinking_is_bounded(self):
        assert llm.DEFAULT_EFFORT in ("low", "medium", "high", "xhigh", "max")


# --- footage matching degrades rather than dying ----------------------

class TestFootageDegradation:
    """A render reaching the footage stage has already paid for a script
    and a voiceover. Those must survive a failure here."""

    @pytest.fixture
    def segments(self):
        from pipeline.plan import Segment
        return [
            Segment(text="a line", shot_brief="a candle in a dark room",
                    keywords=["candle"], start=0, end=5),
            Segment(text="another", shot_brief="an empty road at dusk",
                    keywords=["road"], start=5, end=10),
        ]

    @pytest.fixture
    def stocked_library(self, tmp_path, monkeypatch):
        """A small real SQLite library in a temp directory."""
        from pipeline.footage import store
        db = tmp_path / "library.db"
        library_dir = tmp_path / "library"
        library_dir.mkdir()
        monkeypatch.setattr("core.paths.LIBRARY_DB_PATH", db)
        monkeypatch.setattr("pipeline.footage.store.LIBRARY_DB_PATH", db)
        monkeypatch.setattr("pipeline.footage.store.LIBRARY_DIR", library_dir)
        monkeypatch.setattr("pipeline.footage.library.LIBRARY_DIR", library_dir)

        for i in range(8):
            (library_dir / f"clip{i}.mp4").write_bytes(b"x")
            store.upsert(store.Clip(
                filename=f"clip{i}.mp4",
                description=f"a candle burning on a road at dusk, take {i}",
                duration=5.0, frame_hashes=[i, i, i]), db_path=db)
        return db

    def _patch_db(self, monkeypatch, db):
        import pipeline.footage.retrieval as retrieval
        import pipeline.footage.store as store
        real_connect = store.connect
        monkeypatch.setattr(store, "connect",
                            lambda p=None: real_connect(p or db))
        monkeypatch.setattr(retrieval.store, "connect",
                            lambda p=None: real_connect(p or db))

    @pytest.mark.parametrize("failure", [
        llm.TruncatedResponse("cut short"),
        llm.RefusedResponse("declined"),
        ExternalServiceError("The AI service (Claude)", "boom"),
    ])
    def test_a_failed_scoring_call_still_produces_picks(
            self, segments, stocked_library, monkeypatch, failure):
        from pipeline.footage import library
        self._patch_db(monkeypatch, stocked_library)

        with patch.object(library.llm, "call_json", side_effect=failure):
            outcome = library.assign_clips(segments, [2, 2], [])

        assert [len(p) for p in outcome.picks] == [2, 2]
        assert outcome.degraded is True, "the video must say it wasn't scored"

    def test_degraded_picks_are_still_distinct(
            self, segments, stocked_library, monkeypatch):
        from pipeline.footage import library
        self._patch_db(monkeypatch, stocked_library)

        with patch.object(library.llm, "call_json",
                          side_effect=llm.TruncatedResponse("cut short")):
            outcome = library.assign_clips(segments, [2, 2], [])

        flat = [name for group in outcome.picks for name in group]
        assert len(flat) == len(set(flat)), "a clip must not repeat within one video"

    def test_an_empty_library_says_so_plainly(self, tmp_path, monkeypatch, segments):
        from pipeline.footage import library, store
        db = tmp_path / "empty.db"
        monkeypatch.setattr("pipeline.footage.store.LIBRARY_DB_PATH", db)
        real_connect = store.connect
        monkeypatch.setattr(store, "connect", lambda p=None: real_connect(p or db))

        from core.errors import FootageLibraryError
        with pytest.raises(FootageLibraryError) as exc:
            library.assign_clips(segments, [1, 1], [])
        assert "no clips" in exc.value.user_message.lower()

    def test_an_avoid_list_that_excludes_everything_says_so(
            self, segments, stocked_library, monkeypatch):
        from core.errors import FootageLibraryError
        from pipeline.footage import library
        self._patch_db(monkeypatch, stocked_library)

        with pytest.raises(FootageLibraryError) as exc:
            # Every clip description contains "candle".
            library.assign_clips(segments, [1, 1], ["candle"])
        assert "avoid" in exc.value.user_message.lower()


# --- render-time guards ------------------------------------------------

class TestMissingClipFiles:
    """The database and the directory can disagree — a file deleted by
    hand, a partially restored backup. Discovering that inside moviepy a
    minute into the encode is the worst place to find out."""

    def test_a_missing_file_is_substituted_and_flagged(self, tmp_path, monkeypatch):
        from pipeline import assemble
        from pipeline.footage import store
        from pipeline.plan import RenderPlan, Seed, Shot
        from core.channels import ChannelConfig

        library_dir = tmp_path / "library"
        library_dir.mkdir()
        db = tmp_path / "library.db"
        monkeypatch.setattr("pipeline.footage.store.LIBRARY_DIR", library_dir)
        monkeypatch.setattr("pipeline.footage.store.LIBRARY_DB_PATH", db)
        real_connect = store.connect
        monkeypatch.setattr(store, "connect", lambda p=None: real_connect(p or db))

        (library_dir / "present.mp4").write_bytes(b"x")
        store.upsert(store.Clip(filename="present.mp4", description="a real clip",
                                duration=5.0), db_path=db)

        plan = RenderPlan(
            channel=ChannelConfig(key="t", voice="v", style_prompt="p",
                                  content_mode="topic", topics=["x"]),
            seed=Seed(type="topic", topic="x"))
        plan.shots = [Shot(start=0, end=2, segment_index=0,
                           clip_path=library_dir / "gone.mp4")]

        assemble._replace_missing_clips(plan)

        assert plan.shots[0].clip_path.name == "present.mp4"
        assert plan.shots[0].clip_path.exists()
        assert plan.footage_degraded is True

    def test_nothing_happens_when_every_file_is_present(self, tmp_path, monkeypatch):
        from pipeline import assemble
        from pipeline.plan import RenderPlan, Seed, Shot
        from core.channels import ChannelConfig

        clip = tmp_path / "here.mp4"
        clip.write_bytes(b"x")
        plan = RenderPlan(
            channel=ChannelConfig(key="t", voice="v", style_prompt="p",
                                  content_mode="topic", topics=["x"]),
            seed=Seed(type="topic", topic="x"))
        plan.shots = [Shot(start=0, end=2, segment_index=0, clip_path=clip)]

        assemble._replace_missing_clips(plan)
        assert plan.shots[0].clip_path == clip
        assert plan.footage_degraded is False


# --- the transcript check must never cost a render --------------------

class TestWhisperDegradation:
    def test_an_unloadable_model_disables_the_check(self, monkeypatch):
        from pipeline import tts
        monkeypatch.setattr(tts, "_whisper_model", None)
        monkeypatch.setattr(tts, "_whisper_unavailable", False)

        with patch.dict("sys.modules", {"faster_whisper": None}):
            assert tts._get_whisper() is None
        assert tts._whisper_unavailable is True

    def test_an_unavailable_check_reports_a_pass(self, monkeypatch):
        """Not a failure. Retrying synthesis against a check that cannot
        run would triple the bill and prove nothing."""
        from pipeline import tts
        monkeypatch.setattr(tts, "_get_whisper", lambda: None)
        assert tts.transcript_match_ratio("anything", "nofile.mp3") == 1.0

    def test_a_check_that_throws_reports_a_pass(self, monkeypatch):
        from pipeline import tts
        model = MagicMock()
        model.transcribe.side_effect = RuntimeError("cuda exploded")
        monkeypatch.setattr(tts, "_get_whisper", lambda: model)
        assert tts.transcript_match_ratio("anything", "nofile.mp3") == 1.0

    def test_the_failure_is_only_reported_once(self, monkeypatch):
        from pipeline import tts
        monkeypatch.setattr(tts, "_whisper_model", None)
        monkeypatch.setattr(tts, "_whisper_unavailable", True)
        # Already known-unavailable: must short-circuit without retrying
        # an import that takes seconds to fail.
        with patch("builtins.__import__", side_effect=AssertionError("should not import")):
            assert tts._get_whisper() is None


# --- script generation -------------------------------------------------

class TestScriptGenerationFailures:
    def _channel(self):
        from core.channels import ChannelConfig
        return ChannelConfig(key="t", voice="v", style_prompt="p",
                             content_mode="topic", topics=["x"])

    def test_an_empty_script_is_rejected(self, fake_client):
        from pipeline.plan import Seed
        from pipeline.script_gen import generate_script
        fake_client.messages.create.return_value = text_response(
            '{"segments": [], "title_options": [], "description_body": ""}')
        with pytest.raises(PipelineError) as exc:
            generate_script(Seed(type="topic", topic="x"), self._channel())
        assert "empty" in exc.value.user_message.lower()

    def test_a_wrong_segment_count_still_produces_a_video(self, fake_client):
        """Warns rather than failing: a count mismatch changes pacing but
        the video is still usable, and the script is already paid for."""
        from pipeline.plan import Seed
        from pipeline.script_gen import generate_script
        fake_client.messages.create.return_value = text_response(
            '{"segments": [{"text": "one", "shot_brief": "a road", "keywords": ["road"]}],'
            ' "title_options": ["A Title"], "description_body": "Body."}')
        script = generate_script(Seed(type="topic", topic="x"), self._channel())
        assert len(script.segments) == 1

    def test_missing_optional_fields_do_not_crash(self, fake_client):
        from pipeline.plan import Seed
        from pipeline.script_gen import generate_script
        fake_client.messages.create.return_value = text_response(
            '{"segments": [{"text": "one", "shot_brief": "", "keywords": []}],'
            ' "title_options": [], "description_body": ""}')
        script = generate_script(Seed(type="topic", topic="x"), self._channel())
        assert script.title == ""
        # No brief: matching falls back to the spoken line rather than
        # having nothing to search on.
        assert script.segments[0].visual_text == "one"

    def test_an_unknown_seed_type_is_caught(self):
        from pipeline.plan import Seed
        from pipeline.script_gen import generate_script
        with pytest.raises(PipelineError):
            generate_script(Seed(type="nonsense"), self._channel())


# --- request shapes, checked against the SDK's own types --------------

class TestRequestShapeIsValid:
    """Catch a malformed request here rather than as a 400 in production.

    Two failures of exactly this kind have already reached a real run: a
    schema carrying `minItems`, which the API rejects outright, and a
    token budget too small for thinking plus an answer. Both were
    invisible until a video died. The SDK ships generated TypedDicts
    describing what the API accepts, so the request can be checked
    against them locally, for free.
    """

    def _output_config_keys(self):
        from anthropic.types.output_config_param import OutputConfigParam
        return set(OutputConfigParam.__annotations__)

    def _effort_values(self):
        """The effort levels the installed SDK declares.

        Resolved with get_type_hints rather than reading __annotations__:
        the SDK's generated modules use `from __future__ import
        annotations`, so the raw annotations are strings and
        typing.get_args on them returns nothing.
        """
        import typing
        from anthropic.types.output_config_param import OutputConfigParam

        hints = typing.get_type_hints(OutputConfigParam)
        for arg in typing.get_args(hints["effort"]):
            values = typing.get_args(arg)      # Optional[Literal[...]]
            if values:
                return set(values)
        return set()

    def test_every_effort_level_used_is_one_the_api_accepts(self):
        from pipeline.footage.library import MATCH_EFFORT
        allowed = self._effort_values()
        assert allowed, "couldn't read the SDK's effort values"
        assert llm.DEFAULT_EFFORT in allowed
        assert MATCH_EFFORT in allowed

    def test_output_config_carries_only_supported_keys(self, fake_client):
        fake_client.messages.create.return_value = text_response('{"ok": true}')
        llm.call_json("sys", "user", SCHEMA, operation="test")

        sent = fake_client.messages.create.call_args.kwargs["output_config"]
        assert set(sent) <= self._output_config_keys(), (
            f"unsupported output_config keys: {set(sent) - self._output_config_keys()}")

    def test_the_format_block_matches_the_sdk_type(self, fake_client):
        from anthropic.types.json_output_format_param import JSONOutputFormatParam
        fake_client.messages.create.return_value = text_response('{"ok": true}')
        llm.call_json("sys", "user", SCHEMA, operation="test")

        fmt = fake_client.messages.create.call_args.kwargs["output_config"]["format"]
        assert set(fmt) <= set(JSONOutputFormatParam.__annotations__)
        assert fmt["type"] == "json_schema"

    @pytest.mark.parametrize("build", [
        lambda: __import__("pipeline.script_gen", fromlist=["x"])._segments_schema(),
        lambda: __import__("pipeline.script_gen", fromlist=["x"])._segments_schema(
            extra=__import__("pipeline.script_gen", fromlist=["x"]).QUOTE_SCHEMA_EXTRA),
        lambda: __import__("pipeline.footage.library", fromlist=["x"]).MATCH_SCHEMA,
    ])
    def test_no_schema_uses_a_keyword_the_api_rejects(self, build):
        """`minItems: 3` returns a 400 — array bounds other than 0 or 1
        are not supported. This shipped and broke every generation."""
        unsupported = []

        def walk(node, path="$"):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("minItems", "maxItems") and value not in (0, 1):
                        unsupported.append(f"{path}.{key}={value}")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for i, item in enumerate(node):
                    walk(item, f"{path}[{i}]")

        walk(build())
        assert not unsupported, f"schema uses unsupported keywords: {unsupported}"

    def test_system_blocks_render_as_the_api_expects(self):
        big = "x" * (llm.MIN_CACHEABLE_CHARS + 10)
        rendered = llm._render_system([
            llm.SystemBlock(big, cacheable=True),
            llm.SystemBlock("volatile part"),
        ])
        assert all(set(b) <= {"type", "text", "cache_control"} for b in rendered)
        assert rendered[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in rendered[1], "the volatile block must not be cached"

    def test_a_short_block_is_not_marked_cacheable(self):
        # Below the minimum the marker does nothing, so claiming it would
        # be misleading.
        rendered = llm._render_system([llm.SystemBlock("tiny", cacheable=True)])
        assert "cache_control" not in rendered[0]


class TestPurgingDiscardedVideos:
    """Deleting output is the one operation here that cannot be undone,
    so its refusals matter more than its successes."""

    @pytest.fixture
    def video(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.gallery.DISCARD_HISTORY_PATH",
                            tmp_path / "discard_history.jsonl")
        path = tmp_path / "john_3_16.mp4"
        path.write_bytes(b"video")
        for suffix in ("audio.mp3", "meta.txt", "publish.json", "thumb.jpg"):
            (tmp_path / f"john_3_16_{suffix}").write_text("x")
        return path

    def test_refuses_a_video_that_is_not_discarded(self, video):
        from core import gallery

        with pytest.raises(ValueError):
            gallery.purge(video)
        assert video.exists()

    def test_refuses_a_published_video(self, video):
        from core import gallery

        gallery.save_publish_info(video, {"youtube_url": "https://y/1"})
        with pytest.raises(ValueError):
            gallery.purge(video)
        assert video.exists()

    def test_removes_the_video_and_its_sidecars(self, video):
        from core import gallery

        gallery.set_discarded(video, True, "footage")
        result = gallery.purge(video, "test_channel")

        assert not video.exists()
        assert list(video.parent.glob("john_3_16*")) == []
        assert result["files"] == 5
        assert result["bytes"] > 0

    def test_keeps_a_tombstone_so_the_statistics_survive(self, video):
        """The point of the whole design: a purge must not make the
        discard rate look better than it was."""
        from core import gallery

        gallery.set_discarded(video, True, "footage")
        gallery.purge(video, "test_channel")

        records = gallery.purged_records("test_channel")
        assert len(records) == 1
        assert records[0]["stem"] == "john_3_16"
        assert records[0]["discard_reason"] == "footage"

    def test_a_stem_that_prefixes_another_is_not_swept_up(self, video):
        """`john_3_1` is a prefix of `john_3_16`. A glob on the stem would
        take the wrong video's files with it."""
        from core import gallery

        neighbour = video.parent / "john_3_1.mp4"
        neighbour.write_bytes(b"other")
        (video.parent / "john_3_1_audio.mp3").write_text("x")

        gallery.set_discarded(neighbour, True, "script")
        gallery.purge(neighbour, "test_channel")

        assert video.exists()
        assert (video.parent / "john_3_16_audio.mp3").exists()

    def test_corrupt_history_costs_a_statistic_not_a_crash(self, video, tmp_path):
        from core import gallery

        gallery.set_discarded(video, True, "footage")
        gallery.purge(video, "test_channel")
        path = tmp_path / "discard_history.jsonl"
        path.write_text(path.read_text() + "{not json\n")

        assert len(gallery.purged_records()) == 1

    def test_purged_videos_still_count_toward_the_discard_rate(self, monkeypatch, tmp_path):
        from core import gallery, insights
        from core.channels import ChannelConfig

        monkeypatch.setattr(gallery, "purged_records",
                            lambda key=None: [{"channel": "c", "stem": "a",
                                               "discard_reason": "footage"}] * 3)
        # A channel that still exists but whose output directory is gone:
        # every video it made was discarded and then deleted.
        channel = ChannelConfig(key="c", channel_display_name="C", voice="v",
                                style_prompt="p", content_mode="topic", topics=["x"])
        channel.output_dir = str(tmp_path / "nothing_here")
        monkeypatch.setattr(insights, "load_channels", lambda validate=True: {"c": channel})

        data = insights.collect()
        assert data["totals"]["total"] == 3
        assert data["totals"]["discard_rate"] == 1.0
        assert data["discard_reasons"]["rows"][0]["id"] == "footage"


class TestOrphanDetection:
    def test_finds_audio_with_no_video(self, tmp_path):
        from core import gallery

        (tmp_path / "kept.mp4").write_bytes(b"v")
        (tmp_path / "kept_audio.mp3").write_text("x")
        (tmp_path / "crashed_audio_seg0.mp3").write_text("x")
        (tmp_path / "crashed_audio_seg1.mp3").write_text("x")

        orphans = [p.name for p in gallery.orphaned_files(str(tmp_path))]
        assert orphans == ["crashed_audio_seg0.mp3", "crashed_audio_seg1.mp3"]

    def test_no_output_directory_is_not_an_error(self, tmp_path):
        from core import gallery
        assert gallery.orphaned_files(str(tmp_path / "nope")) == []
