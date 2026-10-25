"""
The voice priority (decision 131). The owner, 23 Oct: "prioritise why
though films when credits are short. then the quiz channel. then minute
pastor." And 25 Oct: "i dont want one channel to miss a video just so Why
Though gets one made 3 weeks in advance."

- what goes out sooner is voiced first, whichever channel it's for;
- between videos due within half a day of each other, the priority decides;
- a video made ahead of any slot comes after every channel's dated ones;
- a channel with no priority comes after every channel that has one.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from core import voice_quota

DAY = 86400


def _channel(key, priority):
    return SimpleNamespace(key=key, archived=False, publishing=SimpleNamespace(enabled=True, voice_priority=priority))


@pytest.fixture
def world(monkeypatch):
    now = time.time()
    channels = {"why": _channel("why", 1), "quiz": _channel("quiz", 2), "pastor": _channel("pastor", 3)}
    plan = {"why": [(now + 3 * DAY, 1500), (now + 7 * DAY, 1500)],
            "quiz": [(now + 1 * DAY, 300), (now + 3 * DAY + 3600, 300)],
            "pastor": [(now + 2 * DAY, 100)]}
    monkeypatch.setattr("core.channels.load_channels", lambda validate=True: channels)
    monkeypatch.setattr(voice_quota, "needs", lambda channel, quota: plan[channel.key])
    monkeypatch.setattr(voice_quota, "credits_for", lambda characters: characters)
    monkeypatch.setattr(voice_quota, "_reserved", {})
    quota = voice_quota.Quota(used=31545 - 2000, limit=31545, resets_at=None)
    monkeypatch.setattr(voice_quota, "current", lambda force=False: quota)
    return SimpleNamespace(channels=channels, plan=plan, now=now)


def test_a_video_due_sooner_is_voiced_first_whichever_channel(world):
    # The quiz short tomorrow and Minute Pastor's in two days go before Why,
    # Though?'s film in three; the quiz short an hour after that film, a
    # near-tie, goes after it.
    assert voice_quota.reserve_for("why") == 300 + 100
    assert voice_quota.reserve_for("quiz") == 0                 # its short tomorrow is the first due
    assert voice_quota.reserve_for("pastor") == 300             # only the quiz short a day before it


def test_a_film_made_ahead_comes_after_everyone_elses_dated_videos(world):
    world.plan["why"] = []                                      # its slots are filled: a film would be ahead
    voice_quota._reserved.clear()
    assert voice_quota.reserve_for("why") == 300 + 300 + 100


def test_a_tie_goes_to_the_channel_first_in_the_priority(world):
    world.plan["quiz"] = [(world.now + 3 * DAY + 3600, 300)]
    voice_quota._reserved.clear()
    # Why, Though?'s film an hour before it, a near-tie, and Minute Pastor's a day before that.
    assert voice_quota.reserve_for("quiz") == 1500 + 100


def test_room_is_what_is_left_after_whats_kept_back(world):
    # 2,000 left: the quiz short tomorrow and Minute Pastor's are due before the film.
    assert voice_quota.has_room_for(1500, channel_key="why")
    assert not voice_quota.has_room_for(1700, channel_key="why")
    assert voice_quota.has_room_for(1700)                       # without a channel, as before
