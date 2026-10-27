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
                documentary=N(auto_make=True, ahead=1, parallel=3, teasers=0, overseen=True, hours=""))
    assert "started the outline of t2" in auto_films.step(channel)          # t1 waits for the overseer
    films["t2"]["stages"]["outline"]["state"] = "working"
    films["t3"] = film("t3", {"pitch": "approved"})
    monkeypatch.setattr(auto_films, "_being_made", lambda key: {"t2"})
    assert "started the outline of t3" in auto_films.step(channel)          # a third film in hand
    films["t3"]["stages"]["outline"]["state"] = "working"
    films["t4"] = film("t4", {"pitch": "approved"})
    monkeypatch.setattr(auto_films, "_being_made", lambda key: {"t2", "t3"})
    monkeypatch.setattr("core.storyboard.upcoming", lambda channel, count=1: [{"id": "t4", "title": "t4"}][:count])
    assert auto_films.step(channel) == "" and started == [("t2", "outline"), ("t3", "outline")]  # three at once: enough


def test_a_restart_waits_only_for_work_being_done_and_resumes_waiting_film_stages(queue, monkeypatch):
    # Decision 108: a storyboard waiting on its batch held the app's
    # restart onto new code for hours.
    a = jobs.start_job("why", {"type": "production", "subtopic_id": "t1", "stage": "stills"}, behind=True)
    assert jobs.busy_for_restart()                                # working
    jobs._sink.on_waiting(a, True)
    assert not jobs.busy_for_restart()                            # only waiting: the restart may go ahead
    s = jobs.start_job("pqb", {"type": "x"})
    jobs._sink.on_waiting(s, True)
    assert jobs.busy_for_restart()                                # a waiting short has nothing to resume it
    # After the restart: the film stage comes back under its own id.
    for job in jobs._jobs.values():
        job.status = "interrupted"
    jobs._jobs.pop(s)
    queue.clear()
    assert jobs.resume_waiting() == [a] and queue == [a] and jobs._jobs[a].status == "running"
    assert not jobs._jobs[a].waiting


def test_four_made_at_once_and_four_banked(monkeypatch):
    # Decision 111: films take a day or three, so several are made at once.
    from types import SimpleNamespace as N
    channel = N(key="why", documentary=N(parallel=4, ahead=4))
    for making, banked, room in ((3, 4, True), (4, 0, False), (2, 6, False), (0, 7, True)):
        monkeypatch.setattr(auto_films, "_in_hand", lambda c, m=making, b=banked: (m, b))
        assert auto_films._room_for_a_new_film(channel) is room


def test_activity_is_told_a_job_is_waiting_on_a_batch():
    # Decision 112: the Activity feed dropped these fields, so its
    # "Waiting on batch" label never showed.
    from web.blueprints import jobs as page
    job = {"id": "a", "channel_key": "why", "status": "running", "waiting": True, "waiting_since": 5.0,
           "seed": {"type": "production", "topic": "T", "subtopic_id": "t1", "stage": "stills"}}
    from web import create_app
    with create_app().test_request_context():
        row = page._for_activity(job, {"why": "Why"})
    assert row["waiting"] is True and row["waiting_since"] == 5.0 and row["film"] is True


def test_no_money_goes_on_a_film_that_cant_be_voiced(monkeypatch):
    # The owner, 27 Oct: "make sure that we dont spend any money on these
    # videos that are doomed to fail until our voice credits refresh".
    data = production.blank("t1", "t1")
    for s in ("pitch", "outline", "script"):
        data["stages"][s]["state"] = "approved"
    started = []
    monkeypatch.setattr(auto_films, "start", lambda channel, row, stage: started.append(stage))
    monkeypatch.setattr(production, "narration_still_to_voice", lambda d: 1500)
    room = {"ok": False}
    monkeypatch.setattr("core.voice_quota.has_room_for", lambda n, **k: room["ok"])
    monkeypatch.setattr("core.voice_quota.current", lambda force=False: object())
    doc = type("D", (), {"teasers": 2, "newsroom": False, "overseen": False})()
    channel = type("C", (), {"key": "why", "documentary": doc})()
    assert auto_films._act(channel, {"id": "t1", "title": "T"}, data, after_hours=False) == ""
    assert started == []                                         # no storyboard drawn
    room["ok"] = True
    assert auto_films._act(channel, {"id": "t1", "title": "T"}, data, after_hours=False)
    assert started == ["stills"]
