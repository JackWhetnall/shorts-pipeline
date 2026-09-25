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


class TestPlaceholderText:
    """The bug: a generated video's opening line was `A catchy line with a
    "quoted phrase" in the middle of it` — the model described the line
    instead of writing it, and the voice read the description out.

    The fix is mostly `SPOKEN_TEXT_GUIDANCE` in the prompt. These tests
    cover the net under it, which matters at both ends: it has to catch
    the shapes that actually went wrong, and it has to leave ordinary
    prose alone, because every false positive costs a paid rewrite.
    """

    @pytest.mark.parametrize("text", [
        'A catchy line with a "quoted phrase" in the middle of it',
        "An engaging opening hook that draws the viewer in",
        "Hook: so you want to learn to read tea leaves",
        "Segment 2: next, lay the cloth out flat",
        "So today we are looking at [topic] and why it matters",
        "Start with a question about {subject}",
    ])
    def test_catches_a_line_that_describes_itself(self, text):
        assert script_gen.placeholder_text([{"text": text}]) == text

    @pytest.mark.parametrize("text", [
        "The line between ritual and habit is thinner than you think.",
        "So, have you ever wondered what a candle is actually doing?",
        "First, lay the cloth out flat. Next, set the bowl in the middle.",
        "A quiet morning is the easiest time to try this.",
        "Some people find that the smell alone settles them.",
        "The phrase your grandmother used was probably closer to the truth.",
    ])
    def test_leaves_ordinary_narration_alone(self, text):
        assert script_gen.placeholder_text([{"text": text}]) == ""

    def test_reads_segment_objects_as_well_as_dicts(self):
        from pipeline.plan import Segment
        good = Segment(text="A quiet morning works well.", shot_brief="", keywords=[])
        bad = Segment(text="A catchy opening line goes here", shot_brief="", keywords=[])
        assert script_gen.placeholder_text([good, bad]) == bad.text

    def test_generate_script_rewrites_once_then_takes_what_comes_back(self, monkeypatch):
        """One retry, not a loop: a second call is cheap, a third is
        chasing a prompt problem with money."""
        calls = []

        def fake_call_json(system, user, schema, **kwargs):
            calls.append(user)
            text = ("A catchy line with a \"quoted phrase\" in it" if len(calls) == 1
                    else "So, have you ever tried this before?")
            return {"segments": [{"text": text, "shot_brief": "b", "keywords": ["k"]}],
                    "title_options": ["T"], "description_body": "d"}

        monkeypatch.setattr(llm, "call_json", fake_call_json)
        script = script_gen.generate_script(Seed(type="topic", topic="Tea"), _channel())

        assert len(calls) == 2
        assert "actual words" in calls[1]
        assert script.segments[0].text == "So, have you ever tried this before?"

    def test_a_retry_that_fails_again_is_flagged_not_failed(self, isolated, monkeypatch):
        """The words are already paid for and are on the review screen to
        judge. Failing the run here would spend money and produce nothing."""
        monkeypatch.setattr(llm, "call_json", lambda *a, **k: {
            "segments": [{"text": "A catchy opening line goes here",
                         "shot_brief": "b", "keywords": ["k"]}],
            "title_options": ["T"], "description_body": "d"})

        plan = RenderPlan(channel=_channel(), seed=Seed(type="topic", topic="Tea"))
        script_gen.run(plan)
        assert plan.script_suspect == "A catchy opening line goes here"

    def test_a_stored_script_is_checked_too(self, isolated, monkeypatch):
        """`run` is the only point every script passes through, whether it
        was written now, pre-written on the syllabus, or reloaded from a
        checkpoint. A pre-written one skips `generate_script` entirely."""
        from core import curriculum

        curriculum.start("c", "T", [{"title": "B", "summary": "s",
                                     "level": "foundation", "target_subtopics": 1}])
        curriculum.add_subtopics("c", "u01", [{"title": "First", "angle": "a"}])
        curriculum.set_script("c", "t0001", {
            "citation": None, "title_options": [], "description_body": "",
            "segments": [{"text": "A catchy line with a \"quoted phrase\" in it",
                         "shot_brief": "", "keywords": [], "start": 0.0, "end": 0.0}]})

        monkeypatch.setattr(llm, "call_json", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("a stored script must not pay for a call")))

        plan = RenderPlan(channel=_channel(),
                          seed=Seed(type="topic", topic="First", topic_id="t0001"))
        script_gen.run(plan)
        assert plan.script_suspect


