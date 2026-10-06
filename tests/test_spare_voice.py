"""
Spare voice (core.spare_voice) and credits per character
(core.voice_quota), decision 069.

The owner, two days from a reset with most of the allowance left: what's
left shouldn't be wasted. Make videos ahead that fill the upload schedule
with no gaps, up to the latest date the spare reaches.

And the finding behind it: ElevenLabs charges 0.2 credits a character for
the voiceover model, and the app counted a character as a credit, so it
thought the allowance five times smaller than it was.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core import spare_voice, voice_quota
from core.spare_voice import Situation, make_plan
from core.voice_quota import Quota, VoiceQuotaExhausted

NOW = datetime(2026, 10, 5, 18, 0).astimezone().timestamp()
DAY = 86400


# --- credits per character -----------------------------------------------------------

def _history(items):
    return SimpleNamespace(ok=True, status_code=200, json=lambda: {"history": items})


def test_the_rate_is_measured_from_elevenlabs_own_history(monkeypatch):
    """7,629 characters took 1,527 credits on 5 Oct: 0.2 a character."""
    from pipeline.tts import ELEVENLABS_MODEL
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    items = [{"model_id": ELEVENLABS_MODEL, "text": "x" * 500, "character_count_change_from": 1000,
              "character_count_change_to": 1100},
             {"model_id": ELEVENLABS_MODEL, "text": "y" * 500, "character_count_change_from": 1100,
              "character_count_change_to": 1200},
             {"model_id": "eleven_multilingual_v2", "text": "z" * 500, "character_count_change_from": 0,
              "character_count_change_to": 500}]                        # another model: left out
    monkeypatch.setattr(voice_quota.requests, "get", lambda *a, **k: _history(items))
    assert REAL_READ_RATIO() == pytest.approx(0.2)
    # Too little to go on says nothing.
    monkeypatch.setattr(voice_quota.requests, "get", lambda *a, **k: _history(items[:1][:0]))
    assert REAL_READ_RATIO() is None


REAL_READ_RATIO = voice_quota._read_ratio       # captured before the autouse fixture stubs it


def test_the_rate_is_kept_a_day_and_the_last_one_stands_in(monkeypatch):
    reads = []
    monkeypatch.setattr(voice_quota, "_read_ratio", lambda: reads.append(1) or 0.2)
    assert voice_quota.credits_per_character() == 0.2
    assert voice_quota.credits_per_character() == 0.2 and len(reads) == 1      # kept
    saved = json.loads(voice_quota.RATIO_PATH.read_text())
    # A day later ElevenLabs won't answer: the last measurement stands in.
    voice_quota.RATIO_PATH.write_text(json.dumps({"at": saved["at"] - 2 * DAY, "ratio": 0.2}))
    monkeypatch.setattr(voice_quota, "_ratio", None)
    monkeypatch.setattr(voice_quota, "_read_ratio", lambda: None)
    assert voice_quota.credits_per_character() == 0.2


def test_never_measured_a_character_is_a_credit():
    assert voice_quota.credits_per_character() == 1.0


def test_room_is_checked_in_credits(monkeypatch):
    """Regression: 900 characters against 500 credits left was refused,
    when at 0.2 a character it takes 180."""
    monkeypatch.setattr(voice_quota, "_ratio", (9e12, 0.2))
    monkeypatch.setattr(voice_quota, "_read", lambda: Quota(used=29_500, limit=30_000))
    voice_quota.require_room(900)
    assert voice_quota.has_room_for(900, force=True)
    with pytest.raises(VoiceQuotaExhausted) as caught:
        voice_quota.require_room(5000)                           # 1,000 credits
    assert "1,000 ElevenLabs credits" in caught.value.user_message


# --- the plan ----------------------------------------------------------------------------

def _daily(hour: int, days: int, start: float = NOW):
    first = datetime.fromtimestamp(start).astimezone().replace(hour=hour, minute=0, second=0, microsecond=0)
    if first.timestamp() <= start:
        first += timedelta(days=1)
    return [first + timedelta(days=i) for i in range(days)]


def _situation(**changes):
    s = Situation(now=NOW, remaining=3000, resets_at=NOW + 2 * DAY,
                  slots={"pqb": _daily(18, 60), "mp": _daily(11, 60)[::2]},
                  covered={"pqb": 2, "mp": 1}, credits={"pqb": 300, "mp": 100},
                  usd={"pqb": 0.10, "mp": 0.05}, usd_available=10.0, minutes=30,
                  names={"pqb": "Pub Quiz Buzz", "mp": "Minute Pastor"})
    for key, value in changes.items():
        setattr(s, key, value)
    return s


def test_nothing_happens_until_the_last_days_before_a_reset():
    plan = make_plan(_situation(resets_at=NOW + 10 * DAY))
    assert not plan.active and "last 3 days" in plan.why
    assert not make_plan(_situation(resets_at=0)).active


def test_slots_are_filled_in_date_order_with_no_gaps_until_the_credits_run_out():
    s = _situation()
    plan = make_plan(s)
    # 3,000 credits less a margin of two 300-credit videos: 2,400 to spend.
    assert plan.spare == 2400 and plan.credits <= 2400
    whens = [when for when, _ in plan.videos]
    assert whens == sorted(whens)
    # The slots already covered are skipped...
    assert plan.videos[0] == (s.slots["pqb"][2], "pqb") or plan.videos[0] == (s.slots["mp"][1], "mp")
    # ...and every slot up to `filled_to` has a video, across both channels.
    upto = [(w, k) for k in ("pqb", "mp") for w in s.slots[k][s.covered[k]:] if w <= plan.filled_to]
    assert sorted(upto) == sorted(v for v in plan.videos if v[0] <= plan.filled_to)
    assert plan.why == "The credits run out there."
    assert "every slot filled to" in plan.summary()


def test_credits_left_over_go_on_a_cheaper_channels_later_slot():
    """Not wasted: when the next slot's video won't fit, a cheaper channel's
    later one still can."""
    s = _situation(remaining=850, covered={"pqb": 0, "mp": 0})
    plan = make_plan(s)                       # 850 - 600 margin = 250: no pqb (300), but mp (100) fits
    assert plan.spare == 250
    assert [k for _, k in plan.videos] == ["mp", "mp"]


def test_the_claude_reserve_stops_it():
    plan = make_plan(_situation(remaining=30_000, usd_available=0.25))
    assert plan.usd <= 0.25 and "two-week reserve" in plan.why


def test_only_what_can_be_made_before_the_reset_is_planned():
    plan = make_plan(_situation(remaining=30_000, resets_at=NOW + 4 * 3600, minutes=60))
    assert len(plan.videos) == 3 and "no time" in plan.why       # 4 hours, less one, at an hour each


def test_never_further_ahead_than_the_horizon():
    plan = make_plan(_situation(remaining=10_000_000, usd_available=1000, minutes=1))
    last = max(when for when, _ in plan.videos)
    assert last.timestamp() <= NOW + spare_voice.MAX_DAYS_AHEAD * DAY
    assert "next 90 days" in plan.why


# --- running it -------------------------------------------------------------------------

@pytest.fixture
def scheduler_world(monkeypatch):
    from core import jobs
    started = []
    monkeypatch.setattr(jobs, "active_jobs", lambda: {})
    monkeypatch.setattr(jobs, "start_job", lambda key, seed, ahead=False, note="":
                        started.append((key, ahead, note)) or "job")
    monkeypatch.setattr("pipeline.run.fetch_seed",
                        lambda channel: SimpleNamespace(to_jsonable=lambda: {"title": channel.key}))
    plan = make_plan(_situation())
    monkeypatch.setattr(spare_voice, "current_plan", lambda channels=None: plan)
    channels = {"pqb": SimpleNamespace(key="pqb"), "mp": SimpleNamespace(key="mp")}
    return SimpleNamespace(started=started, plan=plan, channels=channels, jobs=jobs)


def test_it_starts_the_earliest_slots_video_at_batch_prices(scheduler_world):
    w = scheduler_world
    assert spare_voice.run(w.channels) == w.plan.videos[0][1]
    key, ahead, note = w.started[0]
    assert ahead and "spare voice" in note and "resets" in note


def test_never_while_anything_else_is_being_made(scheduler_world, monkeypatch):
    monkeypatch.setattr(scheduler_world.jobs, "active_jobs", lambda: {"pqb": {}})
    assert spare_voice.run(scheduler_world.channels) is None and not scheduler_world.started


def test_a_channel_that_cant_start_one_doesnt_stop_the_next(scheduler_world, monkeypatch):
    first = scheduler_world.plan.videos[0][1]

    def seed(channel):
        if channel.key == first:
            raise RuntimeError("its plan has run out")
        return SimpleNamespace(to_jsonable=lambda: {})
    monkeypatch.setattr("pipeline.run.fetch_seed", seed)
    started = spare_voice.run(scheduler_world.channels)
    assert started and started != first


def test_switched_off_it_plans_nothing(monkeypatch):
    from core import money
    money.save_settings({"spare_voice": False})
    plan = spare_voice.current_plan({})
    assert not plan.active and "switched off" in plan.why


# --- what Today says ----------------------------------------------------------------------

def test_running_low_on_purpose_before_a_reset_isnt_a_warning():
    from core import today
    soon = datetime.fromtimestamp(NOW).date() + timedelta(days=2)
    voice = {"runs_out": soon - timedelta(days=1), "resets": soon, "dry_days": 1,
             "limit": 30000, "schedule_need": 11000}
    items = today.needs_you({}, lambda e, **k: "/", now=NOW, forecast={"claude_balance": 30,
                                                                      "claude": {"days": 60}, "voice": voice})
    assert not any("runs out" in i.title for i in items)


def test_a_schedule_the_allowance_cant_cover_is_said():
    from core import today
    voice = {"runs_out": None, "resets": None, "limit": 30000, "schedule_need": 41000}
    items = today.needs_you({}, lambda e, **k: "/", now=NOW, forecast={"claude_balance": 30,
                                                                      "claude": {"days": 60}, "voice": voice})
    assert any("won't cover a month of this schedule" in i.title for i in items)


# --- long-form first (decision 075) ---------------------------------------------------------

def _production(**stages):
    from core import production
    data = production.blank("t0001", "Ada Lovelace")
    for stage, state in stages.items():
        production.mark(data, stage, state)
    return data


def test_a_written_script_owes_its_narration_exactly():
    from core import production
    data = _production(outline="approved", script="ready")
    data["script"] = {"scenes": [{"narration": "x" * 1200}, {"narration": "y" * 800}]}
    assert production.narration_still_to_voice(data) == 2000
    # Voiced (or being voiced) already: nothing more is owed for the film.
    for done in ("working", "ready", "approved"):
        production.mark(data, "video", done)
        assert production.narration_still_to_voice(data) == 0


def test_an_approved_outline_owes_an_estimate_and_one_written_ahead_owes_nothing():
    from core import production
    from pipeline.documentary.script import WORDS_PER_SECOND
    data = _production(outline="ready")
    data["outline"] = {"chapters": [{"minutes": 6.0}, {"minutes": 4.0}]}
    assert production.narration_still_to_voice(data) == 0          # the scheduler's, not started
    production.mark(data, "outline", "approved")
    assert production.narration_still_to_voice(data) == round(
        10 * 60 * WORDS_PER_SECOND * production.CHARACTERS_PER_WORD)


def test_teasers_written_and_waiting_are_owed_too():
    from core import production
    data = _production(outline="approved", script="approved", stills="approved", video="approved",
                       teasers="ready")
    data["teasers"] = {"scripts": [{"scenes": [{"narration": "a" * 300}]},
                                   {"scenes": [{"narration": "b" * 200}, {"narration": "c" * 100}]}]}
    assert production.narration_still_to_voice(data) == 600
    production.mark(data, "teasers", "approved")                   # made
    assert production.narration_still_to_voice(data) == 0


def test_the_spare_goes_on_shorts_only_after_whats_owed_to_long_form():
    plain = make_plan(_situation())
    kept = make_plan(_situation(long_form=1000, long_form_films=1))
    assert kept.spare == plain.spare - 1000 and kept.credits <= kept.spare
    assert "Keeping 1,000 credits for 1 documentary in production" in kept.summary()


def test_when_long_form_needs_all_of_it_no_short_is_made_ahead():
    plan = make_plan(_situation(long_form=5000, long_form_films=2))
    assert plan.active and not plan.videos
    assert plan.why == "What's left (3,000 credits) is kept for the documentaries in production."


def test_only_documentaries_in_production_are_counted(tmp_path, monkeypatch):
    from core import production
    monkeypatch.setattr(production, "CHANNELS_DIR", tmp_path)
    monkeypatch.setattr(voice_quota, "_ratio", (9e12, 0.2))
    now = datetime.now().timestamp()

    active = _production(outline="approved", script="ready")
    active["script"] = {"scenes": [{"narration": "x" * 5000}]}
    production.save("history", active)
    abandoned = _production(outline="approved", script="ready")
    abandoned["subtopic_id"] = "t0002"
    abandoned["script"] = {"scenes": [{"narration": "x" * 9000}]}
    for entry in abandoned["stages"].values():
        entry["at"] = "2026-01-01T00:00:00+00:00"                  # untouched for months
    production.save("history", abandoned)
    production.save("archived_docs", active)

    channels = {"history": SimpleNamespace(archived=False, format="documentary"),
                "archived_docs": SimpleNamespace(archived=True, format="documentary"),
                "pqb": SimpleNamespace(archived=False, format="quiz")}
    assert spare_voice.long_form_owed(channels, now) == (1000, 1)  # 5,000 characters at 0.2


def test_a_documentary_channels_slots_are_never_filled_with_shorts(monkeypatch):
    """The scheduler never makes a documentary itself (decision 074); spare
    voice used to plan shorts for any channel with slots, this one included."""
    from core import gallery, jobs, money, publish_queue
    from core import costs
    from pipeline.facts import budget
    from core.voice_quota import Quota
    monkeypatch.setattr(voice_quota, "current", lambda force=False: Quota(used=10_000, limit=30_000))
    monkeypatch.setattr(costs, "read_records", lambda: [])
    monkeypatch.setattr(jobs, "active_jobs", lambda: {})
    monkeypatch.setattr(gallery, "video_state_counts", lambda *a, **k: {"queued": 0, "waiting": 0})
    monkeypatch.setattr(spare_voice, "long_form_owed", lambda channels, now: (0, 0))
    monkeypatch.setattr(spare_voice, "made_ahead_minutes", lambda: 30)
    publishing = SimpleNamespace(enabled=True, slots=["11:00"], weekdays=[0, 1, 2, 3, 4, 5, 6])

    def channel(fmt):
        return SimpleNamespace(archived=False, format=fmt, publishing=publishing, validate=lambda: None,
                               channel_display_name=fmt, output_dir=f"output/{fmt}")
    s = spare_voice.situation({"docs": channel("documentary"), "mp": channel("narrated")}, now=NOW)
    assert list(s.slots) == ["mp"]
