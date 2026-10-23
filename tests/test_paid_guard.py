"""
No paid call outside the project's own programs (decision 132). The owner,
23 Oct: "real API usage and voice credits should never be spent on testing,
ever." 10,785 voice credits had gone on voiceovers run by hand from one-off
scripts.

- a billable request (a voiceover, a picture, a video, a Claude reply) from
  a script outside the project, or from code run with `python -c`, is
  refused before it's sent;
- the project's own programs may spend, and so may a run the owner allows
  by hand;
- lookups (the voice list, the credits left, a batch's status) are never
  refused.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from core import paid
from core.paths import PROJECT_ROOT


@pytest.fixture
def outside(monkeypatch, tmp_path):
    monkeypatch.setattr(paid, "_in_tests", lambda: False)
    monkeypatch.delenv("SHORTS_PAID_OK", raising=False)

    def run_from(path):
        monkeypatch.setitem(sys.modules, "__main__", SimpleNamespace(__file__=str(path) if path else None))
    return run_from


def test_only_the_projects_own_programs_may_spend(outside, tmp_path, monkeypatch):
    outside(tmp_path / "scratch.py")
    assert not paid.sanctioned()
    with pytest.raises(paid.PaidCallRefused):
        paid.check("a voiceover")
    outside(None)                                    # python -c, or code piped in
    assert not paid.sanctioned()
    outside(PROJECT_ROOT / "core" / "overseer.py")
    assert paid.sanctioned()
    outside(tmp_path / "scratch.py")
    monkeypatch.setenv("SHORTS_PAID_OK", "1")        # a paid run the owner asked for
    assert paid.sanctioned()


def test_what_bills_and_what_is_a_lookup():
    assert paid.billed("POST", "https://api.elevenlabs.io/v1/text-to-speech/v/with-timestamps")
    assert paid.billed("POST", "https://api.elevenlabs.io/v1/sound-generation")
    assert paid.billed("POST", "https://api.openai.com/v1/images/generations")
    assert paid.billed("POST", "https://queue.fal.run/fal-ai/minimax")
    assert not paid.billed("GET", "https://api.elevenlabs.io/v1/voices")
    assert not paid.billed("GET", "https://api.elevenlabs.io/v1/user/subscription")
    assert not paid.billed("GET", "https://api.openai.com/v1/batches/b1")
    assert not paid.billed("GET", "https://www.googleapis.com/youtube/v3/search")


def test_a_claude_reply_from_a_one_off_script_is_refused(outside, tmp_path, monkeypatch):
    from pipeline import llm
    outside(tmp_path / "scratch.py")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    with pytest.raises(paid.PaidCallRefused):
        llm.client()
