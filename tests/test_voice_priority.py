"""
The voice priority (decisions 131 and 134). The owner, 23 Oct: "prioritise
why though films when credits are short. then the quiz channel. then minute
pastor." And 25 Oct: "if there is enough credit for the month, then all the
months videos should be made. what i dont want to happen is Why Though
having the whole month made plus the three premade videos prioritised over
another channel's videos that need to be published this month."

- a video for a channel's own slots before the reset keeps back what the
  channels ahead of it in the priority need for theirs;
- once its slots are covered, a video made ahead keeps back what every
  other channel needs;
- with enough credits for the month, every channel's month is made;
- a channel with no priority comes after every channel that has one.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from core import voice_quota
from core.voice_quota import Need

DAY = 86400


def _channel(key, priority):
    return SimpleNamespace(key=key, archived=False, publishing=SimpleNamespace(enabled=True, voice_priority=priority))


@pytest.fixture
def world(monkeypatch):
    now = time.time()
    channels = {"why": _channel("why", 1), "quiz": _channel("quiz", 2), "pastor": _channel("pastor", 3)}
    plan = {"why": [Need(now + 3 * DAY, 1500, True), Need(now + 7 * DAY, 1500, True)],
            "quiz": [Need(now + 1 * DAY, 300, True), Need(now + 3 * DAY, 300, True)],
            "pastor": [Need(now + 2 * DAY, 100, True)]}
    monkeypatch.setattr("core.channels.load_channels", lambda validate=True: channels)
    monkeypatch.setattr(voice_quota, "needs", lambda channel, quota: plan[channel.key])
    monkeypatch.setattr(voice_quota, "credits_for", lambda characters: characters)
    monkeypatch.setattr(voice_quota, "_reserved", {})
    quota = voice_quota.Quota(used=31545 - 2000, limit=31545, resets_at=None)
    monkeypatch.setattr(voice_quota, "current", lambda force=False: quota)
    return SimpleNamespace(channels=channels, plan=plan, now=now, quota=quota)


def test_when_short_the_channels_month_goes_in_priority_order(world):
    assert voice_quota.reserve_for("why") == 0
    assert voice_quota.reserve_for("quiz") == 1500 + 1500
    assert voice_quota.reserve_for("pastor") == 3000 + 600
    # 2,000 left: Why, Though?'s film goes ahead of the quiz short due sooner.
    assert voice_quota.has_room_for(1500, channel_key="why")
    assert not voice_quota.has_room_for(300, channel_key="quiz")


def test_a_film_made_ahead_waits_for_every_other_channels_month(world):
    world.plan["why"] = []                                      # its month is covered: a bank film
    assert voice_quota.reserve_for("why") == 600 + 100
    assert voice_quota.has_room_for(1300, channel_key="why")
    assert not voice_quota.has_room_for(1500, channel_key="why")


def test_teasers_owed_dont_make_a_bank_film_a_months_one(world):
    world.plan["why"] = [Need(world.now, 400, False)]           # teasers to make, no slot left to fill
    assert voice_quota.reserve_for("why") == 600 + 100


def test_with_enough_for_the_month_every_channels_month_is_made(world, monkeypatch):
    plenty = voice_quota.Quota(used=0, limit=31545, resets_at=None)
    monkeypatch.setattr(voice_quota, "current", lambda force=False: plenty)
    for key in ("why", "quiz", "pastor"):
        voice_quota._reserved.clear()
        assert voice_quota.has_room_for(1500, channel_key=key)


def test_a_channel_with_no_priority_comes_last(world):
    world.channels["new"] = _channel("new", 0)
    world.plan["new"] = [Need(world.now + DAY, 200, True)]
    assert voice_quota.reserve_for("new") == 3000 + 600 + 100
    voice_quota._reserved.clear()
    assert voice_quota.reserve_for("pastor") == 3000 + 600      # not kept back for the new channel


def test_without_a_channel_nothing_is_kept_back(world):
    assert voice_quota.has_room_for(1700)
