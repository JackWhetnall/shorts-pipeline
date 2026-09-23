"""
`core.voice_quota`: the ElevenLabs character allowance, read rather than
guessed, and a video stopped before its voiceover when it can't fit.

The property worth pinning down most is the unknown case. A key without
the user_read permission is a normal setup, and it must never block a
render; only a quota that was actually read and is actually too small
does.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from core import voice_quota
from core.voice_quota import Quota, VoiceQuotaExhausted

# Captured at import, before the autouse conftest fixture stubs it out.
_REAL_READ = voice_quota._read


@pytest.fixture
def quota(monkeypatch):
    """Set what ElevenLabs reports; None means unreadable."""
    state = {"value": None, "reads": 0}

    def read():
        state["reads"] += 1
        return state["value"]

    monkeypatch.setattr(voice_quota, "_read", read)
    return state


@pytest.fixture
def cost_log(tmp_path, monkeypatch):
    path = tmp_path / "cost_log.jsonl"
    monkeypatch.setattr("core.paths.COST_LOG_PATH", path)
    monkeypatch.setattr("core.costs.COST_LOG_PATH", path)
    return path


def _voiceover(job_id, characters, channel="chan"):
    return {"ts": time.time(), "service": "elevenlabs", "operation": "voiceover",
            "model": "m", "cost_usd": 0.0, "job_id": job_id, "channel_key": channel,
            "characters": characters}


def test_unknown_quota_never_blocks(quota):
    quota["value"] = None
    voice_quota.require_room(10_000_000)
    assert voice_quota.has_room_for(10_000_000)


def test_too_little_left_raises_with_a_readable_message(quota):
    quota["value"] = Quota(used=29_500, limit=30_000, resets_at=time.time() + 86400)
    with pytest.raises(VoiceQuotaExhausted) as excinfo:
        voice_quota.require_room(900)
    message = excinfo.value.user_message
    assert "900" in message and "500" in message and "30,000" in message
    assert "resets" in message


def test_enough_left_passes(quota):
    quota["value"] = Quota(used=1_000, limit=30_000)
    voice_quota.require_room(900)


def test_render_check_bypasses_the_page_cache(quota):
    quota["value"] = Quota(used=0, limit=30_000)
    voice_quota.current()
    quota["value"] = Quota(used=29_900, limit=30_000)
    # A page load inside the cache window sees the old number...
    assert voice_quota.current().remaining == 30_000
    # ...but the check a render makes reads fresh.
    with pytest.raises(VoiceQuotaExhausted):
        voice_quota.require_room(900)


def test_parses_the_subscription_response(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    payload = {"character_count": 12_000, "character_limit": 30_000,
               "next_character_count_reset_unix": 1_790_000_000, "tier": "starter"}
    monkeypatch.setattr(voice_quota.requests, "get",
                        lambda *a, **k: SimpleNamespace(ok=True, json=lambda: payload))
    q = _REAL_READ()
    assert (q.used, q.limit, q.remaining, q.tier) == (12_000, 30_000, 18_000, "starter")


def test_unreadable_response_is_unknown_not_an_error(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setattr(voice_quota.requests, "get",
                        lambda *a, **k: SimpleNamespace(ok=False, status_code=401))
    assert _REAL_READ() is None
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    assert _REAL_READ() is None


def test_typical_video_is_the_median_per_job_for_that_channel(cost_log):
    rows = [_voiceover("a", 400), _voiceover("a", 400),     # job a: 800
            _voiceover("b", 900),                            # job b: 900
            _voiceover("c", 5000),                           # job c: 5000 (outlier)
            _voiceover("z", 99_999, channel="other")]
    cost_log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert voice_quota.typical_video_characters("chan") == 900
    assert voice_quota.typical_video_characters("new") == voice_quota.DEFAULT_VIDEO_CHARACTERS


def test_summary_flags_a_low_quota(quota, cost_log):
    quota["value"] = Quota(used=27_000, limit=30_000)
    summary = voice_quota.summary(["chan"])
    assert summary["remaining"] == 3_000
    assert summary["videos_left"] == 3
    assert summary["low"]


def test_voiceover_stage_stops_before_any_synthesis(quota, monkeypatch):
    from pipeline import tts
    from pipeline.plan import Segment

    quota["value"] = Quota(used=30_000, limit=30_000)
    monkeypatch.setattr(tts.job_context, "load_json_checkpoint", lambda name: None)
    monkeypatch.setattr(tts, "generate_voiceover",
                        lambda *a, **k: pytest.fail("synthesis must not start"))
    pacing = SimpleNamespace(pause_after_first_segment=0.5, pause_after_citation=0.5,
                             pause_between_segments=0.5)
    plan = SimpleNamespace(
        script=SimpleNamespace(segments=[Segment(text="Hello there.")], citation=None),
        channel=SimpleNamespace(pacing=pacing, voice="v", speed=1.0),
        audio_path="x.mp3",
    )
    with pytest.raises(VoiceQuotaExhausted):
        tts.run(plan)


def test_scheduler_skips_a_channel_the_quota_cannot_cover(quota, monkeypatch, tmp_path):
    from core import scheduler

    channel = SimpleNamespace(archived=False, output_dir="output/chan")
    monkeypatch.setattr(scheduler, "load_channels", lambda validate=False: {"chan": channel})
    monkeypatch.setattr(scheduler.gallery, "video_state_counts",
                        lambda _: {"published": 1, "unpublished": 0})
    monkeypatch.setattr(scheduler.jobs, "active_jobs", lambda: {})
    monkeypatch.setattr("web.checklist.remaining_count", lambda *a: 0)
    path = tmp_path / "schedule.json"
    scheduler.save_schedules({"chan": scheduler.Schedule(enabled=True)}, path)

    quota["value"] = Quota(used=29_950, limit=30_000)
    assert scheduler.due_channels(path) == []

    quota["value"] = None
    voice_quota._cached = None
    assert [key for key, _, _ in scheduler.due_channels(path)] == ["chan"]
