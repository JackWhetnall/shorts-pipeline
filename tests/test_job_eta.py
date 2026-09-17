"""
`core.job_eta`: "how much longer?", answered from this installation's own
finished jobs.

The estimate is allowed to be wrong — it is an estimate. What it is not
allowed to do is learn from records that measure nothing (a retry that
reused its checkpoints, a job left running overnight), quote a channel's
history at a channel that doesn't have any, or tell someone a job that
has already overrun its estimate still has the same time left as when it
started. Those are the tests here.
"""

from __future__ import annotations

import pytest

from core import job_eta

BASE = 1_000_000.0


def _finished(channel="c", per_stage=(10, 20, 30, 40, 50), start=BASE, **overrides):
    """A completed job record with real stage timings."""
    entered, t = {}, start
    for i, seconds in enumerate(per_stage, start=1):
        entered[str(i)] = t
        t += seconds
    return {"id": "j", "channel_key": channel, "status": "done",
            "started_at": start, "finished_at": t, "stage_entered": entered,
            **overrides}


class TestWhatCountsAsASample:
    def test_a_finished_job_gives_one_duration_per_stage(self):
        assert job_eta._durations(_finished()) == {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}

    def test_a_retry_measures_nothing_and_is_excluded(self):
        """A retry reuses its checkpoints, so its stages complete in
        seconds. Learning from it would teach the estimator that a video
        takes four seconds to make."""
        assert job_eta._durations(_finished(retried=True)) == {}

    def test_a_failed_job_is_excluded(self):
        assert job_eta._durations(_finished(status="error")) == {}

    def test_an_implausibly_long_stage_is_dropped(self):
        """A machine that slept mid-render produces a stage duration that
        is a fact about the laptop lid, not about the pipeline."""
        durations = job_eta._durations(_finished(per_stage=(10, 20, 999_999, 40, 50)))
        assert 3 not in durations
        assert durations[4] == 40

    def test_sample_count_counts_only_usable_records(self):
        history = [_finished(), _finished(retried=True), _finished(status="error")]
        assert job_eta.sample_count(history) == 1


class TestStageEstimate:
    def test_no_history_falls_back_to_the_baseline(self):
        assert job_eta.stage_seconds([]) == job_eta.BASELINE

    def test_a_channels_own_history_wins_once_there_is_enough_of_it(self):
        """Segment count and target length are per channel and drive most
        of the variance, so a channel's own numbers beat the average
        across every channel on the machine."""
        history = ([_finished("mine", (1, 1, 1, 1, 1))] * job_eta.MIN_SAMPLES
                   + [_finished("other", (99, 99, 99, 99, 99))] * 10)
        assert job_eta.stage_seconds(history, "mine")[3] == 1

    def test_a_channel_with_too_few_samples_borrows_the_rest(self):
        """Falling back stage by stage rather than all-or-nothing: two
        local measurements are still worth having."""
        history = [_finished("mine", (1, 1, 1, 1, 1)),
                   _finished("mine", (1, 1, 1, 1, 1)),
                   _finished("other", (99, 99, 99, 99, 99)),
                   _finished("other", (99, 99, 99, 99, 99))]
        # Two local samples, below MIN_SAMPLES, so both sets are pooled
        # and the answer sits between them rather than discarding either.
        assert 1 < job_eta.stage_seconds(history, "mine")[3] < 99

    def test_one_slow_job_does_not_move_the_estimate_much(self):
        """Median, not mean: a single stalled download shouldn't rewrite
        every future estimate."""
        history = [_finished("c", (10, 10, 10, 10, 10)) for _ in range(5)]
        history.append(_finished("c", (10, 10, 600, 10, 10)))
        assert job_eta.stage_seconds(history, "c")[3] == 10


class TestRemaining:
    def _history(self):
        return [_finished("c", (10, 20, 30, 40, 50)) for _ in range(job_eta.MIN_SAMPLES)]

    def test_a_job_not_yet_started_has_the_whole_run_left(self):
        job = {"channel_key": "c", "status": "running", "stage": 0}
        assert job_eta.remaining_seconds(job, self._history(), now=BASE) == 150

    def test_only_the_stages_still_to_come_are_counted(self):
        """Stage 4 of 5, just started: 40 seconds of assembly plus 50 of
        finishing. Not the whole 150 scaled by "4 of 5"."""
        job = {"channel_key": "c", "status": "running", "stage": 4,
               "stage_entered": {"4": BASE}}
        assert job_eta.remaining_seconds(job, self._history(), now=BASE) == 90

    def test_time_already_spent_in_this_stage_comes_off(self):
        job = {"channel_key": "c", "status": "running", "stage": 4,
               "stage_entered": {"4": BASE}}
        assert job_eta.remaining_seconds(job, self._history(), now=BASE + 30) == 60

    def test_a_stage_running_long_shrinks_to_zero_rather_than_going_negative(self):
        """It must not start counting up, and it must not claim the
        remaining stages have gone away either."""
        job = {"channel_key": "c", "status": "running", "stage": 4,
               "stage_entered": {"4": BASE}}
        assert job_eta.remaining_seconds(job, self._history(), now=BASE + 10_000) == 50


class TestQueue:
    def test_a_queued_job_waits_for_everything_in_front_of_it(self):
        """Only one job runs at a time, so the queue IS the estimate."""
        history = [_finished("c", (10, 20, 30, 40, 50))
                   for _ in range(job_eta.MIN_SAMPLES)]
        active = [
            {"channel_key": "c", "status": "running", "stage": 5,
             "stage_entered": {"5": BASE}},
            {"channel_key": "c", "status": "queued"},
            {"channel_key": "c", "status": "queued"},
        ]
        annotated = job_eta.annotate(active, history, now=BASE)
        assert [j["eta_seconds"] for j in annotated] == [50, 200, 350]

    def test_annotate_does_not_mutate_the_jobs_it_is_given(self):
        job = {"channel_key": "c", "status": "queued"}
        job_eta.annotate([job], [], now=BASE)
        assert "eta_seconds" not in job


class TestDescribe:
    @pytest.mark.parametrize("seconds, expected", [
        (5, "under a minute"),
        (44, "under a minute"),
        (90, "about 2 minutes"),
        (60, "about 1 minute"),
        (400, "about 7 minutes"),
        (1000, "about 15 minutes"),
    ])
    def test_rounds_coarsely_enough_to_be_honest(self, seconds, expected):
        assert job_eta.describe(seconds) == expected

    def test_nothing_to_say_when_there_is_no_estimate(self):
        assert job_eta.describe(None) == ""
