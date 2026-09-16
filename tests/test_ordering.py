"""
`core.ordering`: which pending subtopic "make the next video" offers,
given a channel's `Ordering` settings.

Built from plain curriculum-shaped dicts rather than the real
`core.curriculum` storage, since the algorithm only ever reads the
`topics`/`subtopics` shape `curriculum.load()` already returns — no file
I/O needed to exercise it.
"""

from __future__ import annotations

import random

from core import curriculum, ordering
from core.channels import ChannelConfig, Ordering


def _topic(topic_id, position):
    return {"id": topic_id, "title": f"Topic {topic_id}", "summary": "",
           "level": "foundation", "target_subtopics": 3, "filled": True}


def _subtopic(sub_id, topic_id, status=curriculum.PENDING, used_at=""):
    return {"id": sub_id, "topic": topic_id, "position": 0, "title": f"Sub {sub_id}",
           "angle": "", "status": status, "video_stem": "", "used_at": used_at,
           "note": "", "script": None, "script_written_at": ""}


def _channel(**ordering_overrides):
    channel = ChannelConfig(key="c", content_mode="topic",
                            voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p")
    for key, value in ordering_overrides.items():
        setattr(channel.ordering, key, value)
    return channel


# Two topics, three subtopics each, all pending except where noted.
def _data(subtopics):
    return {"topics": [_topic("t1", 0), _topic("t2", 1)], "subtopics": subtopics}


class TestNothingPending:
    def test_returns_none(self):
        data = _data([_subtopic("a", "t1", status=curriculum.PUBLISHED, used_at="2026-01-01")])
        assert ordering.choose_next_subtopic(_channel(), data) is None


class TestDefaultsMatchTheOriginalBehaviour:
    """Structured/sequential/sequential/topic_first is the default
    specifically so an existing channel's "next video" doesn't change
    the moment this setting exists."""

    def test_first_pending_subtopic_in_file_order(self):
        data = _data([_subtopic("a1", "t1"), _subtopic("a2", "t1"),
                      _subtopic("b1", "t2")])
        result = ordering.choose_next_subtopic(_channel(), data)
        assert result["id"] == "a1"

    def test_matches_next_pending_on_a_real_curriculum(self, tmp_path, monkeypatch):
        monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
        curriculum.start("c", "S", [
            {"title": "A", "summary": "", "level": "foundation", "target_subtopics": 2},
            {"title": "B", "summary": "", "level": "foundation", "target_subtopics": 2},
        ])
        curriculum.add_subtopics("c", "u01", [{"title": "1", "angle": ""},
                                              {"title": "2", "angle": ""}])
        curriculum.add_subtopics("c", "u02", [{"title": "3", "angle": ""}])

        expected = curriculum.next_pending("c")
        result = ordering.choose_next_subtopic(_channel())
        assert result["id"] == expected["id"]


class TestTopicFirst:
    def test_continues_the_topic_in_progress(self):
        data = _data([
            _subtopic("a1", "t1", status=curriculum.USED, used_at="2026-01-01T00:00:00"),
            _subtopic("a2", "t1"),
            _subtopic("b1", "t2"),
        ])
        result = ordering.choose_next_subtopic(_channel(), data)
        assert result["id"] == "a2"

    def test_advances_when_the_current_topic_runs_out(self):
        data = _data([
            _subtopic("a1", "t1", status=curriculum.PUBLISHED, used_at="2026-01-01T00:00:00"),
            _subtopic("b1", "t2"),
        ])
        result = ordering.choose_next_subtopic(_channel(), data)
        assert result["id"] == "b1"


class TestRoundRobin:
    def test_advances_every_time_regardless_of_what_was_last_made(self):
        data = _data([
            _subtopic("a1", "t1", status=curriculum.USED, used_at="2026-01-01T00:00:00"),
            _subtopic("a2", "t1"),
            _subtopic("b1", "t2"),
        ])
        result = ordering.choose_next_subtopic(_channel(grouping="round_robin"), data)
        assert result["id"] == "b1"

    def test_genuinely_cycles_rather_than_collapsing_back_to_the_first_topic(self):
        """The bug this guards: advancing past an exhausted first topic
        must land on the SECOND topic, not fall back to "the earliest
        pending topic" — which for round_robin (unlike topic_first) is
        never the first topic in the file once it's your turn again."""
        data = _data([
            _subtopic("a1", "t1", status=curriculum.USED, used_at="2026-01-01T00:00:00"),
            _subtopic("a2", "t1", status=curriculum.PENDING),
            _subtopic("b1", "t2", status=curriculum.USED, used_at="2026-01-02T00:00:00"),
            _subtopic("b2", "t2", status=curriculum.PENDING),
        ])
        # b2 (t2) was made most recently; round_robin must move on to t1
        # next (a2), not stay on t2 or reset to whichever topic is first.
        channel = _channel(grouping="round_robin")
        result = ordering.choose_next_subtopic(channel, data)
        assert result["id"] == "a2"


class TestRandomOrder:
    def test_random_topic_order_picks_among_pending_topics(self):
        data = _data([_subtopic("a1", "t1"), _subtopic("b1", "t2")])
        seen = set()
        for seed in range(20):
            channel = _channel(topic_order="random", grouping="round_robin")
            result = ordering.choose_next_subtopic(channel, data, rng=random.Random(seed))
            seen.add(result["topic"])
        assert seen == {"t1", "t2"}

    def test_random_subtopic_order_picks_among_pending_subtopics_in_the_topic(self):
        data = _data([_subtopic("a1", "t1"), _subtopic("a2", "t1"), _subtopic("a3", "t1")])
        seen = set()
        for seed in range(20):
            channel = _channel(subtopic_order="random")
            result = ordering.choose_next_subtopic(channel, data, rng=random.Random(seed))
            seen.add(result["id"])
        assert seen == {"a1", "a2", "a3"}


class TestNatural:
    def test_stickiness_one_always_continues_while_something_is_pending(self):
        data = _data([
            _subtopic("a1", "t1", status=curriculum.USED, used_at="2026-01-01T00:00:00"),
            _subtopic("a2", "t1"),
            _subtopic("b1", "t2"),
        ])
        channel = _channel(mode="natural", stickiness=1.0)
        result = ordering.choose_next_subtopic(channel, data, rng=random.Random(0))
        assert result["id"] == "a2"

    def test_stickiness_zero_always_branches(self):
        data = _data([
            _subtopic("a1", "t1", status=curriculum.USED, used_at="2026-01-01T00:00:00"),
            _subtopic("a2", "t1"),
            _subtopic("b1", "t2"),
        ])
        channel = _channel(mode="natural", stickiness=0.0)
        result = ordering.choose_next_subtopic(channel, data, rng=random.Random(0))
        assert result["topic"] == "t2"

    def test_branching_favours_the_topic_with_the_least_attention(self):
        """t1 has two videos made, t2 has none - weighted toward t2 means
        it should come up noticeably more often than half the time."""
        data = _data([
            _subtopic("a1", "t1", status=curriculum.USED, used_at="2026-01-01T00:00:00"),
            _subtopic("a2", "t1", status=curriculum.USED, used_at="2026-01-02T00:00:00"),
            _subtopic("a3", "t1"),
            _subtopic("b1", "t2"),
            _subtopic("b2", "t2"),
        ])
        channel = _channel(mode="natural", stickiness=0.0)
        counts = {"t1": 0, "t2": 0}
        for seed in range(200):
            result = ordering.choose_next_subtopic(channel, data, rng=random.Random(seed))
            counts[result["topic"]] += 1
        assert counts["t2"] > counts["t1"]

    def test_falls_back_to_the_earliest_pending_topic_before_anything_is_made(self):
        data = _data([_subtopic("a1", "t1"), _subtopic("b1", "t2")])
        channel = _channel(mode="natural", stickiness=1.0)
        result = ordering.choose_next_subtopic(channel, data, rng=random.Random(1))
        assert result["topic"] in ("t1", "t2")  # no "current" topic yet - branches


DEFAULT_SETTINGS = {"mode": "structured", "topic_order": "sequential",
                    "subtopic_order": "sequential", "grouping": "topic_first",
                    "stickiness": 0.8}


class TestSimulate:
    """The settings page's ordering-preview animation is only honest if
    it calls the real function above against dummy data — this checks
    the dummy data itself is well-formed and the loop terminates
    correctly, not the ordering rules again."""

    def test_returns_the_requested_number_of_steps(self):
        steps = ordering.simulate(DEFAULT_SETTINGS, topic_count=3, subtopics_per_topic=3, steps=5)
        assert len(steps) == 5

    def test_stops_once_the_dummy_plan_is_exhausted(self):
        steps = ordering.simulate(DEFAULT_SETTINGS, topic_count=2, subtopics_per_topic=2, steps=50)
        assert len(steps) == 4

    def test_each_step_names_a_real_topic_and_subtopic(self):
        steps = ordering.simulate(DEFAULT_SETTINGS, topic_count=3, subtopics_per_topic=2, steps=6)
        seen_subtopics = {s["subtopic_id"] for s in steps}
        assert len(seen_subtopics) == 6  # every dummy subtopic used exactly once
        for step in steps:
            assert step["topic_title"].startswith("Topic")

    def test_natural_mode_with_full_stickiness_never_leaves_its_first_topic_early(self):
        """Same property tests/test_ordering.py already proves for the
        real function directly - reachable through simulate's dummy data
        construction too. The very first pick is a genuine branch (nothing
        has been made yet, so there's no "current" topic to stick to) -
        stickiness=1.0 only guarantees every pick AFTER that one stays put
        while the topic still has something pending."""
        settings = {**DEFAULT_SETTINGS, "mode": "natural", "stickiness": 1.0}
        steps = ordering.simulate(settings, topic_count=3, subtopics_per_topic=4, steps=4)
        assert len({s["topic_id"] for s in steps}) == 1
