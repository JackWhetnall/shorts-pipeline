"""
`pipeline.script_gen`: turning a seed into a script — and, since the
script-studio work, writing several scripts for one topic together so a
series reads as one continuous thing rather than unrelated one-offs.

Every model call is stubbed. What's worth testing here is not writing
quality — a judgement, not an assertion — but the bookkeeping: a batch is
matched back to the right subtopics, a stored script is used instead of
paying for a fresh call, and a discard never quietly loses one.
"""

from __future__ import annotations

import pytest

from core.channels import ChannelConfig
from core.errors import PipelineError
from pipeline import llm, script_gen
from pipeline.plan import RenderPlan, Seed

TOPIC = {"id": "u01", "title": "Basics", "summary": "The obvious ground."}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from core import curriculum
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    return tmp_path


def _channel(**overrides):
    channel = ChannelConfig(key="c", channel_display_name="C", content_mode="topic",
                            voice="21m00Tcm4TlvDq8ikWAM", style_prompt="Write plainly.")
    for key, value in overrides.items():
        setattr(channel, key, value)
    return channel


def _script_payload(index, text="Some words here to fill the segment out nicely."):
    return {"index": index,
            "segments": [{"text": text, "shot_brief": "a candle", "keywords": ["candle"]},
                         {"text": text, "shot_brief": "a road", "keywords": ["road"]}],
            "title_options": ["A Title"], "description_body": "desc"}


class TestWriteScripts:
    def test_asks_for_exactly_n_and_tags_each_with_its_index(self, monkeypatch):
        captured = {}

        def fake_call_json(system, user, schema, **kwargs):
            captured["user"] = user
            return {"scripts": [_script_payload(1), _script_payload(2)]}

        monkeypatch.setattr(llm, "call_json", fake_call_json)
        subs = [{"id": "t1", "title": "First", "angle": "a"},
               {"id": "t2", "title": "Second", "angle": "b"}]
        written = script_gen.write_scripts(_channel(), TOPIC, subs)

        assert {w["subtopic_id"] for w in written} == {"t1", "t2"}
        assert "2 scripts" in captured["user"]
        assert "First" in captured["user"] and "Second" in captured["user"]

    def test_a_missing_index_drops_that_subtopic_rather_than_guessing(self, monkeypatch):
        """Better to write one real script than invent which subtopic an
        unlabelled answer belongs to."""
        monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"scripts": [_script_payload(1)]})
        subs = [{"id": "t1", "title": "First", "angle": "a"},
               {"id": "t2", "title": "Second", "angle": "b"}]
        written = script_gen.write_scripts(_channel(), TOPIC, subs)
        assert len(written) == 1
        assert written[0]["subtopic_id"] == "t1"

    def test_each_written_script_matches_the_stored_shape(self, monkeypatch):
        monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"scripts": [_script_payload(1)]})
        subs = [{"id": "t1", "title": "First", "angle": "a"}]
        written = script_gen.write_scripts(_channel(), TOPIC, subs)
        script = written[0]["script"]
        assert script["segments"][0]["text"]
        assert script["title_options"] == ["A Title"]
        assert script["description_body"] == "desc"

    def test_no_array_bounds_in_the_schema(self):
        schema = script_gen._batch_schema()
        assert "minItems" not in str(schema) and "maxItems" not in str(schema)

    def test_covered_titles_included_only_when_build_on_previous(self, monkeypatch, isolated):
        from core import curriculum

        curriculum.start("c", "Testing", [{"title": "Basics", "summary": "s",
                                           "level": "foundation", "target_subtopics": 2}])
        curriculum.add_subtopics("c", "u01", [{"title": "Old one", "angle": "a"}])
        curriculum.claim("c", "t0001")
        curriculum.attach_video("c", "t0001", "stem")

        captured = {}

        def fake_call_json(system, user, schema, **kwargs):
            captured["system"] = "\n".join(b.text for b in system)
            return {"scripts": [_script_payload(1)]}

        monkeypatch.setattr(llm, "call_json", fake_call_json)
        subs = [{"id": "t2", "title": "New one", "angle": "a"}]

        script_gen.write_scripts(_channel(build_on_previous=True), TOPIC, subs)
        assert "Old one" in captured["system"]

        script_gen.write_scripts(_channel(build_on_previous=False), TOPIC, subs)
        assert "Old one" not in captured["system"]

    def test_context_scope_controls_how_far_back_it_reaches(self, monkeypatch, isolated):
        """Same setup as the test above, but with a SECOND topic before
        the one being written - "topic" scope must not see it, wider
        scopes must."""
        from core import curriculum

        curriculum.start("c", "Testing", [
            {"title": "Earlier Topic", "summary": "s", "level": "foundation",
             "target_subtopics": 1},
            {"title": "Basics", "summary": "s", "level": "foundation",
             "target_subtopics": 2},
        ])
        curriculum.add_subtopics("c", "u01", [{"title": "Way back", "angle": "a"}])
        curriculum.add_subtopics("c", "u02", [{"title": "Old one", "angle": "a"}])
        for subtopic_id, stem in (("t0001", "s1"), ("t0002", "s2")):
            curriculum.claim("c", subtopic_id)
            curriculum.attach_video("c", subtopic_id, stem)
            curriculum.mark_published("c", stem)

        topic = curriculum.find_topic("c", "u02")
        subs = [{"id": "t3", "title": "New one", "angle": "a"}]

        captured = {}

        def fake_call_json(system, user, schema, **kwargs):
            captured["system"] = "\n".join(b.text for b in system)
            return {"scripts": [_script_payload(1)]}

        monkeypatch.setattr(llm, "call_json", fake_call_json)

        script_gen.write_scripts(
            _channel(build_on_previous=True, context_scope="topic"), topic, subs)
        assert "Way back" not in captured["system"]
        assert "Old one" in captured["system"]

        script_gen.write_scripts(
            _channel(build_on_previous=True, context_scope="all"), topic, subs)
        assert "Way back" in captured["system"]
        assert "Old one" in captured["system"]


