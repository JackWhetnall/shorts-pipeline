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
         "level": "foundation", "target_subtopics": 3},
        {"title": "Middle", "summary": "Builds on the basics.",
         "level": "intermediate", "target_subtopics": 2},
        {"title": "Deep", "summary": "For enthusiasts.",
         "level": "specialist", "target_subtopics": 2},
    ])
    curriculum.add_subtopics("c", "u01", [
        {"title": "First thing", "angle": "a"},
        {"title": "Second thing", "angle": "b"},
        {"title": "Third thing", "angle": "c"},
    ])
    curriculum.add_subtopics("c", "u02", [
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
            {"title": "A", "level": "foundation", "target_subtopics": 5},
            {"title": "B", "level": "advanced", "target_subtopics": 5},
        ])
        assert [u["id"] for u in data["topics"]] == ["u01", "u02"]
        assert [u["title"] for u in data["topics"]] == ["A", "B"]

    def test_an_unknown_level_becomes_intermediate_rather_than_being_stored(self, isolated):
        data = curriculum.start("c", "S", [
            {"title": "A", "level": "impossible", "target_subtopics": 5}])
        assert data["topics"][0]["level"] == "intermediate"

    def test_topics_keep_the_order_they_were_written_in(self, planned):
        titles = [t["title"] for t in curriculum.subtopics("c")]
        assert titles == ["First thing", "Second thing", "Third thing",
                          "Fourth thing", "Fifth thing"]

    def test_duplicate_titles_are_dropped(self, planned):
        """The generator is told not to repeat, but 'told not to' is not a
        guarantee, and a duplicate topic is the exact failure this whole
        system exists to prevent."""
        curriculum.add_subtopics("c", "u03", [
            {"title": "First thing", "angle": "different angle, same topic"},
            {"title": "  SECOND THING  ", "angle": "case and spacing"},
            {"title": "Genuinely new", "angle": "x"},
        ])
        titles = [t["title"] for t in curriculum.subtopics("c")]
        assert titles.count("First thing") == 1
        assert len(titles) == 6
        assert "Genuinely new" in titles

    def test_units_fill_in_order(self, isolated):
        """Filling out of order would let the pending buffer jump ahead of
        the arc it was ordered into."""
        curriculum.start("c", "S", [
            {"title": "A", "level": "foundation", "target_subtopics": 2},
            {"title": "B", "level": "advanced", "target_subtopics": 2},
        ])
        assert curriculum.next_unfilled_topic("c")["id"] == "u01"
        curriculum.add_subtopics("c", "u01", [{"title": "x", "angle": ""}])
        assert curriculum.next_unfilled_topic("c")["id"] == "u02"
        curriculum.add_subtopics("c", "u02", [{"title": "y", "angle": ""}])
        assert curriculum.next_unfilled_topic("c") is None

    def test_adding_to_a_unit_that_does_not_exist_is_refused(self, planned):
        with pytest.raises(curriculum.CurriculumError):
            curriculum.add_subtopics("c", "u99", [{"title": "x", "angle": ""}])

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
        assert len(data["subtopics"]) == 5


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
        assert [t["title"] for t in curriculum.subtopics("c", status="pending")] == [
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

    def test_a_claim_that_never_became_a_video_can_be_released(self, planned):
        """The failure case release() can't reach: generation claimed a
        subtopic, then errored before any video existed to discard. Without
        this, a crashed run leaves a permanently used subtopic with nothing
        to discard and no way back to pending."""
        curriculum.claim("c", "t0001")
        curriculum.release_unattached("c", "t0001")
        assert curriculum.find("c", "t0001")["status"] == curriculum.PENDING
        assert curriculum.next_pending("c")["id"] == "t0001"

    def test_release_unattached_leaves_a_real_video_alone(self, planned):
        """Once a claim became a real file, undoing it is a discard
        decision, not something a failure handler should do automatically."""
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "first_thing")
        curriculum.release_unattached("c", "t0001")
        assert curriculum.find("c", "t0001")["status"] == curriculum.USED

    def test_release_unattached_ignores_a_subtopic_that_was_never_claimed(self, planned):
        curriculum.release_unattached("c", "t0001")
        assert curriculum.find("c", "t0001")["status"] == curriculum.PENDING


class TestScripts:
    """A script is written independently of any video — see
    docs/decisions/023-script-studio.md. What matters here is that it
    survives everything that happens to the video built from it."""

    SCRIPT = {"citation": None,
             "segments": [{"text": "hi", "shot_brief": "b", "keywords": ["k"],
                          "start": 0.0, "end": 0.0}],
             "title_options": ["T"], "description_body": "d"}

    def test_a_new_subtopic_has_no_script(self, planned):
        assert curriculum.find("c", "t0001")["script"] is None

    def test_set_script_writes_it(self, planned):
        curriculum.set_script("c", "t0001", self.SCRIPT)
        row = curriculum.find("c", "t0001")
        assert row["script"] == self.SCRIPT
        assert row["script_written_at"]

    def test_set_script_overwrites_a_previous_one(self, planned):
        curriculum.set_script("c", "t0001", self.SCRIPT)
        rewritten = {**self.SCRIPT, "description_body": "rewritten"}
        curriculum.set_script("c", "t0001", rewritten)
        assert curriculum.find("c", "t0001")["script"]["description_body"] == "rewritten"

    def test_set_script_does_not_change_status(self, planned):
        """Writing survives independently of whether a video has ever been
        made from it — the two are different lifecycles."""
        curriculum.set_script("c", "t0001", self.SCRIPT)
        assert curriculum.find("c", "t0001")["status"] == curriculum.PENDING

    def test_discarding_a_video_leaves_its_script_untouched(self, planned):
        curriculum.set_script("c", "t0001", self.SCRIPT)
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "first_thing")

        curriculum.release("c", "first_thing")
        row = curriculum.find("c", "t0001")
        assert row["status"] == curriculum.PENDING
        assert row["script"] == self.SCRIPT

    def test_a_failed_run_leaves_its_script_untouched(self, planned):
        curriculum.set_script("c", "t0001", self.SCRIPT)
        curriculum.claim("c", "t0001")

        curriculum.release_unattached("c", "t0001")
        row = curriculum.find("c", "t0001")
        assert row["status"] == curriculum.PENDING
        assert row["script"] == self.SCRIPT


class TestCoveredTitles:
    """`covered_titles` is what `context_scope` actually drives — how far
    back a script's continuity context reaches. `planned` gives three
    topics in file order: Basics (u01, 3 subtopics), Middle (u02, 2),
    Deep (u03, unfilled)."""

    def _publish(self, subtopic_id, stem):
        curriculum.claim("c", subtopic_id)
        curriculum.attach_video("c", subtopic_id, stem)
        curriculum.mark_published("c", stem)

    def test_topic_scope_matches_covered_in_topic(self, planned):
        self._publish("t0001", "s1")
        self._publish("t0004", "s4")
        result = curriculum.covered_titles("c", "u02", "topic")
        assert [r["id"] for r in result] == ["t0004"]

    def test_recent_topics_reaches_backward_by_file_order(self, planned):
        self._publish("t0001", "s1")
        self._publish("t0002", "s2")
        self._publish("t0004", "s4")
        result = curriculum.covered_titles("c", "u02", "recent_topics", recent_topics=1)
        assert {r["id"] for r in result} == {"t0001", "t0002", "t0004"}

    def test_recent_topics_respects_the_count(self, planned):
        self._publish("t0001", "s1")
        self._publish("t0004", "s4")
        result = curriculum.covered_titles("c", "u02", "recent_topics", recent_topics=0)
        assert {r["id"] for r in result} == {"t0004"}

    def test_all_reaches_every_topic_up_to_this_one(self, planned):
        self._publish("t0001", "s1")
        self._publish("t0004", "s4")
        result = curriculum.covered_titles("c", "u02", "all")
        assert {r["id"] for r in result} == {"t0001", "t0004"}

    def test_all_never_reaches_forward(self, planned):
        """A topic after this one hasn't been taught yet - reaching
        forward would leak spoilers from later in the syllabus."""
        self._publish("t0001", "s1")
        result = curriculum.covered_titles("c", "u01", "all")
        assert {r["id"] for r in result} == {"t0001"}

    def test_an_unknown_scope_falls_back_to_topic(self, planned):
        self._publish("t0001", "s1")
        self._publish("t0004", "s4")
        result = curriculum.covered_titles("c", "u02", "not_a_real_scope")
        assert [r["id"] for r in result] == ["t0004"]

    def test_a_stale_topic_id_falls_back_to_topic_scope_harmlessly(self, planned):
        assert curriculum.covered_titles("c", "u99", "all") == []


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
            {"title": "A", "level": "foundation", "target_subtopics": 100}])
        curriculum.add_subtopics("c", "u01", [
            {"title": f"Topic {i}", "angle": ""} for i in range(100)])
        assert curriculum.progress("c")["running_low"] is False

    def test_topics_with_subtopics_reports_per_topic_progress(self, planned):
        curriculum.claim("c", "t0001")
        units = curriculum.topics_with_subtopics("c")
        assert units[0]["done"] == 1
        assert len(units[0]["subtopics"]) == 3
        assert units[2]["subtopics"] == []


