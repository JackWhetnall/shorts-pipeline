"""
A failed attempt the owner can see, understand and discard.

The owner ran out of Anthropic credit. The failure said the request was
malformed (a bug in the pipeline), adding credit appeared not to help
(the key's organisation was still at zero), and the failed attempt could
be neither discarded nor got away from: Create video showed it every time.
Also, the launch checklist said "20 of 5 reviewed".
"""

from __future__ import annotations

import pytest

from core import jobs, launch
from core.errors import JobError
from pipeline import llm


class _Rejected(Exception):
    status_code = 400


def test_running_out_of_credit_is_said_plainly_not_called_a_bug():
    error = llm._as_service_error(_Rejected(
        "Error code: 400 - {'error': {'message': 'Your credit balance is too low to access the "
        "Anthropic API.'}}"))
    assert "run out of credit" in error.user_message and "bug" not in error.user_message


def test_another_rejected_request_is_still_reported_as_a_bug():
    assert "bug in the pipeline" in llm._as_service_error(_Rejected("max_tokens: too large")).user_message


@pytest.fixture
def failed(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "JOB_STATE_DIR", tmp_path)
    monkeypatch.setattr(jobs, "_persist", lambda job_id: None)
    monkeypatch.setattr(jobs.job_context, "clear_checkpoints", lambda job_id: None)
    job = jobs.Job(id="j1", channel_key="quiz", seed={}, status="error", finished_at=5.0)
    monkeypatch.setattr(jobs, "_jobs", {"j1": job})
    return job


def test_a_discarded_failure_stops_being_offered(failed):
    assert jobs.latest_failed_for_channel("quiz")["id"] == "j1"
    assert [j["id"] for j in jobs.recent_finished()] == ["j1"]
    jobs.dismiss_job("j1")
    assert failed.dismissed
    assert jobs.latest_failed_for_channel("quiz") is None and jobs.recent_finished() == []


def test_only_a_failed_attempt_can_be_discarded(failed):
    failed.status = "running"
    with pytest.raises(JobError):
        jobs.dismiss_job("j1")
    with pytest.raises(JobError):
        jobs.dismiss_job("nope")


def test_the_checklist_says_which_condition_isnt_met():
    assert launch._shadow_detail(3, 3, False) == "3 of 5 reviewed so far; the checks agreed with you on 3."
    low = launch._shadow_detail(20, 15, False)
    assert "20 of 5" not in low and "15 of 20 (75%)" in low and "80%" in low
    assert launch._shadow_detail(20, 18, True) == "The checks agreed with you on 18 of 20."


# --- the APIs page's key test --------------------------------------------------

def test_the_key_test_reports_what_the_provider_says(monkeypatch):
    from core import services
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-abcdefghijklmnopqrstXwAA")

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                raise _Rejected("Your credit balance is too low to access the Anthropic API.")
    monkeypatch.setattr(llm, "client", lambda: Client)
    result = services.test_key("anthropic")
    assert not result["ok"] and "run out of credit" in result["message"]

    class Fine:
        class messages:
            @staticmethod
            def create(**kw):
                return object()
    monkeypatch.setattr(llm, "client", lambda: Fine)
    assert services.test_key("anthropic")["ok"]
    assert services.key_tail(services.SERVICES[0]) == "XwAA"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert "isn't set" in services.test_key("anthropic")["message"]
    assert not services.test_key("elevenlabs")["ok"]


# --- batch prices by default, Accelerate to make it now (6 Oct, decision 072) --

@pytest.fixture
def queue(monkeypatch):
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(jobs, "_queue", [])
    monkeypatch.setattr(jobs, "_persist", lambda job_id: None)
    monkeypatch.setattr(jobs, "_spawn", lambda *a: None)
    monkeypatch.setattr(jobs, "install", lambda: None)
    monkeypatch.setattr(jobs, "_refuse_if_stale", lambda: None)
    return jobs


def test_a_video_is_made_at_batch_prices_unless_asked_for_now(queue):
    first = queue.start_job("a", {})
    assert queue._jobs[first].ahead
    now = queue.start_job("b", {}, ahead=False)
    assert not queue._jobs[now].ahead


def test_accelerate_puts_it_next_and_at_full_speed(queue):
    running = queue.start_job("a", {})
    second = queue.start_job("b", {})
    third = queue.start_job("c", {})
    assert queue._queue == [second, third]
    assert not queue.someone_waiting()                  # the running one can take its time
    queue.accelerate(third)
    assert queue._queue == [third, second]
    job = queue._jobs[third]
    assert not job.ahead and job.accelerated
    assert queue.someone_waiting()                      # so the running one stops batching


def test_a_running_video_accelerated_stops_batching_its_next_call(queue, monkeypatch):
    from pipeline import llm
    running = queue.start_job("a", {})
    seen = []

    def make():
        seen.append(llm.in_batch_mode())
        queue.accelerate(running)
        seen.append(llm.in_batch_mode())
        return "made"
    assert queue._made_ahead(running, make) == "made"
    assert seen == [True, False]
    assert "accelerated" in queue._jobs[running].notes[-1]


def test_accelerating_a_finished_job_says_so(queue):
    with pytest.raises(JobError):
        queue.accelerate("nope")


def test_the_create_page_asks_for_now_and_activity_offers_accelerate():
    from pathlib import Path
    js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert 'now: Boolean(document.getElementById("make-now")' in js
    assert "/accelerate" in js
