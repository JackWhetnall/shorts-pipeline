"""
Batch mode (pipeline.llm.batched): the hourly background run's calls go
through the Message Batches API at half price, and come back checked,
retried and costed exactly as a direct call would.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core import costs
from core.errors import ExternalServiceError
from pipeline import llm
from tests.test_failure_modes import SCHEMA, FakeResponse, text_response, thinking_only_response


class Stopped(Exception):
    """The app stopping mid-wait."""


class FakeBatches:
    """messages.batches: each create answers with the next queued result.
    A result is a FakeResponse (succeeded) or a SimpleNamespace standing
    in for an errored/expired result."""

    def __init__(self, results, polls_before_end=1, stop_on_poll=False):
        self.queue = list(results)
        self.created = []
        self.answers = {}
        self.polls = {}
        self.polls_before_end = polls_before_end
        self.stop_on_poll = stop_on_poll

    def create(self, requests):
        batch_id = f"msgbatch_{len(self.created)}"
        self.created.append(requests)
        self.answers[batch_id] = (requests[0]["custom_id"], self.queue.pop(0))
        return SimpleNamespace(id=batch_id)

    def retrieve(self, batch_id):
        if self.stop_on_poll:
            raise Stopped()
        self.polls[batch_id] = self.polls.get(batch_id, 0) + 1
        ended = self.polls[batch_id] > self.polls_before_end
        return SimpleNamespace(processing_status="ended" if ended else "in_progress")

    def results(self, batch_id):
        custom_id, answer = self.answers[batch_id]
        result = (SimpleNamespace(type="succeeded", message=answer)
                  if isinstance(answer, FakeResponse) else answer)
        yield SimpleNamespace(custom_id=custom_id, result=result)


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "llm_batches.json"
    monkeypatch.setattr(llm, "LLM_BATCH_JOURNAL_PATH", path)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    return path


def fake_client(monkeypatch, batches: FakeBatches):
    client = MagicMock()
    client.messages.batches = batches
    monkeypatch.setattr(llm, "client", lambda: client)
    return client


def test_outside_batch_mode_calls_go_direct(monkeypatch, journal):
    batches = FakeBatches([])
    client = fake_client(monkeypatch, batches)
    client.messages.create.return_value = text_response('{"ok": true}')

    assert llm.call_json("sys", "user", SCHEMA, operation="test") == {"ok": True}
    assert batches.created == []


def test_batch_mode_sends_a_batch_and_records_half_price(monkeypatch, journal):
    batches = FakeBatches([text_response('{"ok": true}')], polls_before_end=2)
    client = fake_client(monkeypatch, batches)

    with llm.batched():
        assert llm.call_json("sys", "user", SCHEMA, operation="test", model="claude-sonnet-5") == {"ok": True}

    client.messages.create.assert_not_called()
    assert len(batches.created) == 1
    params = batches.created[0][0]["params"]
    assert params["output_config"]["format"]["schema"] == SCHEMA       # the same request as a direct call
    record = costs.read_records()[-1]
    assert record["batch"] is True
    full = (100 * 2.00 + 50 * 10.00) / 1_000_000                      # FakeUsage at Sonnet 5's price
    assert record["cost_usd"] == pytest.approx(full / 2)
    assert json.loads(journal.read_text()) == {}                       # collected, so forgotten


def test_batch_mode_ends_with_the_block(monkeypatch, journal):
    fake_client(monkeypatch, FakeBatches([]))
    with llm.batched():
        assert llm.in_batch_mode()
    assert not llm.in_batch_mode()


def test_a_run_stopped_mid_wait_picks_its_batch_up_instead_of_paying_again(monkeypatch, journal):
    first = FakeBatches([text_response('{"ok": true}')], stop_on_poll=True)
    fake_client(monkeypatch, first)
    with llm.batched(), pytest.raises(ExternalServiceError):
        llm.call_json("sys", "user", SCHEMA, operation="test")
    assert len(first.created) == 1
    assert list(json.loads(journal.read_text()).values())[0]["batch"] == "msgbatch_0"

    # The app restarts; the same request is made again.
    second = FakeBatches([])
    second.answers = first.answers
    fake_client(monkeypatch, second)
    with llm.batched():
        assert llm.call_json("sys", "user", SCHEMA, operation="test") == {"ok": True}
    assert second.created == []


def test_truncated_batch_result_is_retried_with_more_room(monkeypatch, journal):
    batches = FakeBatches([thinking_only_response(), text_response('{"ok": true}')])
    fake_client(monkeypatch, batches)

    with llm.batched():
        assert llm.call_json("sys", "user", SCHEMA, operation="test", max_tokens=1000) == {"ok": True}

    budgets = [requests[0]["params"]["max_tokens"] for requests in batches.created]
    assert budgets == [1000, 3000]


def test_a_refusal_in_a_batch_is_not_retried(monkeypatch, journal):
    batches = FakeBatches([FakeResponse([], stop_reason="refusal")])
    fake_client(monkeypatch, batches)
    with llm.batched(), pytest.raises(llm.RefusedResponse):
        llm.call_json("sys", "user", SCHEMA, operation="test")
    assert len(batches.created) == 1


def test_an_invalid_request_reports_a_pipeline_bug(monkeypatch, journal):
    error = SimpleNamespace(type="errored", error=SimpleNamespace(
        error=SimpleNamespace(type="invalid_request_error", message="bad schema")))
    fake_client(monkeypatch, FakeBatches([error]))
    with llm.batched(), pytest.raises(ExternalServiceError) as exc:
        llm.call_json("sys", "user", SCHEMA, operation="test")
    assert exc.value.status == 400
    assert "bad schema" not in exc.value.user_message


def test_an_expired_request_says_the_next_run_tries_again(monkeypatch, journal):
    fake_client(monkeypatch, FakeBatches([SimpleNamespace(type="expired")]))
    with llm.batched(), pytest.raises(ExternalServiceError) as exc:
        llm.call_json("sys", "user", SCHEMA, operation="test")
    assert "next hourly run" in exc.value.user_message


def test_run_together_waits_side_by_side_in_batch_mode(journal):
    both_waiting = threading.Barrier(2, timeout=5)

    def call(n):
        assert llm.in_batch_mode()           # carried onto the worker thread
        both_waiting.wait()                  # would time out if run one after another
        return n

    with llm.batched():
        assert llm.run_together([lambda: call(1), lambda: call(2)]) == [1, 2]


def test_run_together_runs_in_order_outside_batch_mode():
    seen = []
    assert llm.run_together([lambda: seen.append(1) or "a", lambda: seen.append(2) or "b"]) == ["a", "b"]
    assert seen == [1, 2]


def test_the_hourly_run_is_batched(monkeypatch):
    from pipeline.facts import keep
    seen = []
    monkeypatch.setattr(keep, "_keep_up_work", lambda conn, say, quizzes: seen.append(llm.in_batch_mode()))
    monkeypatch.setattr(keep, "start", lambda action, work: work(None, print) or True)
    monkeypatch.setattr(keep, "_last_auto", 0.0)
    channel = SimpleNamespace(format="quiz", archived=False)

    assert keep.keep_up({"pub": channel})
    assert seen == [True]


def test_cost_of_a_batch_call_is_half():
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000,
                            cache_read_input_tokens=0, cache_creation_input_tokens=0)
    assert costs.record_claude("t", "claude-sonnet-5", usage).cost_usd == pytest.approx(12.0)
    assert costs.record_claude("t", "claude-sonnet-5", usage, batch=True).cost_usd == pytest.approx(6.0)


def test_sorting_in_batch_mode_reports_progress_only_from_the_run_thread(monkeypatch):
    """`say` writes to the run's database connection; the side-by-side
    threads must not call it."""
    from pipeline.facts import scope
    callers = []
    monkeypatch.setattr(scope, "SORT_CHUNK", 2)
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"results": [
        {"number": 1, "categories": ["Science"]}, {"number": 2, "categories": ["Science"]}]})
    rows = [{"id": n, "question": f"Q{n}?", "answer": "A"} for n in range(6)]

    with llm.batched():
        out = scope._verdicts(rows, "- Science", say=lambda m: callers.append(threading.get_ident()))

    assert out == {n: ["Science"] for n in range(6)}
    assert callers and set(callers) == {threading.get_ident()}


# --- videos made ahead of their slot ------------------------------------

@pytest.fixture
def job_registry(monkeypatch, tmp_path):
    from core import jobs
    monkeypatch.setattr(jobs, "JOB_STATE_DIR", tmp_path)
    monkeypatch.setattr(jobs, "_persist", lambda job_id: None)
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(jobs, "_queue", [])
    return jobs


def test_a_video_made_ahead_is_made_at_batch_prices(job_registry):
    jobs = job_registry
    jobs._jobs["a"] = jobs.Job(id="a", channel_key="pub", seed={}, ahead=True)
    jobs._jobs["m"] = jobs.Job(id="m", channel_key="pub", seed={})
    assert jobs._made_ahead("a", llm.in_batch_mode) is True
    assert jobs._made_ahead("m", llm.in_batch_mode) is False


def test_a_video_made_ahead_hurries_once_someone_queues_their_own(job_registry):
    """Jobs run one at a time: a video started by hand mustn't wait out
    another video's batch waits."""
    jobs = job_registry
    jobs._jobs["a"] = jobs.Job(id="a", channel_key="pub", seed={}, ahead=True)
    jobs._jobs["later"] = jobs.Job(id="later", channel_key="other", seed={}, status="queued", ahead=True)
    jobs._queue.append("later")

    def make():
        before = llm.in_batch_mode()
        jobs._jobs["mine"] = jobs.Job(id="mine", channel_key="third", seed={}, status="queued")
        jobs._queue.append("mine")
        return before, llm.in_batch_mode()

    assert jobs._made_ahead("a", make) == (True, False)


