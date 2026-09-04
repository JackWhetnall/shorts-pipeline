"""
The topic syllabus: ordering, status, and the rules that keep a channel
from repeating itself.

Every model call is stubbed. The two things worth testing here are not
the quality of a generated list — that is a judgement, not an assertion —
but the bookkeeping around it, which is where silent damage happens: a
topic handed out twice, a discarded video's topic lost, a syllabus
half-written by a crash.
"""

from __future__ import annotations

import json

import pytest

from core import curriculum
from core.channels import ChannelConfig
from core.errors import PipelineError
from web.blueprints import curriculum as curriculum_web


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    return tmp_path


@pytest.fixture
def planned(isolated):
    """A three-unit syllabus with topics in the first two."""
    curriculum.start("c", "Testing things", [
        {"title": "Basics", "summary": "The obvious ground.",
         "level": "foundation", "target_topics": 3},
        {"title": "Middle", "summary": "Builds on the basics.",
         "level": "intermediate", "target_topics": 2},
        {"title": "Deep", "summary": "For enthusiasts.",
         "level": "specialist", "target_topics": 2},
    ])
    curriculum.add_topics("c", "u01", [
        {"title": "First thing", "angle": "a"},
        {"title": "Second thing", "angle": "b"},
        {"title": "Third thing", "angle": "c"},
    ])
    curriculum.add_topics("c", "u02", [
        {"title": "Fourth thing", "angle": "d"},
        {"title": "Fifth thing", "angle": "e"},
    ])
    return "c"


class TestBuilding:
    def test_a_channel_without_a_plan_reads_as_empty(self, isolated):
        assert curriculum.exists("nobody") is False
        assert curriculum.next_pending("nobody") is None
        assert curriculum.progress("nobody")["has_curriculum"] is False

    def test_units_are_numbered_in_the_order_given(self, isolated):
        data = curriculum.start("c", "S", [
            {"title": "A", "level": "foundation", "target_topics": 5},
            {"title": "B", "level": "advanced", "target_topics": 5},
        ])
        assert [u["id"] for u in data["units"]] == ["u01", "u02"]
        assert [u["title"] for u in data["units"]] == ["A", "B"]

    def test_an_unknown_level_becomes_intermediate_rather_than_being_stored(self, isolated):
        data = curriculum.start("c", "S", [
            {"title": "A", "level": "impossible", "target_topics": 5}])
        assert data["units"][0]["level"] == "intermediate"

    def test_topics_keep_the_order_they_were_written_in(self, planned):
        titles = [t["title"] for t in curriculum.topics("c")]
        assert titles == ["First thing", "Second thing", "Third thing",
                          "Fourth thing", "Fifth thing"]

    def test_duplicate_titles_are_dropped(self, planned):
        """The generator is told not to repeat, but 'told not to' is not a
        guarantee, and a duplicate topic is the exact failure this whole
        system exists to prevent."""
        curriculum.add_topics("c", "u03", [
            {"title": "First thing", "angle": "different angle, same topic"},
            {"title": "  SECOND THING  ", "angle": "case and spacing"},
            {"title": "Genuinely new", "angle": "x"},
        ])
        titles = [t["title"] for t in curriculum.topics("c")]
        assert titles.count("First thing") == 1
        assert len(titles) == 6
        assert "Genuinely new" in titles

    def test_units_fill_in_order(self, isolated):
        """Filling out of order would let the pending buffer jump ahead of
        the arc it was ordered into."""
        curriculum.start("c", "S", [
            {"title": "A", "level": "foundation", "target_topics": 2},
            {"title": "B", "level": "advanced", "target_topics": 2},
        ])
        assert curriculum.next_unfilled_unit("c")["id"] == "u01"
        curriculum.add_topics("c", "u01", [{"title": "x", "angle": ""}])
        assert curriculum.next_unfilled_unit("c")["id"] == "u02"
        curriculum.add_topics("c", "u02", [{"title": "y", "angle": ""}])
        assert curriculum.next_unfilled_unit("c") is None

    def test_adding_to_a_unit_that_does_not_exist_is_refused(self, planned):
        with pytest.raises(curriculum.CurriculumError):
            curriculum.add_topics("c", "u99", [{"title": "x", "angle": ""}])

    def test_a_damaged_file_names_itself(self, isolated):
        curriculum.CURRICULA_DIR.mkdir(parents=True, exist_ok=True)
        (curriculum.CURRICULA_DIR / "c.json").write_text("{not json")
        with pytest.raises(curriculum.CurriculumError) as caught:
            curriculum.load("c")
        assert "curricula/c.json" in caught.value.user_message

    def test_a_channel_key_cannot_escape_the_curricula_directory(self, isolated):
        from core.paths import PathTraversalError

        with pytest.raises(PathTraversalError):
            curriculum.path_for("../../etc/passwd")

    def test_saving_leaves_no_partial_file_behind(self, planned):
        """Written to a temporary path and replaced: this file is the
        record of what has already been published."""
        assert list(curriculum.CURRICULA_DIR.glob("*.tmp")) == []
        data = json.loads(curriculum.path_for("c").read_text(encoding="utf-8"))
        assert len(data["topics"]) == 5


