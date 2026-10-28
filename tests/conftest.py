from __future__ import annotations

from urllib.parse import urlparse

import pytest
import requests


class LiveCallInTest(AssertionError):
    """A test reached a paid service. Mock the call instead."""


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@pytest.fixture(autouse=True)
def _no_paid_api_calls(tmp_path, monkeypatch):
    """No test may spend money. The owner's keys are set in the shell the
    suite runs from, so a test that forgets to mock a call would bill the
    real account - Claude, OpenAI, ElevenLabs or fal - and nothing would
    say so.

    Blocked at the two seams every paid call passes through: the
    Anthropic client `llm.client` builds, and `requests` for everything
    else. Tests that mock either
    (`monkeypatch.setattr(llm, "client", ...)`, `module.requests`) patch
    after this and so replace it; anything that slips through fails
    loudly instead. The cost log goes to a temporary file too, so a test
    that records a fake cost doesn't land on the real spend report.
    """
    from pipeline import llm

    def refuse_claude(*args, **kwargs):
        raise LiveCallInTest("a test tried to call Claude - mock llm.call_json or llm.client")

    # The SDK constructor rather than llm.client, so the key check in
    # client() still runs (and is itself tested).
    monkeypatch.setattr(llm, "Anthropic", refuse_claude)
    monkeypatch.setattr(llm, "_client", None)

    real_request = requests.sessions.Session.request

    def local_only(self, method, url, *args, **kwargs):
        if urlparse(str(url)).hostname not in _LOCAL_HOSTS:
            raise LiveCallInTest(f"a test made a real HTTP request: {method} {url}")
        return real_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "request", local_only)
    monkeypatch.setattr("core.costs.COST_LOG_PATH", tmp_path / "cost_log.jsonl")


@pytest.fixture(autouse=True)
def _no_live_voice_quota(monkeypatch, tmp_path):
    """The quota check reads ElevenLabs over the network whenever a key is
    set, and plenty of tests set a fake one. Unknown is the check's
    allow-everything answer, so this keeps every other test exactly as it
    was; tests of the quota itself patch `_read` again."""
    from core import voice_quota
    monkeypatch.setattr(voice_quota, "_read", lambda: None)
    monkeypatch.setattr(voice_quota, "_cached", None)
    # Likewise the credits a character costs (read from ElevenLabs' history):
    # a character is a credit unless a test says otherwise.
    monkeypatch.setattr(voice_quota, "_read_ratio", lambda: None)
    monkeypatch.setattr(voice_quota, "_ratio", None)
    monkeypatch.setattr(voice_quota, "RATIO_PATH", tmp_path / "voice_credit_ratio.json")
    monkeypatch.setattr(voice_quota, "LAST_PATH", tmp_path / "voice_quota_last.json")


@pytest.fixture(autouse=True)
def _isolated_script_history(tmp_path, monkeypatch):
    """The script stage checks originality against the channel's script
    history, so any test that runs it would otherwise read (and a full
    render would write) this installation's real history."""
    monkeypatch.setattr("pipeline.similarity.SCRIPT_HISTORY_PATH",
                        tmp_path / "script_history.json")
    # And a quiz channel's question bank (pipeline.quiz).
    monkeypatch.setattr("pipeline.quiz.QUESTION_BANK_DIR", tmp_path / "question_banks")
    # And the fact store (pipeline.facts): empty unless a test fills it.
    monkeypatch.setattr("pipeline.facts.store.DB_PATH", tmp_path / "facts.db")
    # And the question bank's budget (pipeline.facts.budget): the default
    # unless a test sets one.
    monkeypatch.setattr("pipeline.facts.budget.LIMIT_PATH", tmp_path / "question_bank_budget.json")
    # And the Money page's settings and voice readings (core.money).
    monkeypatch.setattr("core.money.SETTINGS_PATH", tmp_path / "money.json")
    monkeypatch.setattr("core.money.VOICE_HISTORY_PATH", tmp_path / "voice_usage.json")


@pytest.fixture(autouse=True)
def _isolated_ready_to_post(tmp_path, monkeypatch):
    """Publishing puts a video in the owner's Videos\Shorts to post folder
    (core.posting.stage); no test may touch the real one."""
    monkeypatch.setattr("core.posting.READY_DIR", tmp_path / "ready_to_post")
    monkeypatch.setattr("core.posting.PHONE_DIR", tmp_path / "phone_to_post")
    monkeypatch.setattr("core.posting.PHONE_INDEX", tmp_path / "phone_posts.json")
    monkeypatch.setattr("core.posting.STAGED_INDEX", tmp_path / "staged_posts.json")


@pytest.fixture(autouse=True)
def _isolated_instagram(tmp_path, monkeypatch):
    """Instagram's Meta app and account tokens (core.instagram) are real
    credentials: no test reads or writes the real ones, and none sees an
    account the owner connected."""
    monkeypatch.setattr("core.instagram.PATH", tmp_path / "instagram.json")
    monkeypatch.setattr("core.instagram.READY_DIR", tmp_path / "instagram_ready")
    monkeypatch.delenv("META_APP_ID", raising=False)
    monkeypatch.delenv("META_APP_SECRET", raising=False)