class TestRegenerateScript:
    def _fake(self, monkeypatch, captured):
        def fake_call_json(system, user, schema, **kwargs):
            captured["system"] = "\n".join(b.text for b in system)
            captured["user"] = user
            return {"segments": [{"text": "hi", "shot_brief": "b", "keywords": ["k"]}],
                    "title_options": ["T"], "description_body": "d"}
        monkeypatch.setattr(llm, "call_json", fake_call_json)

    def test_a_blank_instruction_is_a_plain_retry(self, monkeypatch):
        captured = {}
        self._fake(monkeypatch, captured)
        script_gen.regenerate_script(_channel(), TOPIC, {"id": "t1", "title": "First", "angle": "a"}, [])
        assert "Also:" not in captured["user"]

    def test_an_instruction_is_folded_into_the_ask(self, monkeypatch):
        captured = {}
        self._fake(monkeypatch, captured)
        script_gen.regenerate_script(_channel(), TOPIC, {"id": "t1", "title": "First", "angle": "a"},
                                     [], instruction="also mention candles")
        assert "also mention candles" in captured["user"]

    def test_sibling_scripts_are_named_so_they_are_not_repeated(self, monkeypatch):
        captured = {}
        self._fake(monkeypatch, captured)
        siblings = [{"title": "Sibling One",
                    "script": {"segments": [{"text": "an opening about candles"}]}}]
        script_gen.regenerate_script(_channel(), TOPIC, {"id": "t2", "title": "Second", "angle": "b"},
                                     siblings)
        assert "Sibling One" in captured["system"]
        assert "candles" in captured["system"]

    def test_an_empty_response_is_a_pipeline_error(self, monkeypatch):
        monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"segments": []})
        with pytest.raises(PipelineError):
            script_gen.regenerate_script(_channel(), TOPIC, {"id": "t1", "title": "x"}, [])


class TestStoredScript:
    """`_stored_script` is what lets a render skip a paid call entirely
    when a topic's scripts have already been written — and what makes
    that opt-in rather than a requirement: absent everywhere it can't
    apply, a channel that never touches this feature renders exactly as
    it always has."""

    def _script(self, text="hi there friend"):
        return {"citation": None,
                "segments": [{"text": text, "shot_brief": "", "keywords": [],
                             "start": 0.0, "end": 0.0}],
                "title_options": [], "description_body": ""}

    def test_used_when_present(self, isolated):
        from core import curriculum

        curriculum.start("c", "T", [{"title": "B", "summary": "s",
                                     "level": "foundation", "target_subtopics": 1}])
        curriculum.add_subtopics("c", "u01", [{"title": "First", "angle": "a"}])
        curriculum.set_script("c", "t0001", self._script())

        plan = RenderPlan(channel=_channel(),
                          seed=Seed(type="topic", topic="First", topic_id="t0001"))
        result = script_gen._stored_script(plan)
        assert result is not None
        assert result.segments[0].text == "hi there friend"

    def test_none_when_the_channel_has_no_curriculum(self, isolated):
        plan = RenderPlan(channel=_channel(),
                          seed=Seed(type="topic", topic="X", topic_id="whatever"))
        assert script_gen._stored_script(plan) is None

    def test_none_for_a_quote_channel(self, isolated):
        plan = RenderPlan(channel=_channel(content_mode="static_corpus"),
                          seed=Seed(type="quote", text="x", reference="y"))
        assert script_gen._stored_script(plan) is None

    def test_none_when_the_subtopic_has_no_script_yet(self, isolated):
        from core import curriculum

        curriculum.start("c", "T", [{"title": "B", "summary": "s",
                                     "level": "foundation", "target_subtopics": 1}])
        curriculum.add_subtopics("c", "u01", [{"title": "First", "angle": "a"}])
        plan = RenderPlan(channel=_channel(),
                          seed=Seed(type="topic", topic="First", topic_id="t0001"))
        assert script_gen._stored_script(plan) is None

    def test_run_uses_a_stored_script_without_calling_the_model(self, isolated, monkeypatch):
        from core import curriculum

        curriculum.start("c", "T", [{"title": "B", "summary": "s",
                                     "level": "foundation", "target_subtopics": 1}])
        curriculum.add_subtopics("c", "u01", [{"title": "First", "angle": "a"}])
        curriculum.set_script("c", "t0001", self._script())

        def explode(*a, **k):
            raise AssertionError("should not call the model when a script is stored")
        monkeypatch.setattr(llm, "call_json", explode)

        plan = RenderPlan(channel=_channel(),
                          seed=Seed(type="topic", topic="First", topic_id="t0001"))
        script_gen.run(plan)
        assert plan.script.segments[0].text == "hi there friend"

    def test_run_falls_back_to_generating_when_nothing_is_stored(self, isolated, monkeypatch):
        from core import curriculum

        curriculum.start("c", "T", [{"title": "B", "summary": "s",
                                     "level": "foundation", "target_subtopics": 1}])
        curriculum.add_subtopics("c", "u01", [{"title": "First", "angle": "a"}])

        monkeypatch.setattr(llm, "call_json", lambda *a, **k: {
            "segments": [{"text": "generated fresh", "shot_brief": "b", "keywords": ["k"]}],
            "title_options": ["T"], "description_body": "d"})

        plan = RenderPlan(channel=_channel(),
                          seed=Seed(type="topic", topic="First", topic_id="t0001"))
        script_gen.run(plan)
        assert plan.script.segments[0].text == "generated fresh"