class TestOrderAndClaiming:
    def test_next_pending_is_the_first_in_syllabus_order(self, planned):
        assert curriculum.next_pending("c")["title"] == "First thing"

    def test_claiming_advances_the_queue(self, planned):
        first = curriculum.claim("c")
        assert first["title"] == "First thing"
        assert curriculum.next_pending("c")["title"] == "Second thing"

    def test_claiming_the_same_id_twice_yields_two_different_topics(self, planned):
        """Queueing five videos captures the same 'next' topic in each
        seed. Without this, that is one topic made five times."""
        first = curriculum.claim("c", "t0001")
        second = curriculum.claim("c", "t0001")
        assert first["id"] == "t0001"
        assert second["id"] == "t0002"

    def test_a_deliberately_chosen_topic_is_honoured(self, planned):
        assert curriculum.claim("c", "t0004")["title"] == "Fourth thing"
        assert curriculum.next_pending("c")["title"] == "First thing"

    def test_claiming_an_exhausted_syllabus_returns_nothing(self, planned):
        for _ in range(5):
            curriculum.claim("c")
        assert curriculum.claim("c") is None
        assert curriculum.next_pending("c") is None

    def test_skipped_topics_are_passed_over(self, planned):
        curriculum.skip("c", "t0001", "too similar to something else")
        assert curriculum.next_pending("c")["title"] == "Second thing"

    def test_a_skipped_topic_can_be_put_back(self, planned):
        curriculum.skip("c", "t0001")
        curriculum.unskip("c", "t0001")
        assert curriculum.next_pending("c")["title"] == "First thing"

    def test_move_to_front_makes_one_topic_next(self, planned):
        curriculum.move_to_front("c", "t0005")
        assert curriculum.next_pending("c")["title"] == "Fifth thing"

    def test_move_to_front_leaves_the_rest_in_order(self, planned):
        curriculum.move_to_front("c", "t0005")
        curriculum.claim("c")
        assert [t["title"] for t in curriculum.topics("c", status="pending")] == [
            "First thing", "Second thing", "Third thing", "Fourth thing"]


class TestStatusFollowsTheVideo:
    def test_publishing_marks_the_topic_covered(self, planned):
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "first_thing")
        curriculum.mark_published("c", "first_thing")
        assert curriculum.find("c", "t0001")["status"] == curriculum.PUBLISHED

    def test_discarding_returns_the_topic_to_the_queue(self, planned):
        """A take that did not work is not a topic that has been covered.
        Losing it puts a permanent hole in the syllabus that nothing would
        ever surface."""
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "first_thing")
        assert curriculum.next_pending("c")["id"] == "t0002"

        curriculum.release("c", "first_thing")
        assert curriculum.next_pending("c")["id"] == "t0001"
        assert curriculum.find("c", "t0001")["video_stem"] == ""

    def test_releasing_a_published_topic_also_works(self, planned):
        """Un-publishing is a real action — clearing every link on a video
        makes it unpublished again."""
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "stem")
        curriculum.mark_published("c", "stem")
        curriculum.release("c", "stem")
        assert curriculum.find("c", "t0001")["status"] == curriculum.PENDING

    def test_releasing_an_unknown_video_is_harmless(self, planned):
        curriculum.release("c", "never_existed")
        assert curriculum.progress("c")["pending"] == 5


