"""
The voice priority (decision 131). The owner, 23 Oct: "prioritise why
though films when credits are short. then the quiz channel. then minute
pastor."

- a channel starts a video only if what's left still covers what every
  channel ahead of it needs before the reset;
- the first channel keeps nothing back for anyone;
- a channel with no priority comes after every channel that has one.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import voice_quota


def _channel(key, priority):
    return SimpleNamespace(key=key, archived=False, publishing=SimpleNamespace(enabled=True, voice_priority=priority))


@pytest.fixture
def world(monkeypatch):
    channels = {"why": _channel("why", 1), "quiz": _channel("quiz", 2), "pastor": _channel("pastor", 3),
                "other": _channel("other", 0)}
    needs = {"why": 3000, "quiz": 800, "pastor": 400, "other": 100}
    monkeypatch.setattr("core.channels.load_channels", lambda validate=True: channels)
    monkeypatch.setattr(voice_quota, "need_before_reset", lambda channel, quota: needs[channel.key])
    monkeypatch.setattr(voice_quota, "credits_for", lambda characters: characters)
    monkeypatch.setattr(voice_quota, "_reserved", {})
    quota = voice_quota.Quota(used=31545 - 3500, limit=31545, resets_at=None)
    monkeypatch.setattr(voice_quota, "current", lambda force=False: quota)
    return channels


def test_each_channel_keeps_back_what_the_ones_ahead_of_it_need(world):
    assert voice_quota.reserve_for("why") == 0
    assert voice_quota.reserve_for("quiz") == 3000
    assert voice_quota.reserve_for("pastor") == 3800
    assert voice_quota.reserve_for("other") == 4200          # no priority: after all of them


def test_a_short_waits_while_the_films_need_the_credits(world):
    # 3,500 left: the films need 3,000 of them.
    assert voice_quota.has_room_for(1500, channel_key="why")
    assert voice_quota.has_room_for(400, channel_key="quiz")
    assert not voice_quota.has_room_for(600, channel_key="quiz")
    assert not voice_quota.has_room_for(100, channel_key="pastor")
    assert voice_quota.has_room_for(600)                      # without a channel, as before
