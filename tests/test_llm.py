"""
`pipeline.llm`: the one place this project talks to Claude.

Covers a real crash found while building batch script generation: a
`max_tokens` large enough to need streaming (or a truncation retry that
multiplies one up to that point) makes the SDK itself raise a plain
`ValueError` before any request is even sent — no `status_code`, so
`_as_service_error`'s HTTP-status branches never matched it and it
escaped as a raw exception with no `user_message`, violating this
project's own convention that every failure is a `PipelineError`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.errors import PipelineError
from pipeline import llm


class FakeUsage:
    input_tokens = 100
    output_tokens = 200
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [FakeBlock(text)]
        self.stop_reason = stop_reason
        self.stop_details = None
        self.usage = FakeUsage()


@pytest.fixture(autouse=True)
def _cost_log(tmp_path, monkeypatch):
    monkeypatch.setattr("core.paths.COST_LOG_PATH", tmp_path / "costs.jsonl")
    monkeypatch.setattr("core.costs.COST_LOG_PATH", tmp_path / "costs.jsonl")


class TestNonstreamingCeiling:
    def test_an_oversized_budget_is_clamped_before_the_call(self, monkeypatch):
        captured = {}

        def fake_create(**kwargs):
            captured["max_tokens"] = kwargs["max_tokens"]
            return FakeResponse('{"a": 1}')

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        monkeypatch.setattr(llm, "client", lambda: client)

        llm.call_json("system", "user", {"type": "object"}, operation="x",
                      max_tokens=999_999)
        assert captured["max_tokens"] == llm.MAX_NONSTREAMING_TOKENS

    def test_a_truncation_retry_is_also_clamped(self, monkeypatch):
        seen = []

        def fake_create(**kwargs):
            seen.append(kwargs["max_tokens"])
            return FakeResponse("", stop_reason="max_tokens")

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        monkeypatch.setattr(llm, "client", lambda: client)

        with pytest.raises(llm.TruncatedResponse):
            llm.call_json("system", "user", {"type": "object"}, operation="x",
                          max_tokens=15_000)
        assert seen[0] == 15_000
        # 15,000 * TRUNCATION_RETRY_MULTIPLIER (3) would be 45,000 - clamped
        assert seen[1] == llm.MAX_NONSTREAMING_TOKENS

    def test_a_normal_budget_is_left_alone(self, monkeypatch):
        captured = {}

        def fake_create(**kwargs):
            captured["max_tokens"] = kwargs["max_tokens"]
            return FakeResponse('{"a": 1}')

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        monkeypatch.setattr(llm, "client", lambda: client)

        llm.call_json("system", "user", {"type": "object"}, operation="x",
                      max_tokens=2500)
        assert captured["max_tokens"] == 2500


class TestServiceErrorWrapping:
    def test_an_sdk_side_valueerror_becomes_a_pipeline_error(self, monkeypatch):
        """The exact failure this project hit: `client().messages.create`
        raising client-side, before any HTTP response exists at all."""
        def explode(**kwargs):
            raise ValueError("Streaming is required for operations that may "
                             "take longer than 10 minutes.")

        client = MagicMock()
        client.messages.create.side_effect = explode
        monkeypatch.setattr(llm, "client", lambda: client)

        with pytest.raises(PipelineError) as caught:
            llm.call_json("system", "user", {"type": "object"}, operation="x",
                          max_tokens=2500)
        assert caught.value.user_message

    def test_a_pipelineerror_passes_through_unwrapped(self):
        original = PipelineError("boom", user_message="told you")
        assert llm._as_service_error(original) is original

    def test_a_recognised_http_status_still_gets_its_specific_message(self):
        class FakeHttpError(Exception):
            status_code = 429

        wrapped = llm._as_service_error(FakeHttpError("rate limited"))
        assert isinstance(wrapped, PipelineError)
        assert "temporarily limiting" in wrapped.user_message