class TestProgress:
    def test_counts_every_status(self, planned):
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "s")
        curriculum.mark_published("c", "s")
        curriculum.claim("c", "t0002")
        curriculum.skip("c", "t0003")

        state = curriculum.progress("c")
        assert state["published"] == 1
        assert state["used"] == 1
        assert state["skipped"] == 1
        assert state["pending"] == 2
        assert state["done"] == 2

    def test_runway_assumes_two_videos_a_day(self, planned):
        assert curriculum.progress("c")["runway_days"] == 2

    def test_running_low_is_flagged_before_it_runs_out(self, planned):
        """Useful only in advance: running out stops generation dead."""
        assert curriculum.progress("c")["running_low"] is True

    def test_a_full_syllabus_is_not_flagged(self, isolated):
        curriculum.start("c", "S", [
            {"title": "A", "level": "foundation", "target_topics": 100}])
        curriculum.add_topics("c", "u01", [
            {"title": f"Topic {i}", "angle": ""} for i in range(100)])
        assert curriculum.progress("c")["running_low"] is False

    def test_units_with_topics_reports_per_unit_progress(self, planned):
        curriculum.claim("c", "t0001")
        units = curriculum.units_with_topics("c")
        assert units[0]["done"] == 1
        assert len(units[0]["topics"]) == 3
        assert units[2]["topics"] == []


class TestSeedSelection:
    """`fetch_seed` must stay free of side effects — it is called
    repeatedly while someone rerolls."""

    @pytest.fixture
    def channel(self):
        return ChannelConfig(
            key="c", channel_display_name="C", content_mode="topic",
            voice="v", style_prompt="p", topics=["a fallback topic"])

    def test_a_channel_without_a_plan_uses_its_topic_list(self, isolated, channel):
        from pipeline.run import fetch_seed

        seed = fetch_seed(channel)
        assert seed.topic == "a fallback topic"
        assert seed.topic_id == ""

    def test_a_channel_with_a_plan_takes_the_next_topic(self, planned, channel):
        from pipeline.run import fetch_seed

        seed = fetch_seed(channel)
        assert seed.topic == "First thing"
        assert seed.topic_id == "t0001"

    def test_fetching_a_seed_does_not_consume_the_topic(self, planned, channel):
        from pipeline.run import fetch_seed

        fetch_seed(channel)
        fetch_seed(channel)
        assert curriculum.progress("c")["pending"] == 5

    def test_an_exhausted_plan_says_so_rather_than_falling_back(self, planned, channel):
        """Silently reverting to the random list would undo the whole
        point without ever saying it had."""
        from core.errors import ConfigError
        from pipeline.run import fetch_seed

        for _ in range(5):
            curriculum.claim("c")
        with pytest.raises(ConfigError) as caught:
            fetch_seed(channel)
        assert "every topic" in caught.value.user_message

    def test_the_topic_id_survives_the_job_queue(self):
        from pipeline.plan import Seed

        seed = Seed(type="topic", topic="A thing", topic_id="t0042")
        assert Seed.from_jsonable(seed.to_jsonable()).topic_id == "t0042"