class TestSeedSelection:
    """`fetch_seed` must stay free of side effects — it is called
    repeatedly while someone rerolls."""

    @pytest.fixture
    def channel(self):
        return ChannelConfig(
            key="c", channel_display_name="C", content_mode="topic",
            voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p", topics=["a fallback topic"])

    def test_a_channel_without_a_plan_uses_its_topic_list(self, isolated, channel):
        from pipeline.run import fetch_seed

        seed = fetch_seed(channel)
        assert seed.topic == "a fallback topic"
        assert seed.topic_id == ""

    def test_a_topic_channel_with_neither_a_plan_nor_a_list_fails_readably(
            self, isolated):
        """This used to crash raw: random.choice([]) raises IndexError
        with no user_message, reachable the moment anything calls
        fetch_seed on a channel in this state - which the style-tone
        picker's preview does, ahead of the usual validate() gate."""
        from core.errors import ConfigError
        from pipeline.run import fetch_seed

        channel = ChannelConfig(key="c", channel_display_name="C",
                                content_mode="topic",
                                voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p",
                                topics=[])
        with pytest.raises(ConfigError) as caught:
            fetch_seed(channel)
        assert "no topics yet" in caught.value.user_message

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
        assert "every subtopic" in caught.value.user_message

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
                             content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                             style_prompt="Explain one idea about maths.")

    def test_the_outline_prompt_states_the_ordering_rules(self, channel, monkeypatch):
        from pipeline import curriculum_gen

        captured = {}

        def fake(system, user, schema, **kwargs):
            captured["system"] = " ".join(b.text for b in system)
            captured["user"] = user
            return {"subject": "Maths", "topics": [
                {"title": "A", "summary": "", "level": "foundation",
                 "target_subtopics": 40}]}

        monkeypatch.setattr(curriculum_gen, "call_json", fake)
        curriculum_gen.plan_outline(channel, topic_count=25, total_subtopics=1000)

        assert "depend on an idea that has not appeared" in captured["system"]
        assert "Explain one idea about maths." in captured["system"]
        assert "25 topics" in captured["user"]

    def test_an_empty_outline_is_an_error_not_an_empty_plan(self, channel, monkeypatch):
        from pipeline import curriculum_gen

        monkeypatch.setattr(curriculum_gen, "call_json",
                            lambda *a, **k: {"subject": "x", "topics": []})
        with pytest.raises(PipelineError):
            curriculum_gen.plan_outline(channel)

    def test_a_short_outline_is_kept_rather_than_thrown_away(self, channel, monkeypatch):
        """Ordering is what matters; 37 topics is as usable as 40, and
        failing over the number would discard a good answer."""
        from pipeline import curriculum_gen

        monkeypatch.setattr(curriculum_gen, "call_json", lambda *a, **k: {
            "subject": "x",
            "topics": [{"title": str(i), "summary": "", "level": "foundation",
                        "target_subtopics": 25} for i in range(37)]})
        assert len(curriculum_gen.plan_outline(channel, 40)["topics"]) == 37

    def test_topic_generation_is_told_what_already_exists(self, planned, channel,
                                                          monkeypatch):
        from pipeline import curriculum_gen

        captured = {}

        def fake(system, user, schema, **kwargs):
            captured["user"] = user
            captured["system"] = " ".join(b.text for b in system)
            return {"subtopics": []}

        monkeypatch.setattr(curriculum_gen, "call_json", fake)
        data = curriculum.load("c")
        curriculum_gen.write_subtopics(channel, data, data["topics"][1])

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
                            (captured.update(user=user), {"subtopics": []})[1])
        data = curriculum.load("c")
        curriculum_gen.write_subtopics(channel, data, data["topics"][0])

        assert "First thing" in captured["user"]
        assert "Fourth thing" not in captured["user"]

    def test_a_single_call_is_never_asked_for_too_many_subtopics(self, planned, channel,
                                                              monkeypatch):
        """Asking for 80 in one response is how a unit silently ends
        halfway through."""
        from pipeline import curriculum_gen

        captured = {}
        monkeypatch.setattr(curriculum_gen, "call_json",
                            lambda system, user, schema, **k:
                            (captured.update(user=user), {"subtopics": []})[1])
        data = curriculum.load("c")
        data["topics"][2]["target_subtopics"] = 200
        curriculum_gen.write_subtopics(channel, data, data["topics"][2])

        assert f"Write {curriculum_gen.MAX_SUBTOPICS_PER_CALL} subtopics" in captured["user"]

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
        walk(curriculum_gen._subtopics_schema())