def test_the_scheduler_starts_its_videos_ahead(monkeypatch):
    from core import jobs, scheduler
    import pipeline.run
    started = []
    monkeypatch.setattr(jobs, "active_jobs", lambda: {})
    monkeypatch.setattr(jobs, "start_job", lambda key, seed, ahead=False: started.append(ahead))
    monkeypatch.setattr(scheduler, "generation_block", lambda key, channel, active=None: None)
    monkeypatch.setattr(pipeline.run, "fetch_seed", lambda channel: SimpleNamespace(to_jsonable=dict))

    assert scheduler.fill_buffers({"pub": SimpleNamespace()}) == ["pub"]
    assert started == [True]


def test_a_video_retried_by_hand_is_no_longer_made_ahead(job_registry, monkeypatch):
    jobs = job_registry
    monkeypatch.setattr(jobs, "install", lambda: None)
    monkeypatch.setattr(jobs, "_refuse_if_stale", lambda: None)
    monkeypatch.setattr(jobs, "_spawn", lambda *a: None)
    jobs._jobs["a"] = jobs.Job(id="a", channel_key="pub", seed={}, status="error", ahead=True)
    jobs.retry_job("a")
    assert jobs._jobs["a"].ahead is False


def test_a_video_made_ahead_doesnt_teach_the_eta_how_long_videos_take():
    from core import job_eta
    record = {"status": "done", "ahead": True, "stage_entered": {"1": 0.0, "2": 10.0}, "finished_at": 20.0,
              "seed": {}}
    assert job_eta._durations(record) == {}
    assert job_eta._durations({**record, "ahead": False})
