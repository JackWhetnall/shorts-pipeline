"""
A job waiting on a batch steps aside (decision 103): the app runs one job
at a time, so a picture batch OpenAI took 16 hours over held every job
behind it, on every channel, and the night's film never started.
"""

from __future__ import annotations

import pytest

from core import auto_films, jobs, production


@pytest.fixture
def queue(monkeypatch):
    spawned = []
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(jobs, "_queue", [])
    monkeypatch.setattr(jobs, "_waits", {})
    monkeypatch.setattr(jobs, "_persist", lambda job_id: None)
    monkeypatch.setattr(jobs, "_spawn", lambda job_id, *a: spawned.append(job_id))
    monkeypatch.setattr(jobs, "install", lambda: None)
    monkeypatch.setattr(jobs, "_refuse_if_stale", lambda: None)
    return spawned


def test_the_next_job_starts_while_one_waits_and_only_one_works_at_a_time(queue):
    a = jobs.start_job("why", {"type": "production", "subtopic_id": "t1"}, behind=True)
    b = jobs.start_job("pqb", {"type": "x"})
    c = jobs.start_job("mp", {"type": "x"})
    assert queue == [a] and jobs._jobs[b].status == "queued"
    jobs._sink.on_waiting(a, True)
    assert queue == [a, b] and jobs._jobs[b].status == "running"
    assert jobs._jobs[c].status == "queued"                     # b works; c still waits its turn
    jobs._sink.on_waiting(a, False)                              # a's batch is back: it carries on
    assert not jobs._jobs[a].waiting and queue == [a, b]


def test_side_by_side_waits_are_counted(queue):
    a = jobs.start_job("why", {"type": "x"})
    jobs._sink.on_waiting(a, True)
    jobs._sink.on_waiting(a, True)
    jobs._sink.on_waiting(a, False)
    assert jobs._jobs[a].waiting                                 # one batch still out
    jobs._sink.on_waiting(a, False)
    assert not jobs._jobs[a].waiting


def test_a_channel_can_start_another_while_its_job_waits(queue):
    a = jobs.start_job("why", {"type": "x"})
    with pytest.raises(jobs.JobError):
        jobs.start_job("why", {"type": "x"})
    jobs._sink.on_waiting(a, True)
    assert jobs.start_job("why", {"type": "x"})


def test_the_autopilot_moves_another_film_on_while_one_waits(monkeypatch):
    def film(sid, stages):
        data = production.blank(sid)
        for s, v in stages.items():
            data["stages"][s]["state"] = v
        return data
    films = [film("t1", {"pitch": "approved", "outline": "approved", "script": "approved", "stills": "working"}),
             film("t2", {"pitch": "approved", "outline": "approved", "script": "approved"})]
    monkeypatch.setattr(production, "all_for", lambda key: films)
    monkeypatch.setattr(auto_films.curriculum, "find", lambda key, sid: {"id": sid, "title": sid})
    monkeypatch.setattr(jobs, "active_in_order", lambda: [
        {"channel_key": "why", "seed": {"type": "production", "subtopic_id": "t1"}, "waiting": True}])
    channel = type("C", (), {"key": "why", "documentary": type("D", (), {"teasers": 0})()})()
    row, data, new = auto_films._next_film(channel)
    assert row["id"] == "t2" and not new
    assert not auto_films._busy("why")


def test_a_film_waiting_on_someone_doesnt_hold_the_rest_and_three_are_kept_in_hand(monkeypatch):
    # Decision 105: one film at a time, and a film waiting for the
    # overseer held everything else.
    def film(sid, stages):
        data = production.blank(sid, sid)
        for s, v in stages.items():
            data["stages"][s]["state"] = v
        return data
    films = {"t1": film("t1", {"pitch": "approved", "outline": "approved", "script": "ready"}),
             "t2": film("t2", {"pitch": "approved"})}
    monkeypatch.setattr(production, "all_for", lambda key: list(films.values()))
    monkeypatch.setattr(production, "load", lambda key, sid, title="": films.get(sid) or production.blank(sid, title))
    monkeypatch.setattr(auto_films.curriculum, "find", lambda key, sid: {"id": sid, "title": sid})
    monkeypatch.setattr(jobs, "active_in_order", lambda: [])
    monkeypatch.setattr("core.storyboard.upcoming", lambda channel, count=1: [{"id": "t2", "title": "t2"},
                                                                              {"id": "t3", "title": "t3"}][:count])
    started = []
    monkeypatch.setattr(auto_films, "start", lambda c, r, s: started.append((r["id"], s)) or "j")
    import core.channels as config
    monkeypatch.setattr(config, "within_hours", lambda t, h: True)
    from types import SimpleNamespace as N
    channel = N(key="why", format="documentary", archived=False, publishing=N(enabled=True),
                animation=N(style={"a": 1}),
                documentary=N(auto_make=True, ahead=3, teasers=0, overseen=True, hours=""))
    assert "started the outline of t2" in auto_films.step(channel)          # t1 waits for the overseer
    films["t2"]["stages"]["outline"]["state"] = "working"
    films["t3"] = film("t3", {"pitch": "approved"})
    monkeypatch.setattr(auto_films, "_being_made", lambda key: {"t2"})
    assert "started the outline of t3" in auto_films.step(channel)          # a third film in hand
    films["t3"]["stages"]["outline"]["state"] = "working"
    films["t4"] = film("t4", {"pitch": "approved"})
    monkeypatch.setattr(auto_films, "_being_made", lambda key: {"t2", "t3"})
    monkeypatch.setattr("core.storyboard.upcoming", lambda channel, count=1: [{"id": "t4", "title": "t4"}][:count])
    assert auto_films.step(channel) == "" and started == [("t2", "outline"), ("t3", "outline")]  # three: enough