class TestGenerationPrompts:
    """The model call itself is stubbed; what is checked is what gets sent
    to it, since that is the part that decides whether the answer can be
    any good."""

    @pytest.fixture
    def channel(self):
        return ChannelConfig(key="c", channel_display_name="C",
                             content_mode="topic", voice="v",
                             style_prompt="Explain one idea about maths.")

    def test_the_outline_prompt_states_the_ordering_rules(self, channel, monkeypatch):
        from pipeline import curriculum_gen

        captured = {}

        def fake(system, user, schema, **kwargs):
            captured["system"] = " ".join(b.text for b in system)
            captured["user"] = user
            return {"subject": "Maths", "units": [
                {"title": "A", "summary": "", "level": "foundation",
                 "target_topics": 40}]}

        monkeypatch.setattr(curriculum_gen, "call_json", fake)
        curriculum_gen.plan_outline(channel, unit_count=25, total_topics=1000)

        assert "depend on an idea that has not appeared" in captured["system"]
        assert "Explain one idea about maths." in captured["system"]
        assert "25 units" in captured["user"]

    def test_an_empty_outline_is_an_error_not_an_empty_plan(self, channel, monkeypatch):
        from pipeline import curriculum_gen

        monkeypatch.setattr(curriculum_gen, "call_json",
                            lambda *a, **k: {"subject": "x", "units": []})
        with pytest.raises(PipelineError):
            curriculum_gen.plan_outline(channel)

    def test_a_short_outline_is_kept_rather_than_thrown_away(self, channel, monkeypatch):
        """Ordering is what matters; 23 units is as usable as 25, and
        failing over the number would discard a good answer."""
        from pipeline import curriculum_gen

        monkeypatch.setattr(curriculum_gen, "call_json", lambda *a, **k: {
            "subject": "x",
            "units": [{"title": str(i), "summary": "", "level": "foundation",
                       "target_topics": 40} for i in range(23)]})
        assert len(curriculum_gen.plan_outline(channel, 25)["units"]) == 23

    def test_topic_generation_is_told_what_already_exists(self, planned, channel,
                                                          monkeypatch):
        from pipeline import curriculum_gen

        captured = {}

        def fake(system, user, schema, **kwargs):
            captured["user"] = user
            captured["system"] = " ".join(b.text for b in system)
            return {"topics": []}

        monkeypatch.setattr(curriculum_gen, "call_json", fake)
        data = curriculum.load("c")
        curriculum_gen.write_unit_topics(channel, data, data["units"][1])

        assert "First thing" in captured["user"]
        assert "Do not repeat" in captured["user"]
        # The whole outline goes along, so a unit knows its place in the arc.
        assert "Deep" in captured["system"]

    def test_a_unit_is_not_told_about_topics_from_later_units(self, planned, channel,
                                                              monkeypatch):
        """Sending the whole syllabus would grow this prompt without bound
        as the channel runs, and a unit cannot repeat what is not written."""
        from pipeline import curriculum_gen

        captured = {}
        monkeypatch.setattr(curriculum_gen, "call_json",
                            lambda system, user, schema, **k:
                            (captured.update(user=user), {"topics": []})[1])
        data = curriculum.load("c")
        curriculum_gen.write_unit_topics(channel, data, data["units"][0])

        assert "First thing" in captured["user"]
        assert "Fourth thing" not in captured["user"]

    def test_a_single_call_is_never_asked_for_too_many_topics(self, planned, channel,
                                                              monkeypatch):
        """Asking for 80 in one response is how a unit silently ends
        halfway through."""
        from pipeline import curriculum_gen

        captured = {}
        monkeypatch.setattr(curriculum_gen, "call_json",
                            lambda system, user, schema, **k:
                            (captured.update(user=user), {"topics": []})[1])
        data = curriculum.load("c")
        data["units"][2]["target_topics"] = 200
        curriculum_gen.write_unit_topics(channel, data, data["units"][2])

        assert f"Write {curriculum_gen.MAX_TOPICS_PER_CALL} topics" in captured["user"]

    def test_no_schema_uses_array_bounds(self):
        """The API rejects minItems/maxItems other than 0 and 1, which is
        an HTTP 400 rather than a bad answer."""
        from pipeline import curriculum_gen

        def walk(node):
            if isinstance(node, dict):
                assert "minItems" not in node and "maxItems" not in node
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(curriculum_gen._outline_schema())
        walk(curriculum_gen._topics_schema())


