"""
Quiz channels (pipeline.quiz, decision 041).

The model calls are faked. What's tested: a round becomes question and
answer segments with the countdown as silence after each question; the
fact check replaces what it doesn't pass and holds the video when a
replacement still fails; the board is timed from the real voiceover; the
clock's ticks aren't thinned out like other effects; the originality
check compares questions, not the host's patter; and a quiz draft becomes
a channel whose plan is every category at every difficulty.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.channels import ChannelConfig
from pipeline import quiz
from pipeline.plan import Seed, WordTiming


def _round(n=3, prefix="Q"):
    return {"intro": "Today's quiz is all about science, and it's easy. Starting with question one...",
            "questions": [{"lead_in": f"Question {i + 1}." if i else "",
                           "question": f"{prefix} question number {i + 1}?",
                           "answer": f"A{i + 1}", "spoken_answer": f"A{i + 1}. A{i + 1}."}
                          for i in range(n)],
            "outro": "How many did you get?", "title_options": ["Science quiz: easy"],
            "description_body": "Three easy science questions."}


def _channel(n=3):
    channel = ChannelConfig(key="pub_quiz", format="quiz", style_prompt="A friendly host.")
    channel.quiz.questions = n
    return channel


class TestScript:
    def test_questions_are_followed_by_their_countdown_then_the_answer(self):
        script = quiz.to_script(_round(), _channel(), "Science", "Easy")
        texts = [s.text for s in script.segments]
        assert texts[1] == "Q question number 1?"                 # the intro leads into Q1
        assert texts[3] == "Question 2. Q question number 2?"
        assert texts[4] == "A2. A2."
        assert script.segments[1].pause_after == 4.0 and script.segments[2].pause_after == 1.2
        assert script.segments[-1].text == "How many did you get?"
        assert script.quiz["questions"][1] == {
            "question": "Q question number 2?", "answer": "A2", "spoken_answer": "A2. A2.",
            "ask": 3, "reveal": 4}

    def test_the_voiceover_honours_a_segments_own_pause(self):
        from core.channels import Pacing
        from pipeline import tts
        script = quiz.to_script(_round(), _channel(), "Science", "Easy")
        plan = tts.build_plan(script.segments, None, Pacing())
        assert [p for _, p, _ in plan][1:3] == [4.0, 1.2]
        assert plan[-1][1] == Pacing().end_hold

    def test_the_originality_check_compares_questions_not_patter(self):
        from pipeline import similarity
        script = quiz.to_script(_round(), _channel(), "Science", "Easy")
        text = similarity.script_text(script)
        assert "Q question number 2? A2" in text
        assert "Starting with question one" not in text and "Question 2." not in text

    def test_a_script_round_trips_through_a_checkpoint(self):
        from pipeline.plan import Script
        script = quiz.to_script(_round(), _channel(), "Science", "Easy")
        again = Script.from_jsonable(script.to_jsonable())
        assert again.quiz == script.quiz and again.segments[1].pause_after == 4.0


class TestFactCheck:
    def _fake(self, monkeypatch, verdicts):
        calls = {"write": 0}

        def call_json(system, user, schema, *, operation, **kwargs):
            if operation == "quiz_write":
                calls["write"] += 1
                return _round(prefix="Fresh" if calls["write"] > 1 else "Q")
            return {"results": [{"number": i + 1, "your_answer": "?", "verdict": v, "note": ""}
                                for i, v in enumerate(verdicts.pop(0))]}

        monkeypatch.setattr(quiz, "call_json", call_json)
        return calls

    def test_a_question_that_fails_is_replaced_and_rechecked(self, monkeypatch):
        calls = self._fake(monkeypatch, [["ok", "wrong", "ok"], ["ok"]])
        script = quiz.write_script(Seed(type="topic", topic="Science: Easy"), _channel())
        assert calls["write"] == 2
        assert script.quiz["questions"][1]["question"] == "Fresh question number 1?"
        # Its place in the round keeps its lead-in.
        assert script.segments[3].text == "Question 2. Fresh question number 1?"
        assert script.quiz["unverified"] == []

    def test_a_replacement_that_still_fails_holds_the_video(self, monkeypatch):
        from core import publish_gate
        self._fake(monkeypatch, [["ok", "ok", "ambiguous"], ["dated"]])
        script = quiz.write_script(Seed(type="topic", topic="Science: Easy"), _channel())
        assert script.quiz["unverified"] == [3]
        gate = publish_gate.evaluate({"quiz_unverified": [3], "checks": {
            "script": {"ran": True}, "frames": {"ran": True}}})
        assert not gate["passed"] and "question 3" in gate["reasons"][0]

    def test_a_check_that_cannot_run_passes_nothing(self, monkeypatch):
        from core.errors import PipelineError

        def fail(*a, **k):
            raise PipelineError("down", user_message="down")

        monkeypatch.setattr(quiz, "call_json", fail)
        assert quiz.verify("Science", "Easy", _round()["questions"]) == ["unchecked"] * 3

    def test_earlier_questions_are_offered_to_the_writer(self, monkeypatch):
        from pipeline import similarity
        similarity.record("pub_quiz", "old", quiz.to_script(_round(prefix="Old"), _channel(),
                                                            "Science", "Easy"))
        similarity.record("pub_quiz", "other", quiz.to_script(_round(prefix="Geo"), _channel(),
                                                              "Geography", "Easy"))
        asked = quiz.asked_before("pub_quiz", "science")
        assert asked[0].startswith("Old") and asked[-1].startswith("Geo")


class TestRounds:
    def test_a_round_is_read_from_its_subtopic(self):
        channel = _channel()
        assert quiz.round_of(Seed(type="topic", topic="Science: Very hard (round 2)"),
                             channel) == ("Science", "Very hard")

    def test_every_title_is_unique_across_categories_and_rounds(self):
        rows = (quiz.subtopic_rows("Science", ["Easy", "Hard"])
                + quiz.subtopic_rows("Maths", ["Easy", "Hard"])
                + quiz.subtopic_rows("Science", ["Easy", "Hard"], 2))
        titles = [r["title"] for r in rows]
        assert len(set(titles)) == len(titles) and rows[0]["angle"] == "Easy"


class TestBoard:
    def _timed(self):
        script = quiz.to_script(_round(), _channel(), "Science", "Easy")
        t, words = 0.0, []
        for seg in script.segments:
            seg.start = t
            words.append(WordTiming("w", t, t + 1.5))
            t += 2 + (seg.pause_after or 0.3)
            seg.end = t
        return script, words

    def test_the_countdown_runs_in_the_silence_after_the_question(self):
        script, words = self._timed()
        times = quiz.timeline(script, words)
        first = times["questions"][0]
        assert first["reveal"] == script.segments[2].start
        assert first["countdown"] == pytest.approx(first["reveal"] - 4.0)
        cues = quiz.timer_cues(times)
        assert [k for _, k, _ in cues[:5]] == ["tock"] * 4 + ["chime"]

    def test_the_board_has_every_row_and_the_whole_question(self):
        from pipeline.scenes import art
        script, words = self._timed()
        html = quiz.board_html(script, quiz.timeline(script, words), art.resolve({}), 30.0)
        assert "Q question number 2?" in html and "<div class='n'>3.</div>" in html
        assert "STATIC_BACKGROUND = true" in html

    def test_the_clock_is_not_thinned_out_like_other_effects(self, tmp_path):
        import json
        from pipeline import sound
        clip = tmp_path / "board.mp4"
        cues = [(i * 0.5, "tock", 0.8) for i in range(20)]
        clip.with_suffix(".json").write_text(json.dumps({"timer_cues": cues}), encoding="utf-8")
        plan = SimpleNamespace(scene_clips=[{"first": 0, "last": 0, "clip": str(clip)}],
                               script=SimpleNamespace(segments=[SimpleNamespace(start=1.0)]))
        assert len(sound.scene_cues(plan)) == 20            # past MIN_GAP and MAX_CUES


class TestChannel:
    def test_a_quiz_draft_is_held_to_what_renders(self):
        from tests.test_channel_draft import VOICE_IDS, model_answer
        from pipeline import channel_draft
        body = channel_draft.clean(model_answer(
            format="quiz", content_mode="static_corpus", corpus_source="bible",
            quiz_categories=["Science", "science", " Maths "], quiz_difficulties=["Only one"],
            quiz_questions=40, quiz_countdown_seconds=0, target_seconds=150), VOICE_IDS)
        assert body["content_mode"] == "topic" and body["corpus_source"] == ""
        assert body["quiz_categories"] == ["Science", "science", "Maths"][:3]
        assert body["quiz_difficulties"] == ChannelConfig(key="x").quiz.difficulties
        assert body["quiz_questions"] == 15 and body["quiz_countdown_seconds"] == 1
        assert body["target_seconds"] == 150                 # a quiz may run past 90

    def test_accepting_a_quiz_makes_every_category_at_every_difficulty(self, tmp_path, monkeypatch):
        from core import curriculum, drafts
        from core.channels import load_channels
        from tests.test_channel_draft import VOICE_IDS, VOICES, model_answer
        from pipeline import channel_draft
        monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path / "drafts")
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", tmp_path / "channels.json")
        monkeypatch.setattr("core.curriculum.CURRICULA_DIR", tmp_path / "curricula")
        monkeypatch.setattr("core.channel_admin.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(drafts.voice_lab, "get_cached_voices", lambda: VOICES)
        body = channel_draft.clean(model_answer(
            format="quiz", quiz_categories=["Science", "Geography"],
            quiz_difficulties=["Easy", "Hard", "Impossible"], quiz_questions=10,
            quiz_countdown_seconds=4, target_seconds=150), VOICE_IDS)
        monkeypatch.setattr(channel_draft, "draft", lambda *a, **k: body)
        monkeypatch.setattr(channel_draft, "outline",
                            lambda *a: pytest.fail("a quiz needs no outline call"))
        record = drafts.create("a pub quiz")
        drafts.accept(record["id"], {"name": "Pub Quiz", "voice": VOICE_IDS[0]})

        channel = load_channels()["pub_quiz"]
        assert channel.format == "quiz" and not channel.style.captions_enabled
        assert channel.ordering.grouping == "round_robin"
        titles = [s["title"] for s in curriculum.subtopics("pub_quiz")]
        assert len(titles) == 6 and "Geography: Impossible" in titles

        # Running low tops up with another round of everything, for free.
        monkeypatch.setattr(curriculum, "LOW_WATER_MARK", 10)
        assert quiz.top_up(channel) == 6
        assert "Science: Easy (round 2)" in [s["title"] for s in curriculum.subtopics("pub_quiz")]

    def test_the_settings_form_sets_the_format(self):
        from web.forms import apply_channel_form
        from werkzeug.datastructures import MultiDict
        channel = ChannelConfig(key="c")
        apply_channel_form(channel, MultiDict({
            "quiz_present": "1", "format": "quiz", "quiz_questions": "99",
            "quiz_countdown_seconds": "5", "quiz_difficulties": "Easy\nEasy\nFiendish\n",
            "style_flags_present": "1"}))
        assert channel.format == "quiz" and channel.quiz.questions == 15
        assert channel.quiz.countdown_seconds == 5 and channel.quiz.difficulties == ["Easy", "Fiendish"]
        assert channel.style.captions_enabled is False


def test_the_scheduler_writes_the_next_topic_when_a_plan_runs_low(tmp_path, monkeypatch):
    """A new channel's plan only ever had its first topic written, so a
    channel left to publish itself stopped when that topic ran out."""
    from core import curriculum, scheduler
    from pipeline import curriculum_gen
    monkeypatch.setattr("core.curriculum.CURRICULA_DIR", tmp_path / "curricula")
    channel = ChannelConfig(key="narrated", style_prompt="x")
    channel.publishing.enabled = True
    data = curriculum.start("narrated", "science", [{"title": "Atoms"}, {"title": "Forces"}])
    curriculum.add_subtopics("narrated", data["topics"][0]["id"], [{"title": "What an atom is"}])
    monkeypatch.setattr(curriculum_gen, "write_subtopics",
                        lambda ch, plan, topic: [{"title": f"{topic['title']} one"}])
    assert scheduler.top_up_plans({"narrated": channel}) == ["narrated"]
    assert "Forces one" in [s["title"] for s in curriculum.subtopics("narrated")]
    channel.publishing.enabled = False              # not running itself: left alone
    assert scheduler.top_up_plans({"narrated": channel}) == []
