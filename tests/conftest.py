from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_live_voice_quota(monkeypatch):
    """The quota check reads ElevenLabs over the network whenever a key is
    set, and plenty of tests set a fake one. Unknown is the check's
    allow-everything answer, so this keeps every other test exactly as it
    was; tests of the quota itself patch `_read` again."""
    from core import voice_quota
    monkeypatch.setattr(voice_quota, "_read", lambda: None)
    monkeypatch.setattr(voice_quota, "_cached", None)


@pytest.fixture(autouse=True)
def _isolated_script_history(tmp_path, monkeypatch):
    """The script stage checks originality against the channel's script
    history, so any test that runs it would otherwise read (and a full
    render would write) this installation's real history."""
    monkeypatch.setattr("pipeline.similarity.SCRIPT_HISTORY_PATH",
                        tmp_path / "script_history.json")