class TestWebRoutes:
    @pytest.fixture
    def client(self, isolated, tmp_path, monkeypatch):
        from core.channels import channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        channel = ChannelConfig(
            key="c", channel_display_name="C", content_mode="topic",
            voice="v", style_prompt="Explain one idea.", topics=["fallback"])
        channel.output_dir = str(tmp_path / "out")
        write_raw({"c": channel_to_sparse_dict(channel)}, path)

        app = create_app()
        app.config.update(TESTING=True)
        with app.test_client() as test_client:
            yield test_client

    def _csrf(self, client):
        html = client.get("/").get_data(as_text=True)
        marker = 'name="csrf-token" content="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_page_renders_before_a_plan_exists(self, client):
        html = client.get("/channels/c/curriculum").get_data(as_text=True)
        assert "Design the outline" in html

    def test_page_states_the_cost_before_spending_it(self, client):
        """Every other paid action in this project says the figure first."""
        html = client.get("/channels/c/curriculum").get_data(as_text=True)
        assert "dollars" in html

    def test_page_renders_a_plan_in_progress(self, client, planned):
        html = client.get("/channels/c/curriculum").get_data(as_text=True)
        assert "First thing" in html
        assert "Basics" in html

    def test_outline_generation_requires_csrf(self, client):
        assert client.post("/api/channels/c/curriculum/outline",
                           json={}).status_code == 400

    def test_replacing_a_used_plan_is_refused_without_confirmation(self, client, planned):
        """The units are what every topic is positioned against; replacing
        them would orphan the record of what has been made."""
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "s")
        curriculum.mark_published("c", "s")

        response = client.post("/api/channels/c/curriculum/outline", json={},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 400
        assert "already made 1" in response.get_json()["error"]

    def test_replacing_an_unused_plan_is_allowed(self, client, planned, monkeypatch):
        from pipeline import curriculum_gen

        monkeypatch.setattr(curriculum_gen, "plan_outline", lambda *a, **k: {
            "subject": "New", "units": [{"title": "Fresh", "summary": "",
                                         "level": "foundation", "target_topics": 10}]})
        response = client.post("/api/channels/c/curriculum/outline", json={},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        assert curriculum.load("c")["units"][0]["title"] == "Fresh"

    def test_unit_counts_outside_the_sane_range_are_clamped(self, client, monkeypatch):
        from pipeline import curriculum_gen

        captured = {}

        def fake(channel, unit_count, total_topics, subject_hint=""):
            captured.update(unit_count=unit_count, total_topics=total_topics)
            return {"subject": "x", "units": [{"title": "A", "summary": "",
                                               "level": "foundation",
                                               "target_topics": 1}]}

        monkeypatch.setattr(curriculum_gen, "plan_outline", fake)
        client.post("/api/channels/c/curriculum/outline",
                    json={"unit_count": 9999, "total_topics": -5},
                    headers={"X-CSRF-Token": self._csrf(client)})
        assert captured["unit_count"] == curriculum_web.MAX_UNITS
        assert captured["total_topics"] == curriculum_web.MIN_TOPICS

    def test_a_generation_failure_returns_a_sentence(self, client, monkeypatch):
        from pipeline import curriculum_gen

        def explode(*a, **k):
            raise PipelineError("boom", user_message="Couldn't design a plan.")

        monkeypatch.setattr(curriculum_gen, "plan_outline", explode)
        response = client.post("/api/channels/c/curriculum/outline", json={},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 502
        assert response.get_json()["error"] == "Couldn't design a plan."

    def test_filling_writes_the_next_unfilled_unit(self, client, planned, monkeypatch):
        from pipeline import curriculum_gen

        monkeypatch.setattr(curriculum_gen, "write_unit_topics", lambda *a, **k: [
            {"title": "Sixth thing", "angle": "f"}])
        response = client.post("/api/channels/c/curriculum/fill", json={"units": 1},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.get_json()["units"] == ["Deep"]
        assert curriculum.next_pending("c")["title"] == "First thing"
        assert curriculum.progress("c")["total"] == 6

    def test_filling_a_complete_syllabus_says_so(self, client, planned, monkeypatch):
        from pipeline import curriculum_gen

        monkeypatch.setattr(curriculum_gen, "write_unit_topics",
                            lambda *a, **k: [{"title": "x", "angle": ""}])
        client.post("/api/channels/c/curriculum/fill", json={"units": 1},
                    headers={"X-CSRF-Token": self._csrf(client)})
        response = client.post("/api/channels/c/curriculum/fill", json={"units": 1},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 400

    def test_a_partial_multi_unit_fill_keeps_what_worked(self, client, isolated,
                                                         monkeypatch):
        """Three units requested, the second one fails: the first must
        still be saved rather than the whole call being thrown away."""
        from pipeline import curriculum_gen

        curriculum.start("c", "S", [
            {"title": "U" + str(i), "summary": "", "level": "foundation",
             "target_topics": 2} for i in range(3)])

        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise PipelineError("boom", user_message="Failed.")
            return [{"title": "Topic " + str(calls["n"]), "angle": ""}]

        monkeypatch.setattr(curriculum_gen, "write_unit_topics", flaky)
        response = client.post("/api/channels/c/curriculum/fill", json={"units": 3},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        assert response.get_json()["units"] == ["U0"]
        assert curriculum.progress("c")["total"] == 1

    def test_skip_and_put_back_round_trip(self, client, planned):
        token = self._csrf(client)
        client.post("/channels/c/curriculum/t0001/skip",
                    data={"note": "dull", "csrf_token": token})
        assert curriculum.find("c", "t0001")["status"] == curriculum.SKIPPED
        assert curriculum.find("c", "t0001")["note"] == "dull"

        client.post("/channels/c/curriculum/t0001/unskip", data={"csrf_token": token})
        assert curriculum.find("c", "t0001")["status"] == curriculum.PENDING

    def test_acting_on_a_topic_that_does_not_exist_is_a_404(self, client, planned):
        assert client.post("/channels/c/curriculum/t9999/skip",
                           data={"csrf_token": self._csrf(client)}).status_code == 404

    def test_deleting_the_plan_reverts_to_the_topic_list(self, client, planned):
        from pipeline.run import fetch_seed
        from web.helpers import all_channels

        client.post("/channels/c/curriculum/delete",
                    data={"csrf_token": self._csrf(client)})
        assert not curriculum.exists("c")
        assert fetch_seed(all_channels()["c"]).topic == "fallback"

    def test_the_dashboard_links_to_the_plan_for_topic_channels(self, client, planned):
        html = client.get("/channels/c").get_data(as_text=True)
        assert "/channels/c/curriculum" in html
        assert "5 left" in html
