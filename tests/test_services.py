"""
`core.services`: which APIs are set up and what they have cost.

The page exists because the only way to find out a key had lapsed was a
render failing halfway through, and because `core.costs` could answer
"was that video expensive" but never "is the ElevenLabs account about to
run dry".

The thing most worth pinning down here is what this page is careful NOT
to claim. It shows spend, never a balance — no provider gives one to an
ordinary API key, and a "$0.00" beside a service this project never bills
through would read as a measurement rather than as "there is nothing to
measure".
"""

from __future__ import annotations

import json
import time

import pytest

from core import services


@pytest.fixture
def cost_log(tmp_path, monkeypatch):
    path = tmp_path / "cost_log.jsonl"
    monkeypatch.setattr("core.paths.COST_LOG_PATH", path)
    monkeypatch.setattr("core.costs.COST_LOG_PATH", path)
    return path


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def _record(service, cost, ago_days=0, operation="script"):
    return {"ts": time.time() - ago_days * 86400, "service": service,
            "operation": operation, "model": "m", "cost_usd": cost}


class TestSpend:
    def test_each_service_gets_its_own_calls(self, cost_log):
        _write(cost_log, [_record("claude", 1.0), _record("elevenlabs", 0.25),
                          _record("openai-image", 0.5)])
        rows = {r["key"]: r for r in services.collect()["services"]}
        assert rows["anthropic"]["total_usd"] == 1.0
        assert rows["elevenlabs"]["total_usd"] == 0.25
        assert rows["openai"]["total_usd"] == 0.5

    def test_a_service_this_app_never_bills_through_shows_nothing_not_zero(self, cost_log):
        """"$0.00" beside Pexels reads as a measurement. There is nothing
        to measure: the account is free and no call is ever billed to it."""
        _write(cost_log, [_record("claude", 1.0)])
        rows = {r["key"]: r for r in services.collect()["services"]}
        assert rows["pexels"]["total_usd"] is None
        assert rows["youtube"]["total_usd"] is None

    def test_the_recent_window_excludes_older_calls(self, cost_log):
        _write(cost_log, [_record("claude", 1.0, ago_days=2),
                          _record("claude", 9.0, ago_days=services.RECENT_WINDOW_DAYS + 5)])
        data = services.collect()
        rows = {r["key"]: r for r in data["services"]}
        assert rows["anthropic"]["recent_usd"] == 1.0
        assert rows["anthropic"]["total_usd"] == 10.0

    def test_totals_add_up_across_services(self, cost_log):
        _write(cost_log, [_record("claude", 1.0), _record("elevenlabs", 0.5)])
        assert services.collect()["total_usd"] == 1.5

    def test_no_cost_log_is_zero_rather_than_an_error(self, cost_log):
        assert services.collect()["total_usd"] == 0.0


class TestConfigured:
    def test_a_set_key_reads_as_set_up(self, cost_log, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-whatever")
        rows = {r["key"]: r for r in services.collect()["services"]}
        assert rows["anthropic"]["configured"] is True
        assert "Anthropic" not in services.collect()["missing"]

    def test_whitespace_is_not_a_key(self, cost_log, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
        rows = {r["key"]: r for r in services.collect()["services"]}
        assert rows["anthropic"]["configured"] is False

    def test_an_unset_key_is_named_in_missing(self, cost_log, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        assert "ElevenLabs" in services.collect()["missing"]

    def test_youtube_is_read_from_its_own_credentials_not_an_env_var(
            self, cost_log, monkeypatch):
        """It is the one service configured by a file rather than an
        environment variable, so it needs its own check."""
        monkeypatch.setattr("core.youtube.CLIENT_PATH", cost_log.parent / "nope.json")
        monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
        monkeypatch.delenv("YOUTUBE_CLIENT_SECRET", raising=False)
        rows = {r["key"]: r for r in services.collect()["services"]}
        assert rows["youtube"]["env_var"] is None
        assert rows["youtube"]["configured"] is False

        monkeypatch.setenv("YOUTUBE_CLIENT_ID", "id")
        monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "secret")
        rows = {r["key"]: r for r in services.collect()["services"]}
        assert rows["youtube"]["configured"] is True


class TestEveryServiceIsUsable:
    def test_every_service_names_somewhere_to_go(self):
        """The entire point of the page is the link — nobody opens it to
        read a status word."""
        for service in services.SERVICES:
            assert service.dashboard_url.startswith("https://")
            assert service.dashboard_label
            assert service.what_for

    def test_every_cost_service_name_is_one_costs_actually_writes(self, cost_log):
        """A typo in `cost_services` would show $0.00 forever, which is the
        one failure this page cannot afford — an API key that has quietly
        gone unused looks exactly the same.

        Checked against what `core.costs` really writes, by making it
        write one of each, rather than against a list restated here that
        could drift the same way."""
        from core import costs

        class _Usage:
            input_tokens = output_tokens = 1
            cache_read_input_tokens = cache_creation_input_tokens = 0

        costs.record_claude("script", "claude-sonnet-5", _Usage())
        costs.record_elevenlabs("tts", "eleven", 10)
        costs.record_openai_images("logo", "gpt-image-1", 1, "low")

        written = {r["service"] for r in costs.read_records()}
        for service in services.SERVICES:
            assert set(service.cost_services) <= written
