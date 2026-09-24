"""
Job records outlive the checkpoints they sit beside.

Regression: clearing a successful job's checkpoints deleted the job's
whole folder, which also held its record and its log. Every successful
job erased its own history, so the Activity page forgot it on restart and
core.job_eta, which estimates from this installation's finished jobs,
never kept a single measurement.
"""

from __future__ import annotations

import time

import pytest

from core import job_context, jobs


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(job_context, "JOB_STATE_DIR", tmp_path)
    monkeypatch.setattr(jobs, "JOB_STATE_DIR", tmp_path)
    monkeypatch.setattr(jobs, "_jobs", {})
    return tmp_path


def test_clearing_checkpoints_keeps_the_record_and_the_log(state_dir):
    job = jobs.Job(id="j1", channel_key="c", seed={}, status="done",
                   finished_at=time.time(), stage_entered={"1": 1.0, "2": 5.0})
    jobs._jobs["j1"] = job
    jobs._persist("j1")
    jobs._log_path("j1").write_text("a log line\n", encoding="utf-8")

    token = job_context.set_job_id("j1")
    try:
        job_context.save_json_checkpoint("script", {"segments": []})
        assert job_context.load_json_checkpoint("script") == {"segments": []}
        job_context.clear_checkpoints("j1")
        assert job_context.load_json_checkpoint("script") is None
    finally:
        job_context._current_job_id.reset(token)

    assert jobs._record_path("j1").exists()
    assert jobs._log_path("j1").exists()

    jobs._jobs.clear()
    assert jobs.load_persisted_jobs() == 1
    assert jobs._jobs["j1"].stage_entered == {"1": 1.0, "2": 5.0}