class TestWebRoutes:
    @pytest.fixture
    def client(self, isolated, tmp_path, monkeypatch):
        from core.channels import channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        channel = ChannelConfig(
            key="c", channel_display_name="C", content_mode="topic",
            voice="21m00Tcm4TlvDq8ikWAM", style_prompt="Explain one idea.", topics=["fallback"])
        channel.output_dir = str(tmp_path / "out" / channel.key)
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
        """Every other paid action in this project says the figure first —
        now a live cost-dot tooltip rather than static prose, but the real
        figure must still be present before anything is spent."""
        html = client.get("/channels/c/curriculum").get_data(as_text=True)
        assert 'id="curriculum-cost-dot"' in html
        assert "data-cost-outline=" in html and "data-cost-per-topic=" in html

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
            "subject": "New", "topics": [{"title": "Fresh", "summary": "",
                                         "level": "foundation", "target_subtopics": 10}]})
        response = client.post("/api/channels/c/curriculum/outline", json={},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        assert curriculum.load("c")["topics"][0]["title"] == "Fresh"

    def test_topic_counts_outside_the_sane_range_are_clamped(self, client, monkeypatch):
        from pipeline import curriculum_gen

        captured = {}

        def fake(channel, topic_count, total_subtopics, subject_hint=""):
            captured.update(topic_count=topic_count, total_subtopics=total_subtopics)
            return {"subject": "x", "topics": [{"title": "A", "summary": "",
                                               "level": "foundation",
                                               "target_subtopics": 1}]}

        monkeypatch.setattr(curriculum_gen, "plan_outline", fake)
        client.post("/api/channels/c/curriculum/outline",
                    json={"topic_count": 9999, "total_subtopics": -5},
                    headers={"X-CSRF-Token": self._csrf(client)})
        assert captured["topic_count"] == curriculum_web.MAX_TOPICS
        assert captured["total_subtopics"] == curriculum_web.MIN_SUBTOPICS

    def test_a_generation_failure_returns_a_sentence(self, client, monkeypatch):
        from pipeline import curriculum_gen

        def explode(*a, **k):
            raise PipelineError("boom", user_message="Couldn't design a plan.")

        monkeypatch.setattr(curriculum_gen, "plan_outline", explode)
        response = client.post("/api/channels/c/curriculum/outline", json={},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 502
        assert response.get_json()["error"] == "Couldn't design a plan."

    def test_filling_writes_the_next_unfilled_topic(self, client, planned, monkeypatch):
        from pipeline import curriculum_gen

        monkeypatch.setattr(curriculum_gen, "write_subtopics", lambda *a, **k: [
            {"title": "Sixth thing", "angle": "f"}])
        response = client.post("/api/channels/c/curriculum/fill", json={"count": 1},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.get_json()["topics"] == ["Deep"]
        assert curriculum.next_pending("c")["title"] == "First thing"
        assert curriculum.progress("c")["total"] == 6

    def test_filling_a_complete_syllabus_says_so(self, client, planned, monkeypatch):
        from pipeline import curriculum_gen

        monkeypatch.setattr(curriculum_gen, "write_subtopics",
                            lambda *a, **k: [{"title": "x", "angle": ""}])
        client.post("/api/channels/c/curriculum/fill", json={"count": 1},
                    headers={"X-CSRF-Token": self._csrf(client)})
        response = client.post("/api/channels/c/curriculum/fill", json={"count": 1},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 400

    def test_a_partial_multi_topic_fill_keeps_what_worked(self, client, isolated,
                                                         monkeypatch):
        """Three units requested, the second one fails: the first must
        still be saved rather than the whole call being thrown away."""
        from pipeline import curriculum_gen

        curriculum.start("c", "S", [
            {"title": "U" + str(i), "summary": "", "level": "foundation",
             "target_subtopics": 2} for i in range(3)])

        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise PipelineError("boom", user_message="Failed.")
            return [{"title": "Topic " + str(calls["n"]), "angle": ""}]

        monkeypatch.setattr(curriculum_gen, "write_subtopics", flaky)
        response = client.post("/api/channels/c/curriculum/fill", json={"count": 3},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        assert response.get_json()["topics"] == ["U0"]
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
        assert "topics left" in html

    def test_the_home_page_warns_before_a_channel_runs_out(self, client, planned):
        """Running out stops generation dead, so the warning is only
        useful in advance."""
        html = client.get("/").get_data(as_text=True)
        assert "Running low on topics" in html
        assert "5 left" in html

    def test_no_warning_when_there_is_plenty_of_runway(self, client, isolated):
        curriculum.start("c", "S", [
            {"title": "A", "summary": "", "level": "foundation",
             "target_subtopics": 100}])
        curriculum.add_subtopics("c", "u01", [
            {"title": "Topic " + str(i), "angle": ""} for i in range(100)])
        assert "Running low on topics" not in client.get("/").get_data(as_text=True)

    # --- script studio --------------------------------------------------

    def test_scripts_page_renders_before_any_are_written(self, client, planned):
        html = client.get("/channels/c/curriculum/u01/scripts").get_data(as_text=True)
        assert "First thing" in html

    def test_scripts_page_404s_for_an_unknown_topic(self, client, planned):
        assert client.get("/channels/c/curriculum/u99/scripts").status_code == 404

    def test_write_scripts_stores_real_scripts_on_real_subtopics(self, client, planned, monkeypatch):
        from pipeline import script_gen

        monkeypatch.setattr(script_gen, "write_scripts", lambda channel, topic, subs: [
            {"subtopic_id": s["id"],
             "script": {"citation": None,
                       "segments": [{"text": f"about {s['title']}", "shot_brief": "b",
                                    "keywords": ["k"], "start": 0.0, "end": 0.0}],
                       "title_options": ["T"], "description_body": "d"}}
            for s in subs])

        response = client.post("/api/channels/c/curriculum/u01/write-scripts", json={},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        assert set(response.get_json()["scripted"]) == {"t0001", "t0002", "t0003"}
        row = curriculum.find("c", "t0001")
        assert row["script"]["segments"][0]["text"] == "about First thing"

    def test_write_scripts_skips_subtopics_that_already_have_one(self, client, planned, monkeypatch):
        from pipeline import script_gen

        curriculum.set_script("c", "t0001", {"citation": None, "segments": [], "title_options": [],
                                             "description_body": ""})
        captured = {}

        def fake_write(channel, topic, subs):
            captured["ids"] = [s["id"] for s in subs]
            return [{"subtopic_id": s["id"],
                    "script": {"citation": None,
                              "segments": [{"text": "x", "shot_brief": "", "keywords": [],
                                           "start": 0.0, "end": 0.0}],
                              "title_options": [], "description_body": ""}}
                   for s in subs]

        monkeypatch.setattr(script_gen, "write_scripts", fake_write)
        client.post("/api/channels/c/curriculum/u01/write-scripts", json={},
                    headers={"X-CSRF-Token": self._csrf(client)})
        assert "t0001" not in captured["ids"]
        assert set(captured["ids"]) == {"t0002", "t0003"}

    def test_write_scripts_says_so_when_nothing_is_left(self, client, planned):
        for sub_id in ("t0001", "t0002", "t0003"):
            curriculum.set_script("c", sub_id, {"citation": None, "segments": [],
                                                "title_options": [], "description_body": ""})
        response = client.post("/api/channels/c/curriculum/u01/write-scripts", json={},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 400

    def test_regenerate_script_overwrites_in_place(self, client, planned, monkeypatch):
        from pipeline import script_gen

        curriculum.set_script("c", "t0001", {"citation": None,
                                             "segments": [{"text": "old", "shot_brief": "",
                                                          "keywords": [], "start": 0.0, "end": 0.0}],
                                             "title_options": [], "description_body": ""})
        monkeypatch.setattr(script_gen, "regenerate_script", lambda *a, **k: {
            "citation": None,
            "segments": [{"text": "new", "shot_brief": "", "keywords": [], "start": 0.0, "end": 0.0}],
            "title_options": [], "description_body": ""})

        response = client.post("/api/channels/c/curriculum/t0001/regenerate-script",
                               json={"instruction": "make it new"},
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        assert curriculum.find("c", "t0001")["script"]["segments"][0]["text"] == "new"

    def test_regenerate_script_requires_csrf(self, client, planned):
        assert client.post("/api/channels/c/curriculum/t0001/regenerate-script",
                           json={}).status_code == 400

    def test_edit_script_saves_and_redirects(self, client, planned):
        response = client.post(
            "/channels/c/curriculum/t0001/edit-script",
            data={"segment_text": ["Hand-written line one.", "Hand-written line two."],
                 "segment_shot_brief": ["a candle", "a road"],
                 "segment_keywords": ["candle, wax", "road, dusk"],
                 "title_options": "A Title\nAnother Title",
                 "description_body": "A description.",
                 "csrf_token": self._csrf(client)})
        assert response.status_code == 302
        row = curriculum.find("c", "t0001")
        assert row["script"]["segments"][0]["text"] == "Hand-written line one."
        assert row["script"]["segments"][1]["keywords"] == ["road", "dusk"]
        assert row["script"]["title_options"] == ["A Title", "Another Title"]

    def test_edit_script_with_no_segments_does_not_blank_an_existing_one(self, client, planned):
        curriculum.set_script("c", "t0001", {"citation": None,
                                             "segments": [{"text": "keep me", "shot_brief": "",
                                                          "keywords": [], "start": 0.0, "end": 0.0}],
                                             "title_options": [], "description_body": ""})
        client.post("/channels/c/curriculum/t0001/edit-script",
                    data={"segment_text": [""], "csrf_token": self._csrf(client)})
        assert curriculum.find("c", "t0001")["script"]["segments"][0]["text"] == "keep me"


class TestCreateVideoTable:
    """web.blueprints.channels.create_video: one chosen video with the
    button that makes it, and the whole plan to change it from.

    Regression: it was a table of eight topics beside a separate random
    pick, clicking a topic re-rolled the pick rather than following the
    click, and "Make next" did nothing visible on a random-order channel."""

    @pytest.fixture
    def client(self, isolated, tmp_path, monkeypatch):
        from core.channels import channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        channel = ChannelConfig(
            key="c", channel_display_name="C", content_mode="topic",
            voice="21m00Tcm4TlvDq8ikWAM", style_prompt="Explain one idea.", topics=["fallback"])
        channel.output_dir = str(tmp_path / "out" / channel.key)
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

    def test_a_flat_topic_list_channel_has_no_plan_picker(self, client):
        html = client.get("/channels/c/create").get_data(as_text=True)
        assert 'id="chosen-video"' not in html and "getSeed(" in html

    def test_every_topic_and_waiting_video_is_offered(self, client, planned):
        html = client.get("/channels/c/create").get_data(as_text=True)
        assert 'id="chosen-video"' in html
        for title in ("Basics", "Middle", "Deep", "First thing", "Fifth thing"):
            assert title in html
        assert "Random from this topic" in html and "Write its videos" in html  # Deep is unwritten

    def test_make_now_arrives_with_that_video_chosen(self, client, planned):
        sub = curriculum.subtopics("c", topic_id="u02")[1]
        html = client.get(f"/channels/c/create?subtopic_id={sub['id']}").get_data(as_text=True)
        assert f'data-initial-subtopic="{sub["id"]}"' in html

    def test_a_pick_is_followed(self, client, planned):
        token = self._csrf(client)
        sub = curriculum.subtopics("c", topic_id="u02")[1]
        exact = client.post("/api/channels/c/seed", json={"subtopic_id": sub["id"]},
                            headers={"X-CSRF-Token": token}).get_json()
        assert exact["seed"]["topic_id"] == sub["id"] and exact["topic_title"] == "Middle"
        for _ in range(5):
            within = client.post("/api/channels/c/seed", json={"topic_id": "u02", "mode": "random"},
                                 headers={"X-CSRF-Token": token}).get_json()
            assert curriculum.find("c", within["seed"]["topic_id"])["topic"] == "u02"

    def test_up_next_wins_even_on_a_random_channel(self, client, planned):
        from core import ordering
        from core.channels import load_channels
        channel = load_channels()["c"]
        channel.ordering.topic_order = channel.ordering.subtopic_order = "random"
        sub = curriculum.subtopics("c", topic_id="u02")[1]
        curriculum.move_to_front("c", sub["id"])
        assert all(ordering.choose_next_subtopic(channel)["id"] == sub["id"] for _ in range(5))
        curriculum.claim("c", sub["id"])
        assert curriculum.load("c").get("up_next") is None

    def test_ordering_preview_returns_the_requested_number_of_steps(self, client):
        response = client.post(
            "/api/channels/c/ordering-preview", json={},
            headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        assert len(response.get_json()["steps"]) > 0

    def test_ordering_preview_reflects_unsaved_form_values(self, client):
        """The whole point is trying a setting before committing to it -
        this must use exactly the settings posted, not the channel's
        saved ones."""
        response = client.post(
            "/api/channels/c/ordering-preview",
            json={"mode": "natural", "stickiness": 1.0},
            headers={"X-CSRF-Token": self._csrf(client)})
        steps = response.get_json()["steps"]
        # stickiness=1.0: every step after the first genuine branch stays
        # on the same topic while it has anything pending.
        assert len({s["topic_id"] for s in steps[:3]}) == 1

    def test_ordering_preview_requires_csrf(self, client):
        assert client.post("/api/channels/c/ordering-preview", json={}).status_code == 400

    def test_ordering_preview_falls_back_safely_on_junk_values(self, client):
        response = client.post(
            "/api/channels/c/ordering-preview",
            json={"mode": "not_a_real_mode", "stickiness": "not_a_number"},
            headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200


class TestChannelIsolation:
    """A channel must never be able to see another channel's videos.

    This is not hypothetical. The create form pre-filled the output
    directory with "output/" + the key, and on the new-channel page the
    key is empty at render time — so submitting it unchanged pointed the
    channel at the output ROOT, and its gallery listed every other
    channel's videos as its own.
    """

    def _channel(self, output_dir):
        from core.channels import ChannelConfig

        channel = ChannelConfig(
            key="mine", content_mode="topic", voice="abcdefghij0123456789",
            style_prompt="p", topics=["t"])
        channel.output_dir = output_dir
        return channel

    @pytest.mark.parametrize("shared", ["output", "output/", "output//", "output\\"])
    def test_the_shared_output_root_is_refused(self, shared):
        from core.errors import ConfigError

        with pytest.raises(ConfigError) as caught:
            self._channel(shared).validate()
        assert "every other channel" in str(caught.value)

    def test_the_project_root_is_refused(self):
        from core.errors import ConfigError

        with pytest.raises(ConfigError):
            self._channel(".").validate()

    def test_an_empty_directory_falls_back_to_the_key(self):
        channel = self._channel("")
        channel.validate()
        assert channel.output_dir == "output/mine"

    def test_a_normal_directory_is_kept(self):
        channel = self._channel("output/mine")
        channel.validate()
        assert channel.output_dir == "output/mine"

    def test_a_deliberate_custom_directory_is_still_allowed(self):
        """Pointing a channel at an existing folder is a real, if rare,
        thing to want. Only the shared root is refused."""
        channel = self._channel("output/archive/mine")
        channel.validate()
        assert channel.output_dir == "output/archive/mine"

    def test_the_form_cannot_set_it_at_all(self):
        """It is derived from the key. A form that carries it is a form
        that can get it wrong."""
        from core.channels import ChannelConfig
        from web.forms import apply_channel_form

        channel = ChannelConfig(key="mine", content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                                style_prompt="p", topics=["t"])
        before = channel.output_dir
        apply_channel_form(channel, {"output_dir": "output/"})
        assert channel.output_dir == before


class TestVoiceIdValidation:
    """A voice that isn't a voice fails minutes into a render, after a
    script has already been paid for."""

    def _channel(self, voice):
        from core.channels import ChannelConfig

        return ChannelConfig(key="k", content_mode="topic", voice=voice,
                             style_prompt="p", topics=["t"])

    @pytest.mark.parametrize("voice", ["a", "placeholder", "", "   ",
                                       "abcdefghij012345678", "not a voice id!!"])
    def test_a_placeholder_is_refused(self, voice):
        from core.errors import ConfigError

        with pytest.raises(ConfigError):
            self._channel(voice).validate()

    def test_a_real_voice_id_passes(self):
        self._channel("21m00Tcm4TlvDq8ikWAM").validate()


class TestTopicChannelSources:
    """A topic channel needs somewhere for topics to come from — but a
    syllabus counts, so a channel with a plan should not also have to keep
    a redundant flat list."""

    def _channel(self, topics):
        from core.channels import ChannelConfig

        return ChannelConfig(key="c", content_mode="topic",
                             voice="abcdefghij0123456789", style_prompt="p",
                             topics=topics)

    def test_neither_a_plan_nor_a_list_is_refused(self, isolated):
        from core.errors import ConfigError

        with pytest.raises(ConfigError) as caught:
            self._channel([]).validate()
        assert "topic plan" in str(caught.value)

    def test_a_flat_list_is_enough(self, isolated):
        self._channel(["something"]).validate()

    def test_a_syllabus_is_enough_without_a_list(self, planned):
        self._channel([]).validate()


class TestCreatingAChannel:
    """Creation asks for a name and nothing else.

    It used to be the whole settings form — an output directory, a raw
    ElevenLabs voice ID, a content mode and a style prompt, before the
    channel existed. You could not complete it without already having a
    voice ID to hand, and the channel it produced could point at the
    shared output root with "a" for a voice.
    """

    @pytest.fixture
    def client(self, isolated, tmp_path, monkeypatch):
        from core.channels import CHANNELS_JSON_PATH, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        monkeypatch.setattr("core.channel_admin.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("core.corpus.CORPORA_DIR", tmp_path / "corpora")
        write_raw({}, path)
        app = create_app()
        app.config.update(TESTING=True)
        with app.test_client() as test_client:
            yield test_client

    def _csrf(self, client):
        html = client.get("/").get_data(as_text=True)
        marker = 'name="csrf-token" content="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_a_name_alone_is_enough(self, client):
        from core.channels import load_channels

        response = client.post("/channels/new", data={
            "channel_display_name": "Test Astronomy", "csrf_token": self._csrf(client)})
        assert response.status_code == 302
        assert "test_astronomy" in load_channels(validate=False)

    def test_it_lands_on_the_first_setup_step(self, client):
        response = client.post("/channels/new", data={
            "channel_display_name": "Test Astronomy", "csrf_token": self._csrf(client)})
        assert response.headers["Location"].endswith("/setup/content")

    def test_the_key_is_derived_from_the_name(self, client):
        from core.channels import load_channels

        client.post("/channels/new", data={
            "channel_display_name": "Wren's Guide to Witchcraft",
            "csrf_token": self._csrf(client)})
        assert "wrens_guide_to_witchcraft" in load_channels(validate=False)

    def test_the_output_directory_is_the_channels_own(self, client):
        from core.channels import load_channels

        client.post("/channels/new", data={
            "channel_display_name": "Mine", "csrf_token": self._csrf(client)})
        assert load_channels(validate=False)["mine"].output_dir == "output/mine"

    def test_a_name_with_no_usable_characters_is_refused(self, client):
        response = client.post("/channels/new", data={
            "channel_display_name": "!!!", "csrf_token": self._csrf(client)})
        assert response.status_code == 400
        assert "set the key yourself" in response.get_data(as_text=True).lower()

    def test_a_duplicate_name_is_refused(self, client):
        client.post("/channels/new", data={
            "channel_display_name": "Mine", "csrf_token": self._csrf(client)})
        response = client.post("/channels/new", data={
            "channel_display_name": "Mine", "csrf_token": self._csrf(client)})
        assert response.status_code == 400
        assert "already exists" in response.get_data(as_text=True)

    def test_a_new_channel_cannot_generate_yet_and_says_why(self, client):
        from core.channels import load_channels
        from web.helpers import channel_progress

        client.post("/channels/new", data={
            "channel_display_name": "Mine", "csrf_token": self._csrf(client)})
        channel = load_channels(validate=False)["mine"]
        info = channel_progress("mine", channel)
        assert info["can_generate"] is False
        assert info["setup_problem"]

    def test_the_page_does_not_ask_for_a_voice_or_a_directory(self, client):
        """Both were required fields on a form shown before the channel
        existed; one has no sensible value to type and the other is
        derived."""
        html = client.get("/channels/new").get_data(as_text=True)
        assert 'name="voice"' not in html
        assert "output_dir" not in html


class TestSettingsContentSection:
    """The three-way 'where do the words come from' question.

    It lived on a wizard step; it lives on the settings page now. There is
    one editor, so these post to /settings.
    """

    @pytest.fixture
    def client(self, isolated, tmp_path, monkeypatch):
        from core.channels import ChannelConfig, channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        monkeypatch.setattr("core.corpus.CORPORA_DIR", tmp_path / "corpora")
        channel = ChannelConfig(key="c", channel_display_name="C",
                                content_mode="topic")
        channel.output_dir = str(tmp_path / "out" / "c")
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

    def _post(self, client, **fields):
        data = {"channel_display_name": "C", "style_prompt": "Explain something.",
                "csrf_token": self._csrf(client)}
        data.update(fields)
        return client.post("/channels/c/settings", data=data)

    def test_all_three_options_are_explained_not_just_named(self, client):
        html = client.get("/channels/c/settings").get_data(as_text=True)
        assert "Written from scratch" in html
        assert "Your own list of quotes" in html
        assert "A built-in library" in html
        # The old wording, which said nothing about what it meant.
        assert "Fixed source" not in html

    def test_every_section_is_on_the_one_page(self, client):
        """Four hidden tabs plus a nine-step wizard is what made it unclear
        where anything lived."""
        html = client.get("/channels/c/settings").get_data(as_text=True)
        for anchor in ("section-content", "section-voice", "section-look", "section-graphics",
                       "section-music", "section-publishing", "section-money"):
            assert f'id="{anchor}"' in html

    def test_the_look_section_carries_the_caption_controls(self, client):
        """The colours and font were reachable only through a tab that had
        to be discovered."""
        html = client.get("/channels/c/settings").get_data(as_text=True)
        assert 'name="style_font_face"' in html
        assert 'name="style_base_color"' in html
        assert 'type="color"' in html

    def test_choosing_original_sets_topic_mode(self, client):
        from core.channels import load_channels

        self._post(client, words_from="original", topics="stars\nplanets")
        channel = load_channels(validate=False)["c"]
        assert channel.content_mode == "topic"
        assert channel.topics == ["stars", "planets"]

    def test_choosing_own_quotes_stores_them(self, client):
        from core import corpus
        from core.channels import load_channels

        self._post(client, words_from="own_quotes",
                   quotes="The unexamined life is not worth living. — Socrates\n"
                          "Know thyself, said the oracle | Delphi")
        channel = load_channels(validate=False)["c"]
        assert channel.content_mode == "static_corpus"
        assert channel.source == "custom"
        assert corpus.count("c") == 2

    def test_choosing_a_built_in_library_sets_the_source(self, client):
        from core.channels import load_channels

        self._post(client, words_from="built_in", source="bible")
        channel = load_channels(validate=False)["c"]
        assert channel.content_mode == "static_corpus"
        assert channel.source == "bible"

    def test_an_unknown_source_is_ignored_rather_than_stored(self, client):
        from core.channels import load_channels

        self._post(client, words_from="built_in", source="../../etc/passwd")
        assert load_channels(validate=False)["c"].source != "../../etc/passwd"

    def test_the_voice_picker_lists_voices_rather_than_asking_for_an_id(
            self, client, monkeypatch):
        from core import voice_lab

        monkeypatch.setattr(voice_lab, "get_cached_voices", lambda: [
            {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",
             "description": "Calm and clear", "preview_url": "https://x/p.mp3"}])
        html = client.get("/channels/c/settings").get_data(as_text=True)
        assert "Rachel" in html
        assert "https://x/p.mp3" in html

    def test_the_page_still_works_without_the_voice_list(self, client, monkeypatch):
        """A key restricted to text-to-speech can synthesize but not list
        voices. That must not take the whole settings page down."""
        from core import voice_lab
        from core.errors import MissingCredentialError

        def explode():
            raise MissingCredentialError("ELEVENLABS_API_KEY", "the voice list")

        monkeypatch.setattr(voice_lab, "get_cached_voices", explode)
        response = client.get("/channels/c/settings")
        assert response.status_code == 200
        assert "Paste an ID instead" in response.get_data(as_text=True)

    def test_choosing_a_voice_saves_it(self, client, monkeypatch):
        from core import voice_lab
        from core.channels import load_channels

        monkeypatch.setattr(voice_lab, "get_cached_voices", lambda: [])
        self._post(client, words_from="original", topics="stars",
                   voice="21m00Tcm4TlvDq8ikWAM")
        assert load_channels(validate=False)["c"].voice == "21m00Tcm4TlvDq8ikWAM"

    def test_a_pasted_id_beats_the_picker(self, client, monkeypatch):
        from core import voice_lab
        from core.channels import load_channels

        monkeypatch.setattr(voice_lab, "get_cached_voices", lambda: [])
        self._post(client, words_from="original", topics="stars",
                   voice="21m00Tcm4TlvDq8ikWAM",
                   voice_id_manual="AAAAAAAAAAAAAAAAAAAA")
        assert load_channels(validate=False)["c"].voice == "AAAAAAAAAAAAAAAAAAAA"

    def test_an_empty_paste_box_does_not_wipe_the_chosen_voice(
            self, client, monkeypatch):
        """It sits behind a disclosure below the picker; leaving it blank
        is the normal case, not an instruction to clear the voice."""
        from core import voice_lab
        from core.channels import load_channels

        monkeypatch.setattr(voice_lab, "get_cached_voices", lambda: [])
        self._post(client, words_from="original", topics="stars",
                   voice="21m00Tcm4TlvDq8ikWAM", voice_id_manual="   ")
        assert load_channels(validate=False)["c"].voice == "21m00Tcm4TlvDq8ikWAM"

    def test_target_length_saves(self, client):
        from core.channels import load_channels

        self._post(client, words_from="original", topics="stars",
                   pacing_target_seconds="90")
        assert load_channels(validate=False)["c"].pacing.target_seconds == 90

    def test_a_cadence_preset_applies_its_pauses(self, client):
        from core.channels import load_channels
        from core.voice_lab import CADENCE_PRESETS

        preset = next(iter(CADENCE_PRESETS))
        self._post(client, words_from="original", topics="stars", preset=preset)
        pacing = load_channels(validate=False)["c"].pacing
        for field, value in CADENCE_PRESETS[preset]["pacing"].items():
            assert getattr(pacing, field) == value

    def test_saving_one_section_leaves_the_others_alone(self, client):
        """One form carries every section, so what it omits must survive —
        this is the property that made the old wizard's silent saves
        dangerous."""
        from core.channels import load_channels

        self._post(client, words_from="original", topics="stars",
                   style_font_face="impact", patreon_url="https://patreon/x")
        before = load_channels(validate=False)["c"]
        assert before.style.font_face == "impact"

        self._post(client, words_from="original", topics="stars",
                   channel_display_name="Renamed")
        after = load_channels(validate=False)["c"]
        assert after.channel_display_name == "Renamed"
        assert after.style.font_face == "impact"
        assert after.monetization.patreon_url == "https://patreon/x"


class TestCustomQuoteCorpus:
    def test_attribution_after_any_of_the_separators(self, isolated, monkeypatch):
        from core import corpus

        monkeypatch.setattr(corpus, "CORPORA_DIR", isolated / "corpora")
        entries = corpus.parse(
            "The unexamined life is not worth living. — Socrates\n"
            "Nothing is at last sacred but your own mind. | Emerson\n"
            "Knowledge speaks but wisdom listens - Hendrix")
        assert [e["reference"] for e in entries] == ["Socrates", "Emerson", "Hendrix"]

    def test_a_hyphen_inside_the_quote_stays_in_the_quote(self, isolated, monkeypatch):
        from core import corpus

        monkeypatch.setattr(corpus, "CORPORA_DIR", isolated / "corpora")
        entry = corpus.parse("Well-being is the only goal - Aristotle")[0]
        assert entry["text"] == "Well-being is the only goal"
        assert entry["reference"] == "Aristotle"

    def test_comments_and_blank_lines_are_ignored(self, isolated, monkeypatch):
        from core import corpus

        monkeypatch.setattr(corpus, "CORPORA_DIR", isolated / "corpora")
        assert len(corpus.parse("# stoics\n\nA real quote here\n\n# later\n")) == 1

    def test_a_quote_with_no_attribution_falls_back_to_the_channel(
            self, isolated, monkeypatch):
        """The filename is built from the reference, and readable filenames
        are how a repeat stays visible in the output folder."""
        from core import corpus

        monkeypatch.setattr(corpus, "CORPORA_DIR", isolated / "corpora")
        corpus.save("c", "A quote with no attribution at all")
        assert corpus.pick("c", "My Channel")["reference"] == "My Channel"

    def test_an_empty_list_says_what_to_do(self, isolated, monkeypatch):
        from core import corpus
        from core.errors import ConfigError

        monkeypatch.setattr(corpus, "CORPORA_DIR", isolated / "corpora")
        corpus.save("c", "")
        with pytest.raises(ConfigError) as caught:
            corpus.pick("c")
        assert "empty" in caught.value.user_message

    def test_a_channel_key_cannot_escape_the_corpora_directory(
            self, isolated, monkeypatch):
        from core import corpus
        from core.paths import PathTraversalError

        monkeypatch.setattr(corpus, "CORPORA_DIR", isolated / "corpora")
        with pytest.raises(PathTraversalError):
            corpus.path_for("../../secrets")

    def test_the_pipeline_reads_the_custom_list(self, isolated, monkeypatch):
        from core import corpus
        from core.channels import ChannelConfig
        from pipeline.quote_source import get_quote

        monkeypatch.setattr(corpus, "CORPORA_DIR", isolated / "corpora")
        corpus.save("c", "The unexamined life is not worth living. — Socrates")
        channel = ChannelConfig(key="c", channel_display_name="C",
                                content_mode="static_corpus", source="custom",
                                voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p")
        quote = get_quote(channel)
        assert quote["reference"] == "Socrates"

    def test_an_unknown_source_names_the_alternatives(self, isolated):
        from core.channels import ChannelConfig
        from core.errors import ConfigError
        from pipeline.quote_source import get_quote

        channel = ChannelConfig(key="c", content_mode="static_corpus",
                                source="nonsense", voice="21m00Tcm4TlvDq8ikWAM",
                                style_prompt="p")
        with pytest.raises(ConfigError) as caught:
            get_quote(channel)
        assert "your own quote list" in caught.value.user_message


class TestSchemaMigration:
    """Version 1 called topics "units" and subtopics "topics".

    There is real data in that shape — a syllabus with a video already made
    from it — so the rename has to be a migration, not a rename.
    """

    V1 = {
        "version": 1, "channel": "c", "subject": "Witchcraft",
        "generated_at": "2026-09-04T00:00:00+00:00",
        "units": [
            {"id": "u01", "title": "Basics", "summary": "The obvious ground.",
             "level": "foundation", "target_topics": 45, "filled": True},
            {"id": "u02", "title": "Deeper", "summary": "Later.",
             "level": "advanced", "target_topics": 30, "filled": False},
        ],
        "topics": [
            {"id": "t0001", "unit": "u01", "position": 1, "title": "First",
             "angle": "a", "status": "used", "video_stem": "first",
             "used_at": "2026-09-04T00:00:00+00:00", "note": ""},
            {"id": "t0002", "unit": "u01", "position": 2, "title": "Second",
             "angle": "b", "status": "pending", "video_stem": "",
             "used_at": "", "note": ""},
        ],
    }

    @pytest.fixture
    def migrated(self, isolated):
        import json

        curriculum.CURRICULA_DIR.mkdir(parents=True, exist_ok=True)
        curriculum.path_for("c").write_text(json.dumps(self.V1), encoding="utf-8")
        return curriculum.load("c")

    def test_units_become_topics(self, migrated):
        assert [t["title"] for t in migrated["topics"]] == ["Basics", "Deeper"]
        assert migrated["topics"][0]["target_subtopics"] == 45
        assert migrated["topics"][0]["filled"] is True

    def test_topics_become_subtopics(self, migrated):
        """The old file had BOTH keys, and "topics" meant subtopics — so
        writing the new "topics" before reading the old one destroys the
        subtopics. It did, once."""
        assert [t["title"] for t in migrated["subtopics"]] == ["First", "Second"]
        assert len(migrated["subtopics"]) == 2

    def test_the_link_from_a_subtopic_to_its_topic_survives(self, migrated):
        assert all(t["topic"] == "u01" for t in migrated["subtopics"])

    def test_what_was_already_made_is_not_lost(self, migrated):
        used = [t for t in migrated["subtopics"] if t["status"] == "used"]
        assert len(used) == 1
        assert used[0]["video_stem"] == "first"

    def test_progress_reads_the_migrated_shape(self, migrated):
        state = curriculum.progress("c")
        assert state["topic_count"] == 2
        assert state["total"] == 2
        assert state["done"] == 1
        assert state["pending"] == 1

    def test_the_next_write_persists_version_2(self, migrated):
        import json

        curriculum.skip("c", "t0002")
        stored = json.loads(curriculum.path_for("c").read_text(encoding="utf-8"))
        assert stored["version"] == 2
        assert "units" not in stored
        assert "subtopics" in stored

    def test_migrating_twice_is_harmless(self, migrated):
        curriculum.save(migrated)
        again = curriculum.load("c")
        assert len(again["topics"]) == 2
        assert len(again["subtopics"]) == 2


def _current(topic_id):
    """table_rows takes the full subtopic dict the ordering policy
    picked, not just a topic id — this is that dict, for a test that
    only cares which topic is "current"."""
    return curriculum.next_pending("c", topic_id=topic_id)


class TestTableRows:
    """The Create Video table's windowing — never every topic, but never
    a silent drop either."""

    @pytest.fixture
    def channel(self):
        from core.channels import ChannelConfig
        return ChannelConfig(key="c", channel_display_name="C", content_mode="topic",
                             voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p")

    @pytest.fixture
    def many_topics(self, isolated):
        """10 topics, one subtopic each — enough to force windowing at a
        small max_topics without a 40-topic fixture nobody can read."""
        curriculum.start("c", "S", [
            {"title": f"Topic {i}", "summary": "", "level": "foundation",
             "target_subtopics": 1}
            for i in range(10)])
        for i in range(10):
            curriculum.add_subtopics("c", f"u{i + 1:02d}", [{"title": f"Sub {i}", "angle": ""}])
        return "c"

    def test_the_current_topic_is_always_included(self, channel, many_topics):
        result = curriculum.table_rows(channel, current_subtopic=_current("u07"), max_topics=3)
        assert "u07" in [r["topic_id"] for r in result["rows"]]
        assert result["rows"][0]["is_current"]

    def test_hidden_topics_counts_what_was_left_out(self, channel, many_topics):
        result = curriculum.table_rows(channel, current_subtopic=_current("u01"), max_topics=4)
        assert len(result["rows"]) == 4
        assert result["hidden_topics"] == 6

    def test_nothing_is_hidden_when_everything_fits(self, channel, many_topics):
        result = curriculum.table_rows(channel, current_subtopic=_current("u01"), max_topics=20)
        assert result["hidden_topics"] == 0
        assert len(result["rows"]) == 10

    def test_sequential_topic_order_shows_upcoming_topics(self, channel, many_topics):
        channel.ordering.topic_order = "sequential"
        result = curriculum.table_rows(channel, current_subtopic=_current("u03"), max_topics=4)
        ids = [r["topic_id"] for r in result["rows"]]
        assert "u04" in ids or "u05" in ids  # something after u03 in file order

    def test_random_topic_order_does_not_pad_with_untouched_upcoming_topics(
            self, channel, many_topics):
        """A channel that could jump anywhere next shouldn't render a run
        of never-touched topics as if they were queued up — unlike a
        sequential channel, it must not fall back to file order just
        because there's still room to fill."""
        channel.ordering.topic_order = "random"
        curriculum.claim("c", "t0003")  # u03's only subtopic: some activity
        result = curriculum.table_rows(channel, current_subtopic=_current("u01"), max_topics=5)
        ids = {r["topic_id"] for r in result["rows"]}
        # u01 (current) and u03 (touched) belong; nothing else has any
        # activity, so nothing else should be padded in despite max_topics
        # allowing 5.
        assert ids == {"u01", "u03"}

    def test_most_recently_active_topics_are_favoured(self, channel, many_topics):
        curriculum.claim("c", "t0005")
        curriculum.attach_video("c", "t0005", "s5")
        result = curriculum.table_rows(channel, current_subtopic=_current("u01"), max_topics=2)
        ids = [r["topic_id"] for r in result["rows"]]
        assert "u05" in ids

    def test_a_rows_sample_never_exceeds_the_cap(self, channel, isolated):
        curriculum.start("c", "S", [{"title": "Big", "summary": "",
                                     "level": "foundation", "target_subtopics": 20}])
        curriculum.add_subtopics("c", "u01", [{"title": f"S{i}", "angle": ""} for i in range(20)])
        result = curriculum.table_rows(channel, current_subtopic=_current("u01"))
        assert len(result["rows"][0]["subtopics"]) <= curriculum.MAX_ROW_SAMPLE

    def test_the_actual_next_subtopic_is_marked_and_guaranteed_a_slot(self, channel, isolated):
        """Not just any pending subtopic in the current row - the exact
        one the policy picked, even when subtopic order is random and it
        wouldn't otherwise have made the sample's first-few cut."""
        curriculum.start("c", "S", [{"title": "Big", "summary": "",
                                     "level": "foundation", "target_subtopics": 10}])
        curriculum.add_subtopics("c", "u01", [{"title": f"S{i}", "angle": ""} for i in range(10)])
        last = curriculum.find("c", "t0010")  # the last subtopic, position-wise
        result = curriculum.table_rows(channel, current_subtopic=last)
        row = result["rows"][0]
        marked = [s for s in row["subtopics"] if s["is_next"]]
        assert marked == [{"id": "t0010", "title": "S9", "status": "pending", "is_next": True}]
        assert result["rows"][0]["total"] == 10


class TestChoosingWhatToMake:
    """The create page offers the whole plan, not just "the next one".

    Every one of these goes through `fetch_seed`, which must stay free of
    side effects — it is called repeatedly while someone rerolls.
    """

    @pytest.fixture
    def channel(self, planned):
        from core.channels import ChannelConfig
        return ChannelConfig(key="c", channel_display_name="C",
                             content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                             style_prompt="p")

    def test_no_pick_is_the_next_one_in_order(self, channel):
        from pipeline.run import fetch_seed
        assert fetch_seed(channel).title == "First thing"

    def test_a_topic_narrows_to_its_own_subtopics(self, channel):
        from pipeline.run import fetch_seed
        assert fetch_seed(channel, {"topic_id": "u02"}).topic == "Fourth thing"

    def test_a_specific_subtopic_is_honoured(self, channel):
        from pipeline.run import fetch_seed
        seed = fetch_seed(channel, {"subtopic_id": "t0003"})
        assert seed.topic == "Third thing"
        assert seed.topic_id == "t0003"

    def test_random_stays_inside_the_chosen_topic(self, channel):
        from pipeline.run import fetch_seed
        for _ in range(12):
            seed = fetch_seed(channel, {"topic_id": "u02", "mode": "random"})
            assert seed.topic in ("Fourth thing", "Fifth thing")

    def test_random_without_a_topic_can_reach_anything(self, channel):
        from pipeline.run import fetch_seed
        seen = {fetch_seed(channel, {"mode": "random"}).topic for _ in range(40)}
        assert len(seen) > 1

    def test_a_stale_subtopic_id_falls_through_rather_than_failing(self, channel):
        """The plan page and the create page can be open at once, so an id
        that was pending when the page rendered may not be by the time it
        is used."""
        from pipeline.run import fetch_seed

        curriculum.claim("c", "t0002")
        seed = fetch_seed(channel, {"subtopic_id": "t0002"})
        assert seed.topic == "First thing"

    def test_choosing_does_not_consume_anything(self, channel):
        from pipeline.run import fetch_seed

        for pick in ({}, {"topic_id": "u02"}, {"subtopic_id": "t0003"},
                     {"mode": "random"}):
            fetch_seed(channel, pick)
        assert curriculum.progress("c")["pending"] == 5

    def test_an_exhausted_topic_falls_back_to_the_next_overall(self, channel):
        """Better than refusing: the button said "make a video"."""
        from pipeline.run import fetch_seed

        for subtopic_id in ("t0004", "t0005"):
            curriculum.claim("c", subtopic_id)
        assert fetch_seed(channel, {"topic_id": "u02"}).topic == "First thing"


class TestContinuity:
    """Some channels teach in order and video 7 should not re-explain what
    1-6 established. Most short-form is the opposite — videos are found
    individually — so this is off by default."""

    @pytest.fixture
    def channel(self, planned):
        from core.channels import ChannelConfig
        return ChannelConfig(key="c", channel_display_name="C",
                             content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                             style_prompt="p")

    def _seed(self, subtopic_id="t0003"):
        from pipeline.plan import Seed
        return Seed(type="topic", topic="Third thing", topic_id=subtopic_id)

    def test_off_by_default(self, channel):
        from pipeline.script_gen import _continuity
        assert _continuity(channel, self._seed()) == ""

    def test_on_it_lists_what_was_already_covered(self, channel):
        from pipeline.script_gen import _continuity

        channel.build_on_previous = True
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "first_thing")

        text = _continuity(channel, self._seed())
        assert "First thing" in text
        assert "Do not re-explain" in text

    def test_only_what_actually_became_a_video(self, channel):
        """A pending subtopic has not been seen by anyone."""
        from pipeline.script_gen import _continuity

        channel.build_on_previous = True
        assert _continuity(channel, self._seed()) == ""

    def test_it_does_not_reach_into_other_topics(self, channel):
        from pipeline.script_gen import _continuity
        from pipeline.plan import Seed

        channel.build_on_previous = True
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "first_thing")

        # t0004 lives in u02; t0001 lives in u01.
        text = _continuity(channel, Seed(type="topic", topic="Fourth thing",
                                         topic_id="t0004"))
        assert text == ""

    def test_a_subtopic_never_lists_itself(self, channel):
        from pipeline.script_gen import _continuity

        channel.build_on_previous = True
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "stem")
        text = _continuity(channel, self._seed("t0001"))
        assert "First thing" not in text

    def test_the_list_is_capped(self, channel, monkeypatch):
        """The prompt must not grow without bound as a topic fills up."""
        from pipeline import script_gen

        channel.build_on_previous = True
        monkeypatch.setattr(curriculum, "covered_in_topic", lambda *a: [
            {"id": f"c{i:04d}", "title": f"Covered {i}"} for i in range(50)])
        # A real id, so the lookup that precedes the list still resolves.
        text = script_gen._continuity(channel, self._seed("t0003"))
        assert text.count("- Covered") == script_gen.CONTINUITY_LIMIT

    def test_a_broken_plan_costs_the_context_not_the_video(self, channel, monkeypatch):
        from pipeline.script_gen import _continuity

        channel.build_on_previous = True

        def explode(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(curriculum, "find", explode)
        assert _continuity(channel, self._seed()) == ""

    def test_the_setting_round_trips_through_the_form(self):
        from core.channels import ChannelConfig
        from web.forms import apply_channel_form

        channel = ChannelConfig(key="c", content_mode="topic",
                                voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p",
                                topics=["x"])
        apply_channel_form(channel, {"continuity_present": "1",
                                     "build_on_previous": "on"})
        assert channel.build_on_previous is True

        apply_channel_form(channel, {"continuity_present": "1"})
        assert channel.build_on_previous is False

    def test_a_form_without_the_field_leaves_it_alone(self):
        from core.channels import ChannelConfig
        from web.forms import apply_channel_form

        channel = ChannelConfig(key="c", content_mode="topic",
                                voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p",
                                topics=["x"])
        channel.build_on_previous = True
        apply_channel_form(channel, {"channel_display_name": "C"})
        assert channel.build_on_previous is True


class TestBackgroundPicture:
    """Choosing and editing the still image behind the title and outro
    cards. Every network call is stubbed."""

    @pytest.fixture
    def isolated_channel(self, tmp_path, monkeypatch):
        from core import backgrounds

        monkeypatch.setattr(backgrounds, "CHANNELS_DIR", tmp_path / "channels")
        return "c"

    def _photo(self, size=(600, 1200), colour=(200, 120, 40)):
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", size, colour).save(buffer, format="JPEG")
        return buffer.getvalue()

    def _stub_download(self, monkeypatch, data):
        from core import backgrounds

        class Response:
            content = data
            status_code = 200

            def raise_for_status(self):
                pass

        monkeypatch.setattr(backgrounds.requests, "get", lambda *a, **k: Response())

    def test_a_chosen_picture_is_cropped_to_the_frame(
            self, isolated_channel, monkeypatch):
        from PIL import Image

        from core import backgrounds
        from core.paths import FRAME_HEIGHT, FRAME_WIDTH

        self._stub_download(monkeypatch, self._photo())
        backgrounds.choose("c", "https://example/p.jpg", "pexels")

        with Image.open(backgrounds.path("c")) as image:
            assert image.size == (FRAME_WIDTH, FRAME_HEIGHT)

    def test_a_landscape_source_is_covered_not_letterboxed(
            self, isolated_channel, monkeypatch):
        """A bar of background colour down the sides is worse than a crop,
        and a photograph's subject is almost always in the middle."""
        from PIL import Image

        from core import backgrounds
        from core.paths import FRAME_HEIGHT, FRAME_WIDTH

        self._stub_download(monkeypatch, self._photo(size=(1920, 400)))
        backgrounds.choose("c", "https://example/p.jpg", "pexels")

        with Image.open(backgrounds.path("c")) as image:
            assert image.size == (FRAME_WIDTH, FRAME_HEIGHT)
            # Every pixel is real picture; a letterbox would leave bars.
            assert image.convert("RGB").getpixel((5, 5)) != (0, 0, 0)

    def test_the_original_is_kept_beside_the_edited_copy(
            self, isolated_channel, monkeypatch):
        """So the sliders can be moved again without re-downloading."""
        from core import backgrounds

        self._stub_download(monkeypatch, self._photo())
        backgrounds.choose("c", "https://example/p.jpg", "pexels")
        assert backgrounds.original_path("c").exists()
        assert backgrounds.path("c").exists()

    def test_edits_always_derive_from_the_original(
            self, isolated_channel, monkeypatch):
        """Blur applied twice is not the same as more blur applied once,
        so moving a slider back has to undo."""
        from core import backgrounds

        from PIL import Image

        def middle():
            with Image.open(backgrounds.path("c")) as image:
                return image.convert("RGB").getpixel((540, 960))

        self._stub_download(monkeypatch, self._photo(colour=(200, 120, 40)))
        backgrounds.choose("c", "https://example/p.jpg", "pexels", blur=20, dim=60)
        dimmed = middle()
        assert dimmed[0] < 120        # 60% black over (200, 120, 40)

        # Back to nothing: the source colour, not a dimmer version of the
        # already-dimmed one.
        backgrounds.apply_edits("c", blur=0, dim=0)
        assert middle()[0] > 180

        backgrounds.apply_edits("c", blur=20, dim=60)
        assert abs(middle()[0] - dimmed[0]) <= 2

    def test_edits_are_clamped(self, isolated_channel, monkeypatch):
        from core import backgrounds

        self._stub_download(monkeypatch, self._photo())
        backgrounds.choose("c", "https://example/p.jpg", "pexels")
        info = backgrounds.apply_edits("c", blur=9999, dim=-5)
        assert info["blur"] == backgrounds.MAX_BLUR
        assert info["dim"] == 0

    def test_the_licence_is_recorded(self, isolated_channel, monkeypatch):
        """The same question gets asked at monetization time as for a
        footage clip."""
        from core import backgrounds

        self._stub_download(monkeypatch, self._photo())
        backgrounds.choose("c", "https://example/p.jpg", "pexels", credit="A. Person")
        info = backgrounds.info("c")
        assert "Pexels License" in info["license"]
        assert info["credit"] == "A. Person"

    def test_an_unknown_source_is_flagged_rather_than_assumed_free(
            self, isolated_channel, monkeypatch):
        from core import backgrounds

        self._stub_download(monkeypatch, self._photo())
        backgrounds.choose("c", "https://example/p.jpg", "somewhere_else")
        assert "Unconfirmed" in backgrounds.info("c")["license"]

    def test_a_non_http_url_is_refused(self, isolated_channel):
        from core import backgrounds

        with pytest.raises(backgrounds.BackgroundError):
            backgrounds.choose("c", "file:///etc/passwd", "pexels")

    def test_editing_without_a_picture_says_so(self, isolated_channel):
        from core import backgrounds

        with pytest.raises(backgrounds.BackgroundError) as caught:
            backgrounds.apply_edits("c", blur=5)
        assert "no background" in caught.value.user_message.lower()

    def test_clear_removes_everything(self, isolated_channel, monkeypatch):
        from core import backgrounds

        self._stub_download(monkeypatch, self._photo())
        backgrounds.choose("c", "https://example/p.jpg", "pexels")
        backgrounds.clear("c")
        assert not backgrounds.has_background("c")
        assert not backgrounds.original_path("c").exists()
        assert backgrounds.info("c") == {}

    def test_one_site_failing_still_returns_the_other(self, monkeypatch):
        from core import backgrounds

        def explode(*a, **k):
            raise RuntimeError("down")

        monkeypatch.setattr(backgrounds, "_search_pexels", explode)
        monkeypatch.setattr(backgrounds, "_search_pixabay",
                            lambda q, n: [{"source": "pixabay", "preview": "p",
                                           "full": "f", "credit": "", "link": ""}])
        assert len(backgrounds.search("candles")) == 1

    def test_a_channel_key_cannot_escape_the_channels_directory(self, isolated_channel):
        from core import backgrounds
        from core.paths import PathTraversalError

        with pytest.raises(PathTraversalError):
            backgrounds.path("../../secrets")


class TestTitleCard:
    def _style(self, **overrides):
        from core.channels import Style

        style = Style()
        for field, value in overrides.items():
            setattr(style, field, value)
        return style

    def test_it_is_off_by_default(self):
        """Seconds before the content starts are watch time spent on
        nothing, and short-form is decided in the first of them."""
        assert self._style().title_card_enabled is False

    def test_it_renders_a_full_frame(self):
        from core.paths import FRAME_HEIGHT, FRAME_WIDTH
        from pipeline.assemble import render_title_card

        frame = render_title_card("My Channel", "A Video Title", self._style())
        assert frame.shape[0] == FRAME_HEIGHT
        assert frame.shape[1] == FRAME_WIDTH

    def test_a_long_title_wraps_rather_than_overflowing(self):
        from pipeline.assemble import render_title_card

        frame = render_title_card(
            "My Channel",
            "An extremely long video title that could not possibly fit on one line",
            self._style())
        assert frame.shape[1] == 1080

    def test_a_missing_background_falls_back_to_the_colour(self, tmp_path, monkeypatch):
        """A decoration must never fail a render that is otherwise done."""
        from core import backgrounds
        from pipeline.assemble import card_background

        monkeypatch.setattr(backgrounds, "CHANNELS_DIR", tmp_path / "channels")
        image = card_background("nobody", (5, 6, 7, 255),
                                self._style(use_background_image=True))
        assert image.getpixel((10, 10))[:3] == (5, 6, 7)

    def test_switching_the_picture_off_uses_the_colour(self, tmp_path, monkeypatch):
        from core import backgrounds
        from pipeline.assemble import card_background

        monkeypatch.setattr(backgrounds, "CHANNELS_DIR", tmp_path / "channels")
        image = card_background("c", (1, 2, 3, 255),
                                self._style(use_background_image=False))
        assert image.getpixel((10, 10))[:3] == (1, 2, 3)

    def test_an_unreadable_picture_does_not_raise(self, tmp_path, monkeypatch):
        from core import backgrounds
        from pipeline.assemble import card_background

        monkeypatch.setattr(backgrounds, "CHANNELS_DIR", tmp_path / "channels")
        target = backgrounds.path("c")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"not a jpeg")
        image = card_background("c", (9, 9, 9, 255),
                                self._style(use_background_image=True))
        assert image.getpixel((10, 10))[:3] == (9, 9, 9)


class TestTopicTitleForCard:
    """The title card's optional third line: the enclosing topic's
    title, one hop up from the subtopic a seed carries."""

    def _channel(self, **overrides):
        channel = ChannelConfig(key="c", content_mode="topic",
                                voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p")
        for k, v in overrides.items():
            setattr(channel, k, v)
        return channel

    def test_the_right_topic_title_for_a_real_subtopic(self, planned):
        from pipeline.assemble import _topic_title_for_card
        from pipeline.plan import Seed

        seed = Seed(type="topic", topic="First thing", topic_id="t0001")
        assert _topic_title_for_card(self._channel(), seed) == "Basics"

    def test_empty_for_a_quote_channel(self, planned):
        from pipeline.assemble import _topic_title_for_card
        from pipeline.plan import Seed

        channel = self._channel(content_mode="static_corpus")
        seed = Seed(type="quote", text="x", reference="y")
        assert _topic_title_for_card(channel, seed) == ""

    def test_empty_when_there_is_no_curriculum(self, isolated):
        from pipeline.assemble import _topic_title_for_card
        from pipeline.plan import Seed

        seed = Seed(type="topic", topic="X", topic_id="whatever")
        assert _topic_title_for_card(self._channel(), seed) == ""

    def test_empty_for_a_stale_subtopic_id(self, planned):
        from pipeline.assemble import _topic_title_for_card
        from pipeline.plan import Seed

        seed = Seed(type="topic", topic="Gone", topic_id="t9999")
        assert _topic_title_for_card(self._channel(), seed) == ""
