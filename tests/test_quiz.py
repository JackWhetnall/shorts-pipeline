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
    def answer_for(i):
        return f"A{i + 1}" if prefix == "Q" else f"{prefix}{i + 1}"
    return {"intro": "Today's quiz is all about science, and it's easy. Starting with question one...",
            "questions": [{"lead_in": f"Question {i + 1}." if i else "",
                           "question": f"{prefix} question number {i + 1}?",
                           "answer": answer, "spoken_answer": f"{answer}. {answer}."}
                          for i, answer in ((i, answer_for(i)) for i in range(n))],
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
            return {"results": [{"number": i + 1, "working": "", "correct_answers": ["?"], "verdict": v, "note": ""}
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
        # This category's questions are shown; another category's only
        # when they touch on this one (and the local check catches the rest).
        assert asked[0].startswith("Old") and not any(q.startswith("Geo") for q in asked)
        geo = quiz.to_script(_round(prefix="Geo"), _channel(), "Geography", "Easy").quiz["questions"]
        assert quiz.repeats(geo, "pub_quiz") == [0, 1, 2]


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
        apply_channel_form(channel, MultiDict([
            ("quiz_present", "1"), ("format", "quiz"), ("quiz_questions", "99"),
            ("quiz_countdown_seconds", "5"), ("style_flags_present", "1"),
            ("quiz_level_name", "Easy"), ("quiz_level_value", "2"),
            ("quiz_level_name", "easy"), ("quiz_level_value", "3"),
            ("quiz_level_name", "Fiendish"), ("quiz_level_value", "8"),
            ("quiz_level_name", "Hard"), ("quiz_level_value", "5.4"),
            ("quiz_level_name", ""), ("quiz_level_value", "9")]))
        assert channel.format == "quiz" and channel.quiz.questions == 15
        # Duplicates and blank rows dropped, ordered by level, the number kept.
        assert channel.quiz.countdown_seconds == 5
        assert channel.quiz.difficulties == ["Easy (2)", "Hard (5.5)", "Fiendish (8)"]
        assert quiz.labels(channel) == ["Easy", "Hard", "Fiendish"]
        assert quiz.level_of(channel, "Hard") == 5.5
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


def test_the_checker_works_the_answer_out_before_judging():
    """Regression: shown "J" as the only letter in no element symbol, a
    checker that judged first agreed; made to list every correct answer
    first, it found Q too. The schema's order is what enforces that."""
    fields = list(quiz.VERIFY_SCHEMA["properties"]["results"]["items"]["properties"])
    assert fields.index("working") < fields.index("correct_answers") < fields.index("verdict")
    assert quiz.VERIFY_EFFORT == "high"


def test_the_round_is_written_to_fit_a_short():
    """Regression: the first real round was 370 words, which with ten
    five-second silences made a 3:37 video, past the Shorts limit."""
    channel = _channel(10)
    channel.pacing.target_seconds = 150
    assert 220 <= quiz.word_budget(channel) <= 260
    assert "at most" in quiz._user("Science", "Hard", 10, channel, ([], []), "")


def test_a_video_past_three_minutes_is_held():
    from core import publish_gate
    ok = {"checks": {"script": {"ran": True}, "frames": {"ran": True}}}
    assert publish_gate.evaluate({**ok, "video_seconds": 179})["passed"]
    held = publish_gate.evaluate({**ok, "video_seconds": 217})
    assert not held["passed"] and "3:37" in held["reasons"][0]


def test_a_replacement_never_repeats_an_answer_already_in_the_round():
    assert quiz._mentions("Which country is shaped like a boot? Italy", "Italy")
    assert not quiz._mentions("Which country contains Australia's capital?", "Au")
    assert quiz._mentions("the Pacific Ocean", "The Pacific")


def test_a_long_category_shrinks_to_one_line_rather_than_wrapping():
    """Regression: "General Knowledge Quiz" in a serif face wrapped onto a
    second line that ran into the question card."""
    from pipeline.scenes import art
    script = quiz.to_script(_round(), _channel(), "General Knowledge", "Medium")
    for seg in script.segments:
        seg.start, seg.end = 0.0, 1.0
    html = quiz.board_html(script, quiz.timeline(script, []), art.resolve({}), 10.0)
    assert "<span class='cat' data-fit=" in html and "white-space: nowrap" in html


def test_settings_for_a_quiz_show_only_the_board_look(tmp_path, monkeypatch):
    from web import create_app
    from core.channels import save_channel
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", tmp_path / "channels.json")
    channel = _channel()
    channel.voice = "a" * 20
    save_channel(channel)
    page = create_app().test_client().get("/channels/pub_quiz/settings").get_data(as_text=True)
    assert "Board look" in page and "quiz-preview.jpg" in page
    assert 'type="range" name="scene_share"' not in page and 'name="scene_share"' in page
    assert "Paintings and engravings" not in page and "Hook text and key words" not in page


class TestLadder:
    """A category's rounds are written easiest first, each seeing the
    others, then made in any order."""

    @pytest.fixture
    def plan(self, tmp_path, monkeypatch):
        from core import curriculum
        monkeypatch.setattr("core.curriculum.CURRICULA_DIR", tmp_path / "curricula")
        channel = _channel()
        channel.quiz.difficulties = ["Easy", "Medium", "Hard"]
        data = curriculum.start("pub_quiz", "quiz", [{"title": "Science"}, {"title": "Maths"}])
        for topic in data["topics"]:
            curriculum.add_subtopics("pub_quiz", topic["id"],
                                     quiz.subtopic_rows(topic["title"], channel.quiz.difficulties))
        prompts = []

        def call_json(system, user, schema, *, operation, **kwargs):
            if operation == "quiz_verify":
                return {"results": [{"number": i + 1, "working": "", "correct_answers": ["x"],
                                     "verdict": "ok", "note": ""} for i in range(3)]}
            prompts.append(user)
            difficulty = user.split("Difficulty: ")[1].split(",")[0]
            return _round(prefix=difficulty)

        monkeypatch.setattr(quiz, "call_json", call_json)
        return SimpleNamespace(channel=channel, prompts=prompts,
                               find=lambda title: next(s for s in curriculum.subtopics("pub_quiz")
                                                       if s["title"] == title))

    def test_a_hard_round_writes_the_easier_ones_first_and_builds_on_them(self, plan):
        hard = plan.find("Science: Hard")
        script = quiz.write_script(Seed(type="topic", topic=hard["title"], topic_id=hard["id"]),
                                   plan.channel)
        assert [p.split("Difficulty: ")[1].split(",")[0] for p in plan.prompts] == [
            "Easy", "Medium", "Hard"]
        assert "The Easy round, level 2 (must be easier" in plan.prompts[1]
        assert "Easy question number 1?" in plan.prompts[2] and "Medium question number 1?" in plan.prompts[2]
        assert script.quiz["difficulty"] == "Hard"
        # The easier rounds are stored for their own videos; the other
        # category is untouched.
        assert plan.find("Science: Easy")["script"]["quiz"]["difficulty"] == "Easy"
        assert plan.find("Maths: Easy").get("script") is None

    def test_a_stored_round_is_used_when_its_video_comes_up(self, plan):
        from pipeline import script_gen
        medium = plan.find("Science: Medium")
        quiz.write_script(Seed(type="topic", topic=medium["title"], topic_id=medium["id"]),
                          plan.channel)
        easy = plan.find("Science: Easy")
        stored = script_gen._stored_script(SimpleNamespace(
            channel=plan.channel, seed=Seed(type="topic", topic=easy["title"], topic_id=easy["id"])))
        assert stored.quiz["difficulty"] == "Easy"
        # And counts as asked, so no other round repeats it.
        assert "Easy question number 1?" in quiz.asked_before("pub_quiz", "Science")

    def test_a_round_already_made_counts_as_a_rung(self, plan):
        """The owner made Medium first: Easy must be pitched below it."""
        from core import curriculum
        from pipeline import similarity
        medium = plan.find("Science: Medium")
        curriculum.attach_video("pub_quiz", medium["id"], "science_medium")
        curriculum.claim("pub_quiz", medium["id"])
        similarity.record("pub_quiz", "science_medium",
                          quiz.to_script(_round(prefix="Made"), plan.channel, "Science", "Medium"))
        easy = plan.find("Science: Easy")
        quiz.write_script(Seed(type="topic", topic=easy["title"], topic_id=easy["id"]), plan.channel)
        assert "The Medium round, level 4 (must be harder" in plan.prompts[0]
        assert "Made question number 1? (Made1)" in plan.prompts[0]


class TestScale:
    def test_the_default_ladder_sits_on_the_fixed_scale(self):
        assert quiz.levels(["Easy", "Medium", "Hard", "Fiendish", "Impossible"]) == [
            ("Easy", 2), ("Medium", 4), ("Hard", 5.5), ("Fiendish", 8), ("Impossible", 9.5)]

    def test_a_level_added_later_slots_in_without_moving_the_others(self):
        before = dict(quiz.levels(["Easy", "Medium", "Hard", "Fiendish", "Impossible"]))
        after = dict(quiz.levels(["Easy", "Medium", "Hard", "Tricky", "Fiendish", "Impossible"]))
        assert all(after[k] == v for k, v in before.items())
        assert before["Hard"] < after["Tricky"] < before["Fiendish"]

    def test_an_unknown_name_sits_between_its_neighbours_and_a_number_wins(self):
        assert dict(quiz.levels(["Easy", "Warm", "Hard"]))["Warm"] == 4        # midway 2 .. 5.5
        assert dict(quiz.levels(["Easy", "Spicy (7)", "Hard"])) == {"Easy": 2, "Spicy": 7, "Hard": 8}
        # The list's order is the ladder's: levels always rise down it, even
        # when a familiar name is out of its usual place.
        odd = [level for _, level in quiz.levels(["Easy", "Impossible", "Hard"])]
        assert odd == sorted(odd) and len(set(odd)) == 3

    def test_a_numbered_category_shares_its_memory(self):
        assert quiz.base_category("General Knowledge 2") == "General Knowledge"
        assert quiz.base_category("General Knowledge (3)") == "General Knowledge"
        assert quiz.base_category("Henry VIII") == "Henry"         # the price of Roman numerals
        assert quiz.base_category("Maths") == "Maths"

    def test_a_new_level_reaches_every_round_already_planned(self, tmp_path, monkeypatch):
        from core import curriculum
        monkeypatch.setattr("core.curriculum.CURRICULA_DIR", tmp_path / "curricula")
        channel = _channel()
        channel.quiz.difficulties = ["Easy", "Hard"]
        data = curriculum.start("pub_quiz", "quiz", [{"title": "Science"}])
        topic = data["topics"][0]["id"]
        curriculum.add_subtopics("pub_quiz", topic, quiz.subtopic_rows("Science", ["Easy", "Hard"]))
        curriculum.add_subtopics("pub_quiz", topic, quiz.subtopic_rows("Science", ["Easy", "Hard"], 2))
        channel.quiz.difficulties = ["Easy", "Hard", "Tricky"]
        assert quiz.sync_ladders(channel) == 2
        titles = [s["title"] for s in curriculum.subtopics("pub_quiz")]
        assert "Science: Tricky" in titles and "Science: Tricky (round 2)" in titles
        assert quiz.sync_ladders(channel) == 0


class TestBank:
    def test_every_round_is_kept_beyond_the_originality_history(self):
        for n in range(3):
            quiz.remember("pub_quiz", f"v{n}", quiz.to_script(_round(prefix=f"R{n}"), _channel(),
                                                               "Science", "Easy"))
        assert [r["video"] for r in quiz.bank("pub_quiz")] == ["v0", "v1", "v2"]
        quiz.remember("pub_quiz", "v1", quiz.to_script(_round(prefix="Again"), _channel(),
                                                      "Science", "Easy"))
        assert len(quiz.bank("pub_quiz")) == 3          # a re-render replaces, never duplicates

    def test_a_new_topic_is_shown_what_other_topics_asked_about_it(self):
        biology = {"intro": "i", "outro": "o", "title_options": ["t"], "description_body": "",
                   "questions": [
                       {"lead_in": "", "question": "Which snake has the most toxic venom?",
                        "answer": "Inland taipan", "spoken_answer": "x"},
                       {"lead_in": "", "question": "What do bees make?", "answer": "Honey",
                        "spoken_answer": "x"}]}
        quiz.remember("pub_quiz", "bio", quiz.to_script(biology, _channel(2), "Biology", "Easy"))
        same, related = quiz.context_questions("pub_quiz", "Snakes")
        assert same == [] and [q["answer"] for q in related] == ["Inland taipan"]
        # And a repeat is caught however it's worded, in any category.
        again = [{"question": "Which snake's venom is the most toxic?", "answer": "the inland taipan"}]
        assert quiz.repeats(again, "pub_quiz") == [0]
        assert quiz.repeats([{"question": "Which bird lays the largest egg?", "answer": "Ostrich"}],
                            "pub_quiz") == []


def test_a_finished_render_leaves_no_working_files_and_listings_skip_them(tmp_path):
    from core import gallery
    from pipeline import assemble
    (tmp_path / "v.mp4").write_bytes(b"")
    work = tmp_path / "v_scenes"
    work.mkdir()
    (work / "board.mp4").write_bytes(b"")
    (tmp_path / "old_TEMP_board.mp4").write_bytes(b"")
    assert [p.name for p in gallery.videos_in(tmp_path)] == ["v.mp4"]
    assemble.remove_working_files(SimpleNamespace(out_dir=tmp_path, stem="v"))
    assert not work.exists()


def test_a_new_category_gets_its_rounds_by_rule(monkeypatch):
    from pipeline import curriculum_gen
    monkeypatch.setattr(curriculum_gen, "write_subtopics", lambda *a: pytest.fail("no model call"))
    channel = _channel()
    channel.quiz.difficulties = ["Easy", "Hard", "Tricky"]
    rows = curriculum_gen.fill_topic(channel, {"title": "Snakes"})
    assert [r["title"] for r in rows] == ["Snakes: Easy", "Snakes: Hard", "Snakes: Tricky"]


def test_chemical_symbols_are_respelled_by_rule():
    """Regression: "Au" was read as "ow". Not left to the writer to notice."""
    questions = [{"question": "What is the chemical symbol for gold?", "answer": "Au"},
                 {"question": "Which element has the symbol Fe?", "answer": "Iron"},
                 {"question": "What is the symbol for indium?", "answer": "In"},     # a word: left alone
                 {"question": "Which metal is liquid at room temperature?", "answer": "Mercury"}]
    assert quiz.element_respellings(questions) == {"Au": "ay you", "Fe": "eff ee"}
    cleaned = quiz._clean_round({**_round(), "questions": questions + questions[:0],
                                 "pronunciations": [{"written": "Au", "say": "A U"}]}, 3)
    assert cleaned["pronunciations"]["Au"] == "ay you"


def test_a_round_never_holds_two_questions_that_clash():
    questions = [{"question": "What is the capital city of France?", "answer": "Paris"},
                 {"question": "What is the most populous city in France?", "answer": "Paris"},
                 {"question": "Which river flows through the city of Paris?", "answer": "Seine"},
                 {"question": "What is the capital city of Spain?", "answer": "Madrid"}]
    assert quiz.round_clashes(questions) == [1, 2]


def test_a_quiz_category_that_runs_out_gets_its_next_round(tmp_path, monkeypatch):
    """No waiting to be topped up by the scheduler, and no error: asking
    for a category with nothing left starts its next round, free."""
    from core import curriculum
    from pipeline.run import fetch_seed
    monkeypatch.setattr("core.curriculum.CURRICULA_DIR", tmp_path / "curricula")
    channel = _channel()
    channel.quiz.difficulties = ["Easy", "Hard"]
    data = curriculum.start("pub_quiz", "quiz", [{"title": "Maths"}, {"title": "Art"}])
    for topic in data["topics"]:
        curriculum.add_subtopics("pub_quiz", topic["id"], quiz.subtopic_rows(topic["title"], ["Easy", "Hard"]))
    maths = data["topics"][0]["id"]
    for row in curriculum.subtopics("pub_quiz", topic_id=maths):
        curriculum.claim("pub_quiz", row["id"])
    seed = fetch_seed(channel, pick={"topic_id": maths, "mode": "random"})
    assert "(round 2)" in seed.topic and seed.topic.startswith("Maths")
    # And with nothing waiting anywhere, every category gets its next round.
    for row in curriculum.subtopics("pub_quiz", status=curriculum.PENDING):
        curriculum.claim("pub_quiz", row["id"])
    fetch_seed(channel)
    assert "Art: Easy (round 2)" in [s["title"] for s in curriculum.subtopics("pub_quiz")]


def test_the_channel_pronunciation_list_is_saved_and_used(tmp_path):
    from pipeline import tts
    from web.forms import apply_channel_form
    from werkzeug.datastructures import MultiDict
    channel = _channel()
    apply_channel_form(channel, MultiDict({"pronunciations": "Job = Jobe\nAu = ay you\nnonsense line\n"}))
    assert channel.pronunciations == {"Job": "Jobe", "Au": "ay you"}
    assert tts.speakable("Au, like Job said", channel.pronunciations) == "ay you, like Jobe said"


class TestPictureRounds:
    """Picture rounds (pipeline.pictures, decision 046). Sources faked."""

    def test_a_picture_question_repeats_by_what_it_shows_not_its_wording(self):
        france = {"question": "Whose flag is this?", "answer": "France", "kind": "flags", "subject": "France"}
        spain = {**france, "answer": "Spain", "subject": "Spain"}
        outline = {**france, "question": "Which country has this shape?", "kind": "outlines"}
        assert quiz.repeats([spain, outline], "pub_quiz", among=[france]) == []
        assert quiz.repeats([dict(france)], "pub_quiz", among=[france]) == [0]
        assert quiz.round_clashes([france, spain]) == []

    def test_a_question_whose_picture_fails_is_replaced(self, monkeypatch):
        from pipeline import pictures
        rounds = {"n": 0}

        def call_json(system, user, schema, *, operation, **kwargs):
            rounds["n"] += 1
            names = ["Chile", "Nowhere", "Peru"] if rounds["n"] == 1 else ["Japan", "Italy", "Spain"]
            return {"intro": "i", "outro": "o", "title_options": ["t"], "description_body": "",
                    "pronunciations": [],
                    "questions": [{"lead_in": "", "question": "Whose flag is this?", "answer": n,
                                   "spoken_answer": n, "subject": n} for n in names]}

        def fetch(kind, subject, style=None):
            if subject == "Nowhere":
                raise pictures.PictureError("no flag", user_message="no flag")
            return {"path": f"{subject}.png", "credit": ""}

        monkeypatch.setattr(quiz, "call_json", call_json)
        monkeypatch.setattr(pictures, "choices", lambda kind: ["Chile", "Peru", "Japan"])
        monkeypatch.setattr(pictures, "fetch", fetch)
        monkeypatch.setattr(pictures, "check", lambda *a: "")
        script = quiz._write_checked(_channel(), "Flags", "Easy", kind="flags")
        assert [q["answer"] for q in script.quiz["questions"]] == ["Chile", "Japan", "Peru"]
        assert script.quiz["questions"][1]["picture"]["path"] == "Japan.png"
        assert script.quiz["unverified"] == []

    def test_the_board_shows_the_picture_big_with_the_question_under_it(self, monkeypatch, tmp_path):
        from pipeline.scenes import art
        png = tmp_path / "f.png"
        from PIL import Image
        Image.new("RGB", (30, 20), "red").save(png)
        data = {"intro": "i", "outro": "o", "questions": [
            {"lead_in": "", "question": "Whose flag is this?", "answer": f"C{i}", "spoken_answer": "x",
             "kind": "flags", "subject": f"C{i}", "picture": {"kind": "flags", "path": str(png)}}
            for i in range(3)]}
        script = quiz.to_script(data, _channel(), "Flags", "Easy")
        for seg in script.segments:
            seg.start, seg.end = 0.0, 1.0
        page = quiz.board_html(script, quiz.timeline(script, []), art.resolve({}), 10.0)
        assert "data:image/png;base64," in page and "class='qtext small'" in page
        assert f"height: {quiz.PICTURE_CARD_H}px" in page


def test_outlines_are_drawn_from_shapes_and_specks_are_left_out(monkeypatch):
    from pipeline import pictures
    square = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]}
    speck = {"type": "Polygon", "coordinates": [[[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1], [0, 0]]]}
    monkeypatch.setattr(pictures, "_shapes", lambda: {"Squareland": square, "Speck": speck})
    assert pictures.outline_countries() == ["Squareland"]
    svg = pictures.outline_svg("Squareland", "#123456")
    assert svg.startswith("<svg") and "fill='#123456'" in svg and "<path d='M" in svg


def test_only_reusable_commons_pictures_are_taken(monkeypatch):
    from pipeline import pictures
    assert pictures._commons_file("https://upload.wikimedia.org/wikipedia/commons/7/7e/A_b.jpg?utm_source=x") == "A_b.jpg"
    assert pictures._commons_file("https://upload.wikimedia.org/wikipedia/en/1/1a/Poster.jpg") == ""
    for ok in ("Public domain", "CC0", "CC BY 2.0", "CC BY-SA 4.0"):
        assert pictures.REUSABLE.match(ok)
    for no in ("Fair use", "", "All rights reserved"):
        assert not pictures.REUSABLE.match(no)



def test_dingbats_are_not_offered():
    """Removed: a dingbat's meaning is in its exact shape, which a model
    can't reliably design or judge, and there's no free library of real
    ones. Categories set to it before are ordinary rounds now."""
    from pipeline import pictures
    assert "dingbats" not in pictures.KINDS and "dingbats" not in quiz.PICTURE_GUIDE


class TestHook:
    """The owner: quiz shorts need a hook, with splash text to catch the
    eye, varied and novel, never lifted from examples in the prompt."""

    def _round(self, **extra):
        return {"intro": "Keep score. Question one.", "outro": "Bye.", "title_options": ["t"],
                "description_body": "", **extra,
                "questions": [{"lead_in": "", "question": f"Q{i}?", "answer": f"A{i}",
                               "spoken_answer": f"A{i}."} for i in range(3)]}

    def test_the_hook_is_said_first_and_the_splash_is_on_the_opening_card(self):
        channel = ChannelConfig(key="c", format="quiz")
        channel.quiz.questions = 3
        script = quiz.to_script(self._round(hook="Rate your rock knowledge?", splash="Rock on"),
                                channel, "Music", "Hard")
        assert script.segments[0].text == "Rate your rock knowledge?"
        assert script.segments[1].text == "Keep score. Question one."
        assert script.quiz["questions"][0]["ask"] == 2
        assert (script.quiz["hook"], script.quiz["splash"]) == ("Rate your rock knowledge?", "Rock on")
        t = 0.0
        for seg in script.segments:
            seg.start, seg.end = t, t + 2
            t += 2 + (seg.pause_after or 0)
        from pipeline.scenes import art
        page = quiz.board_html(script, quiz.timeline(script, []), art.resolve({}), t)
        assert "class='splash'" in page and "Rock on" in page

    def test_a_round_written_before_hooks_still_works(self):
        channel = ChannelConfig(key="c", format="quiz")
        channel.quiz.questions = 3
        script = quiz.to_script(self._round(), channel, "Music", "Hard")
        assert script.segments[0].text == "Keep score. Question one." and not script.quiz["splash"]

    def test_recent_openings_are_shown_to_the_writer_to_avoid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(quiz, "QUESTION_BANK_DIR", tmp_path)
        monkeypatch.setattr(quiz, "_written", lambda key: [])
        channel = ChannelConfig(key="c", format="quiz")
        channel.quiz.questions = 3
        script = quiz.to_script(self._round(hook="Rate your rock knowledge?", splash="Rock on"),
                                channel, "Music", "Hard")
        quiz.remember("c", "music_hard", script)
        assert quiz.recent_openings("c") == [("Rate your rock knowledge?", "Rock on")]
        prompt = quiz._user("Science", "Hard", 3, channel, ([], []), "")
        assert "- Rate your rock knowledge? / Rock on" in prompt

    def test_the_prompt_gives_no_opening_to_copy(self):
        system = quiz.SYSTEM.lower()
        for stock in ("test your", "how well do you", "think you know", "only 1%"):
            assert stock not in system
