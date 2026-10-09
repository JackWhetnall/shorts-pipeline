"""
Prices and times for batch-or-now, long quiz counts and picks, and a
production's old video (decision 081).

The owner: "lots of 'accelerate' or 'now, at full price' options dotted
around, but no indication how much faster it is likely to make it, how
much it will cost"; the long quiz menu said "Tricky - 7 ready" and then
"5 of 6 rounds are ready at Tricky"; "Rising" shouldn't be made by
itself; rounds should be pickable and orderable; and nothing showed that
a video had been discarded when its script was redone.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import estimates


def _job(id_, seed, minutes, ahead, channel="c"):
    return {"id": id_, "seed": seed, "status": "done", "started_at": 0.0, "finished_at": minutes * 60.0,
            "ahead": ahead, "channel_key": channel}


def test_a_job_kind_is_what_decides_its_price_and_time():
    assert estimates.kind_of({"type": "production", "stage": "script"}) == "production:script"
    assert estimates.kind_of({"type": "longform"}) == "longform"
    assert estimates.kind_of({"reference": "John 3:16"}) == "short"


def test_batch_halves_only_claudes_part_and_times_come_from_history():
    seed = {"type": "production", "stage": "script"}
    history = [_job("a", seed, 3, False), _job("b", seed, 48, True), _job("c", seed, 50, True)]
    records = [
        {"job_id": "a", "service": "claude", "cost_usd": 0.20, "batch": False},
        {"job_id": "b", "service": "claude", "cost_usd": 0.10, "batch": True},       # 0.20 at full price
        {"job_id": "b", "service": "elevenlabs", "cost_usd": 0.30},
        {"job_id": "c", "service": "claude", "cost_usd": 0.10, "batch": True},
    ]
    e = estimates.estimate(seed, "c", history, records)
    assert e.measured and e.usd_now == pytest.approx(0.20) and e.usd_batch == pytest.approx(0.10)
    assert (round(e.minutes_now), round(e.minutes_batch)) == (3, 49)


def test_with_no_history_a_default_stands_in_and_says_so():
    e = estimates.estimate({"type": "production", "stage": "outline"}, "c", [], [])
    assert not e.measured and e.usd_batch < e.usd_now and e.minutes_batch >= e.minutes_now


def test_finish_labels():
    assert estimates.finish_label(20) == "~20 min"
    assert estimates.finish_label(30, start_in=25).startswith("~") and ":" in estimates.finish_label(30, start_in=25)


# --- long quizzes ------------------------------------------------------------------

@pytest.fixture
def rounds(monkeypatch):
    from pipeline import longform
    rows = [{"stem": s, "category": c, "difficulty": "Tricky", "level": 6, "rank": (0, i),
             "video": SimpleNamespace(), "questions": [{"question": f"q {s}", "answer": a}]}
            for i, (s, c, a) in enumerate([("a", "Sport", "Pele"), ("b", "Countries", "France"),
                                          ("c", "Flags", "France"), ("d", "Music", "Abba")])]
    monkeypatch.setattr(longform, "available_rounds", lambda channel, series=None: [dict(r) for r in rows])
    monkeypatch.setattr(longform.gallery, "load_publish_info", lambda v: {"title": ""})
    monkeypatch.setattr(longform.quiz, "labels", lambda channel: ["Tricky"])
    monkeypatch.setattr(longform.random, "shuffle", lambda x: None)
    return SimpleNamespace(key="pqb"), longform


def test_the_menu_counts_rounds_that_can_go_together(rounds):
    channel, longform = rounds
    assert longform.availability(channel)["Tricky"] == 4                      # what the scheduler uses, unchanged
    assert longform.availability(channel, clash_free=True)["Tricky"] == 3     # Flags and Countries share France


def test_rounds_can_be_picked_and_ordered_but_not_clashing_ones(rounds):
    channel, longform = rounds
    listed = longform.rounds_for(channel, "Tricky")
    assert [r["stem"] for r in listed if r["chosen"]] == ["a", "b", "d"] and not listed[-1]["chosen"]
    assert [r["stem"] for r in longform.picked_rounds(channel, "Tricky", ["d", "a"])] == ["d", "a"]
    with pytest.raises(longform.LongformError) as raised:
        longform.picked_rounds(channel, "Tricky", ["b", "c"])
    assert "give each other's answers away" in raised.value.user_message


def test_rising_is_only_made_when_asked_for(rounds):
    channel, longform = rounds
    channel.quiz = SimpleNamespace(longform_rounds=6)
    assert longform.plan_request(channel, {"difficulty": "best", "rounds": 6})["difficulty"] == "Tricky"


# --- a production's old video ------------------------------------------------------------

def test_a_video_that_no_longer_follows_its_plan_is_discarded_and_shown(tmp_path, monkeypatch):
    from core import curriculum, gallery, production
    from pipeline.documentary import run
    monkeypatch.setattr(production, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(run, "_root", lambda channel: tmp_path / "out")
    video = tmp_path / "out" / "longform" / "film.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    discarded = []
    monkeypatch.setattr(gallery, "load_publish_info", lambda p: {"discarded": False})
    monkeypatch.setattr(gallery, "is_out", lambda info: False)
    monkeypatch.setattr(gallery, "set_discarded", lambda p, on, reason=None: discarded.append((p.name, reason)))
    channel = SimpleNamespace(key="h")
    production.update("h", "t1", lambda d: d.update(video={"path": "longform/film.mp4"}))
    assert run.retire_video(channel, "t1")
    assert discarded == [("film.mp4", "remade")]
    assert production.load("h", "t1")["video"]["retired"] == "longform/film.mp4"
    assert not run.retire_video(channel, "t1", keep="longform/film.mp4")