class TestOriginalityGate:
    """The check used to run after the render: a retread of an earlier
    script had already paid for its voiceover, footage and encode before
    anyone was told. Now it gates the voiceover, and rewrites once."""

    EARLIER = ("The shepherd walks ahead of the flock through the dark valley, "
               "and the sheep follow the sound of his voice without seeing the path.")

    def _history(self):
        from pipeline import similarity
        from pipeline.plan import Script, Segment
        similarity.record("c", "Earlier video", Script(
            segments=[Segment(text=self.EARLIER)], citation=None))

    def _payload(self, text):
        return {"segments": [{"text": text, "shot_brief": "b", "keywords": ["k"]}],
                "title_options": ["T"], "description_body": "d"}

    def _plan(self):
        return RenderPlan(channel=_channel(), seed=Seed(type="topic", topic="Shepherds"))

    def test_a_retread_is_rewritten_once_with_the_earlier_text_to_avoid(self, monkeypatch):
        self._history()
        calls = []

        def fake(system, user, schema, **kwargs):
            calls.append(user)
            if len(calls) == 1:
                return self._payload(self.EARLIER)
            return self._payload("Bread rises overnight in a cold kitchen while the baker sleeps.")

        monkeypatch.setattr(llm, "call_json", fake)
        plan = self._plan()
        script_gen.run(plan)

        assert len(calls) == 2
        assert "Earlier video" in calls[1] and "shepherd walks ahead" in calls[1]
        assert plan.script.segments[0].text.startswith("Bread rises")
        assert not plan.similarity.flagged

    def test_a_rewrite_that_is_no_better_is_not_kept(self, monkeypatch):
        self._history()
        first = self.EARLIER + " Hope."
        responses = iter([self._payload(first), self._payload(self.EARLIER)])
        monkeypatch.setattr(llm, "call_json", lambda *a, **k: next(responses))
        plan = self._plan()
        script_gen.run(plan)

        assert plan.script.segments[0].text == first
        assert plan.similarity.flagged

    def test_an_original_script_costs_no_extra_call(self, monkeypatch):
        self._history()
        calls = []

        def fake(*a, **k):
            calls.append(1)
            return self._payload("Bread rises overnight in a cold kitchen while the baker sleeps.")

        monkeypatch.setattr(llm, "call_json", fake)
        plan = self._plan()
        script_gen.run(plan)
        assert len(calls) == 1
        assert not plan.similarity.flagged

    def test_a_stored_studio_script_is_flagged_but_never_rewritten(self, isolated, monkeypatch):
        from core import curriculum

        self._history()
        curriculum.start("c", "T", [{"title": "B", "summary": "s",
                                     "level": "foundation", "target_subtopics": 1}])
        curriculum.add_subtopics("c", "u01", [{"title": "First", "angle": "a"}])
        curriculum.set_script("c", "t0001", {
            "citation": None, "title_options": ["T"], "description_body": "d",
            "segments": [{"text": self.EARLIER, "shot_brief": "b", "keywords": ["k"]}]})

        def explode(*a, **k):
            raise AssertionError("a stored script may carry hand edits; never rewrite it")
        monkeypatch.setattr(llm, "call_json", explode)

        plan = RenderPlan(channel=_channel(),
                          seed=Seed(type="topic", topic="First", topic_id="t0001"))
        script_gen.run(plan)
        assert plan.similarity.flagged
        assert plan.script.segments[0].text == self.EARLIER


# --- the hook and the landing ------------------------------------------------

def _seg(text):
    return {"text": text, "shot_brief": "a candle", "keywords": ["candle"]}


class TestHookAndLanding:
    def test_a_quote_video_opens_with_its_hook_before_the_passage(self, monkeypatch):
        seen = {}

        def fake(system, user, schema, **kwargs):
            seen["user"], seen["schema"] = user, schema
            return {"hook_promise": "why a threat reads as a promise",
                    "payoff": "the last line names the promise",
                    "hook": "This verse sounds like a warning. It was written as comfort.",
                    "hook_shot_brief": "storm clouds parting", "hook_keywords": ["clouds"],
                    "segments": [_seg("One two three."), _seg("Four five six.")],
                    "title_options": ["T"], "description_body": "d",
                    "quote_shot_brief": "an open bible", "quote_keywords": ["bible"]}

        monkeypatch.setattr(llm, "call_json", fake)
        channel = _channel(content_mode="static_corpus", source="bible",
                           hook_style="Open on a quiet question.")
        channel.pacing.segment_count = 2
        script = script_gen.generate_script(
            Seed(type="quote", text="Fear not.", reference="Isaiah 41:10"), channel)
        texts = [s.text for s in script.segments]
        assert texts[0].startswith("This verse sounds like a warning")
        assert texts[1] == "Fear not." and script.source_index == 1
        assert script.hook_promise == "why a threat reads as a promise"
        # Planned before written: the loop comes first in the schema.
        assert list(seen["schema"]["properties"])[:3] == ["hook_promise", "payoff", "hook"]
        assert "Open on a quiet question." in seen["user"]
        assert "THE LANDING" in seen["user"]

    def test_a_topic_script_carries_its_planned_loop(self, monkeypatch):
        monkeypatch.setattr(llm, "call_json", lambda *a, **k: {
            "hook_promise": "p", "payoff": "q",
            "segments": [_seg("One two three."), _seg("Four five six."), _seg("Seven eight.")],
            "title_options": ["T"], "description_body": "d"})
        script = script_gen.generate_script(Seed(type="topic", topic="Pythagoras"), _channel())
        assert (script.hook_promise, script.payoff, script.source_index) == ("p", "q", None)

    def test_the_originality_check_skips_the_passage_but_not_the_hook(self):
        from pipeline import similarity
        from pipeline.plan import Script, Segment
        script = Script(segments=[Segment("my hook"), Segment("their verse"), Segment("my notes")],
                        citation="John 3:16", source_index=1)
        assert similarity.script_text(script) == "my hook my notes"
        # Scripts saved before hooks existed: the passage was segment 0.
        old = Script.from_jsonable({"citation": "John 3:16",
                                    "segments": [{"text": "verse"}, {"text": "notes"}]})
        assert old.source_index == 0 and similarity.script_text(old) == "notes"

    def test_the_script_studio_plans_each_loop_too(self):
        item = script_gen._batch_schema()["properties"]["scripts"]["items"]
        assert {"hook_promise", "payoff"} <= set(item["required"])


def test_a_hook_is_always_a_finished_sentence():
    # Regression: Minute Pastor hooks came back as lowercase fragments with
    # no question mark, and the captions show them exactly as written.
    assert script_gen._sentence("why does he keep answering her") == "Why does he keep answering her?"
    assert script_gen._sentence("this verse sounds like a threat") == "This verse sounds like a threat."
    assert script_gen._sentence("It isn't what it seems!") == "It isn't what it seems!"
