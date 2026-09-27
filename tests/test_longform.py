"""
Long quizzes (pipeline.longform, decision 044).

Model calls, voice and rendering are faked or skipped. What's tested: a
short saves where its questions and answers are in its voice track; rounds
are chosen by difficulty or rising, and a round is used in one long video
only; the timeline lays questions, clocks and answers down in the right
order for both variants; the board clears each round away; a long video
publishes in its own lane, YouTube only; and an early short's timings are
rebuilt from its silences.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from core import gallery
from core.channels import ChannelConfig
from pipeline import longform, quiz
from pipeline.plan import WordTiming

FPS = 1000


def _channel():
    channel = ChannelConfig(key="pub_quiz", format="quiz", style_prompt="host")
    channel.quiz.questions = 3
    channel.quiz.difficulties = ["Easy", "Hard"]
    return channel


def _short(folder: Path, stem: str, category: str, difficulty: str, when: float = 0) -> Path:
    """A finished quiz short with its sidecar, as pipeline.run leaves it."""
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / f"{stem}.mp4"
    video.write_bytes(b"")
    (folder / f"{stem}_audio.mp3").write_bytes(b"")
    questions = [{"question": f"{category} Q{i}?", "answer": f"A{i}", "spoken_answer": f"A{i}.",
                  "ask_audio": [i * 10.0, i * 10.0 + 2], "answer_audio": [i * 10.0 + 6, i * 10.0 + 7]}
                 for i in range(3)]
    quiz.round_sidecar(video).write_text(json.dumps({
        "category": category, "difficulty": difficulty, "level": quiz.level_of(_channel(), difficulty),
        "audio": f"{stem}_audio.mp3", "questions": questions}), encoding="utf-8")
    if when:
        import os
        os.utime(video, (when, when))
    return video


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("core.gallery.PROJECT_ROOT", tmp_path)
    channel = _channel()
    channel.output_dir = "out"
    root = tmp_path / "out" / "2026-09-26"
    return SimpleNamespace(channel=channel, root=root, tmp=tmp_path)


def test_a_short_saves_where_its_questions_and_answers_are(tmp_path):
    channel = _channel()
    data = {"intro": "Hi, question one.", "outro": "Bye.", "title_options": ["t"], "description_body": "",
            "questions": [{"lead_in": "", "question": f"Q{i}?", "answer": f"A{i}",
                           "spoken_answer": f"A{i}."} for i in range(3)]}
    script = quiz.to_script(data, channel, "Science", "Hard")
    t = 0.0
    for seg in script.segments:
        seg.start = t
        t += 2 + (seg.pause_after or 0.4)
        seg.end = t
    plan = SimpleNamespace(script=script, channel=channel, audio_path=tmp_path / "v_audio.mp3",
                           video_path=tmp_path / "v.mp4")
    saved = json.loads(quiz.save_round(plan).read_text(encoding="utf-8"))
    first = saved["questions"][0]
    # The spoken part only: the clock and the pause after the answer are not in it.
    assert first["ask_audio"] == [2.4, 4.4] and first["answer_audio"] == [8.4, 10.4]
    assert saved["level"] == 5.5 and saved["audio"] == "v_audio.mp3"


class TestChoosing:
    def test_one_difficulty_distinct_categories_published_first(self, world):
        a = _short(world.root, "science_hard", "Science", "Hard", when=100)
        _short(world.root, "space_hard", "Space", "Hard", when=200)
        _short(world.root, "science_hard_2", "Science", "Hard", when=50)
        _short(world.root, "maths_easy", "Maths", "Easy")
        gallery.save_publish_info(a, {"youtube_url": "https://youtu.be/x"})
        picked = longform.choose_rounds(world.channel, "Hard", 3)
        assert [r["stem"] for r in picked] == ["science_hard", "space_hard"]
        assert longform.availability(world.channel) == {"Easy": 1, "Hard": 2, "rising": 3}

    def test_rising_climbs_and_a_used_round_is_never_reused(self, world):
        _short(world.root, "science_hard", "Science", "Hard")
        _short(world.root, "maths_easy", "Maths", "Easy")
        _short(world.root, "art_easy", "Art", "Easy")
        picked = longform.choose_rounds(world.channel, "rising", 2)
        assert [r["difficulty"] for r in picked] == ["Easy", "Hard"]
        long_dir = world.tmp / "out" / "longform" / "2026-09-27"
        long_dir.mkdir(parents=True)
        (long_dir / "quiz.mp4").write_bytes(b"")
        quiz.round_sidecar(long_dir / "quiz.mp4").write_text(json.dumps({"rounds": ["science_hard"]}))
        assert "science_hard" not in [r["stem"] for r in longform.available_rounds(world.channel)]
        # A discarded long video frees its rounds.
        gallery.set_discarded(long_dir / "quiz.mp4", True, "test")
        assert "science_hard" in [r["stem"] for r in longform.available_rounds(world.channel)]


def _laid_out(variant):
    channel = _channel()
    rows = [{"category": c, "difficulty": "Hard"} for c in ("Science", "Space")]
    sidecars = [{"questions": [{"question": f"Q{i}?", "answer": f"A{i}",
                                "ask_audio": [i * 10.0, i * 10.0 + 2],
                                "answer_audio": [i * 10.0 + 6, i * 10.0 + 7]} for i in range(3)]}
                for _ in rows]
    audio = np.ones((40 * FPS, 2), dtype=np.float32)
    # welcome, one round intro, (a finish line and a pens-down per round), sign-off
    links = [np.ones((FPS, 2), dtype=np.float32)] * (2 + 1 + (4 if variant == "at_end" else 0))
    return longform.build_timeline(channel, rows, sidecars, [audio, audio], links, variant, FPS)


class TestTimeline:
    def test_after_each_question_a_second_then_a_long_clock_then_the_answer(self):
        """The long format is played along with: a second after the question,
        ten seconds of clock (the shorts have four)."""
        track, timeline = _laid_out("after_each")
        q = timeline["rounds"][0]["questions"][0]
        assert q["countdown"][0] == pytest.approx(q["ask"][1] + longform.CLOCK_LEAD, abs=0.002)
        assert q["countdown"][1] - q["countdown"][0] == pytest.approx(10.0, abs=0.002)
        assert q["reveal"][0] == q["countdown"][1] and "reask" not in q
        assert len(track.samples()) / FPS == pytest.approx(timeline["end"], abs=0.01)

    def test_at_end_asks_all_then_rereads_each_before_its_answer(self):
        _, timeline = _laid_out("at_end")
        rnd = timeline["rounds"][1]
        last_clock = rnd["questions"][-1]["countdown"][1]
        # A spoken nudge, thirty seconds to finish off, then pens down.
        assert rnd["finish"]["line"][0] >= last_clock + longform.CLOCK_TAIL - 0.002
        c0, c1 = rnd["finish"]["clock"]
        assert c1 - c0 == pytest.approx(30.0, abs=0.002) and rnd["answers_intro"][0] > c1
        second = rnd["questions"][1]["ask"][0]
        assert second - rnd["questions"][0]["countdown"][1] == pytest.approx(longform.CLOCK_TAIL, abs=0.002)
        for q in rnd["questions"]:
            assert q["reask"][0] > rnd["answers_intro"][1]
            assert q["reveal"][0] == pytest.approx(q["reask"][1] + longform.REASK_GAP, abs=0.002)
        labels = [label for _, label in longform.chapters(timeline)]
        assert labels == ["Welcome", "Round 1: Science", "Round 1 answers", "Round 2: Space",
                          "Round 2 answers", "Scores"]
        cues = [k for _, k, _ in longform.cues(timeline)]
        # Six chimes; each ten-second clock and each finish ticks its last five seconds only.
        assert cues.count("chime") == 6 and cues.count("tock") == (6 + 2) * longform.TICKS

    def test_the_board_clears_each_round_and_turns_questions_into_answers(self):
        from pipeline.scenes import art
        _, timeline = _laid_out("at_end")
        page = longform.board_html(timeline, art.resolve({}), "The Pub Quiz", "2 rounds")
        end = timeline["rounds"][0]["end"]
        assert f"data-out='{end - 0.2:.3f}'" in page            # round 1's rows leave
        reveal = timeline["rounds"][0]["questions"][0]["reveal"][0]
        assert f"data-out='{reveal:.3f}'>Q0?" in page           # the question gives way...
        assert f"data-in='{reveal:.3f}' data-anim='fade' data-dur='0.5'>A0<" in page  # ...to its answer
        assert "width: 1920px; height: 1080px" in page
        assert "Finish your answers" in page and "with-timer" in page
        # The ring moves in tenths of a second, not every frame.
        assert "data-steps='100'" in page and "data-steps='300'" in page


def test_a_long_video_publishes_in_its_own_lane_youtube_only(world, monkeypatch):
    from core import publish_queue, youtube
    short = _short(world.root, "science_hard", "Science", "Hard")
    long_dir = world.tmp / "out" / "longform" / "2026-09-27"
    long_dir.mkdir(parents=True)
    long_video = long_dir / "quiz.mp4"
    long_video.write_bytes(b"")
    (long_dir / "quiz_thumb.jpg").write_bytes(b"jpg")
    for video in (short, long_video):
        publish_queue.enqueue(video, "you")
    assert publish_queue.queued(world.channel) == [short]
    assert publish_queue.queued(world.channel, long=True) == [long_video]
    world.channel.publishing.post_tiktok = True
    monkeypatch.setattr(youtube, "connection", lambda key: {"connected": True})
    monkeypatch.setattr(youtube, "upload", lambda *a, **k: {"id": "vid", "url": "https://youtu.be/vid"})
    thumbs = []
    monkeypatch.setattr(youtube, "set_thumbnail", lambda key, vid, path: thumbs.append(path.name))
    publish_queue.send(world.channel, long_video)
    assert thumbs == ["quiz_thumb.jpg"]
    assert gallery.load_publish_info(long_video)["handoff"] == {}      # never to TikTok


def test_an_early_shorts_timings_are_rebuilt_from_its_silences(tmp_path, monkeypatch):
    """Shorts made before sidecars: the clocks are the only long silences."""
    from pipeline import tts
    channel = _channel()
    fps = 100
    speech = lambda s: np.full((int(s * fps), 2), 0.3, dtype=np.float32)
    quiet = lambda s: np.zeros((int(s * fps), 2), dtype=np.float32)
    # intro, Q1, clock, A1 (with its own 1.1 s pause inside), pause, Q2, clock, A2, pause, Q3, clock, A3, pause, outro
    pieces = [speech(3), quiet(0.4), speech(2), quiet(4), speech(1), quiet(1.1), speech(1), quiet(1.3),
              speech(2), quiet(4), speech(1), quiet(1.3), speech(2), quiet(4), speech(1), quiet(1.3), speech(2)]
    audio = np.concatenate(pieces)
    monkeypatch.setattr("pipeline.audio.decode_audio_file", lambda path, fps=0, nchannels=2: audio)
    monkeypatch.setattr(tts, "SAMPLE_RATE", fps)
    monkeypatch.setattr(tts, "_get_whisper", lambda: SimpleNamespace(transcribe=lambda *a, **k: (
        [SimpleNamespace(words=[SimpleNamespace(word=" Hi", start=0.1), SimpleNamespace(word=" What", start=3.4),
                                SimpleNamespace(word=" is", start=3.6), SimpleNamespace(word=" one", start=3.8)])],
        None)))
    monkeypatch.setattr(quiz, "bank", lambda key: [{"video": "old", "questions": [
        {"question": "What is one?"}, {"question": "Two?"}, {"question": "Three?"}]}])
    video = tmp_path / "old.mp4"
    (tmp_path / "old_meta.txt").write_text(
        "[segment 0]\nHi\n\n[segment 1]\nWhat is one?\n\n[segment 2]\nMars, it's red.\n\n"
        "[segment 3]\nTwo?\n\n[segment 4]\nB. Bee.\n\n[segment 5]\nThree?\n\n[segment 6]\nC!\n\n"
        "[segment 7]\nBye\n", encoding="utf-8")
    data = longform.rebuild_round(channel, {"video": video, "category": "Science",
                                            "difficulty": "Easy", "level": 2.0})
    q1, q2 = data["questions"][0], data["questions"][1]
    assert q1["ask_audio"][0] == pytest.approx(3.32, abs=0.05)
    assert q1["ask_audio"][1] == pytest.approx(5.4, abs=0.05)
    # The answer runs through its own long pause to the inserted one after it.
    assert q1["answer_audio"] == pytest.approx([9.4, 12.5], abs=0.05)
    assert q2["ask_audio"][0] == pytest.approx(13.8, abs=0.05)
    assert [q["answer"] for q in data["questions"]] == ["Mars", "B", "C"]


def test_starting_one_needs_enough_rounds(world, monkeypatch):
    from web import create_app
    from core.channels import channel_to_sparse_dict, write_raw
    path = world.tmp / "channels.json"
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
    world.channel.voice = "21m00Tcm4TlvDq8ikWAM"
    write_raw({"pub_quiz": channel_to_sparse_dict(world.channel)}, path)
    _short(world.root, "science_hard", "Science", "Hard")
    client = create_app().test_client()
    page = client.get("/channels/pub_quiz/create").get_data(as_text=True)
    assert "A long quiz" in page and "Hard &mdash; 1 ready" in page
    token = page.split('name="csrf-token" content="')[1].split('"')[0]
    response = client.post("/api/channels/pub_quiz/longform", headers={"X-CSRF-Token": token},
                           json={"difficulty": "Hard", "rounds": 2, "variant": "at_end"})
    assert response.status_code == 400 and "1 of 2" in response.get_json()["error"]


def test_the_scheduler_makes_one_every_n_days_when_rounds_are_ready(world, monkeypatch):
    import os
    import time
    from core import jobs, scheduler
    world.channel.publishing.enabled = True
    world.channel.quiz.longform_rounds = 2
    started = []
    monkeypatch.setattr(jobs, "active_jobs", lambda: {})
    monkeypatch.setattr(jobs, "start_job", lambda key, seed: started.append(seed) or "job")
    _short(world.root, "science_hard", "Science", "Hard")
    channels = {"pub_quiz": world.channel}
    assert scheduler.fill_long_quizzes(channels) == []          # off by default
    world.channel.quiz.longform_every_days = 7
    assert scheduler.fill_long_quizzes(channels) == []          # only one round ready
    _short(world.root, "space_hard", "Space", "Hard")
    assert scheduler.fill_long_quizzes(channels) == ["pub_quiz"]
    assert started[0]["type"] == "longform" and started[0]["difficulty"] == "Hard"
    # And not again until a week after the last one.
    long_dir = world.tmp / "out" / "longform" / "2026-09-27"
    long_dir.mkdir(parents=True)
    (long_dir / "quiz.mp4").write_bytes(b"")
    assert scheduler.fill_long_quizzes(channels) == []
    old = time.time() - 8 * 86400
    os.utime(long_dir / "quiz.mp4", (old, old))
    assert scheduler.fill_long_quizzes(channels) == ["pub_quiz"]


def test_the_settings_form_sets_the_long_quiz_and_its_slots():
    from werkzeug.datastructures import MultiDict
    from web.forms import apply_channel_form
    channel = _channel()
    apply_channel_form(channel, MultiDict([
        ("quiz_present", "1"), ("format", "quiz"), ("quiz_longform_rounds", "8"),
        ("quiz_longform_variant", "at_end"), ("quiz_longform_every_days", "7"),
        ("publishing_plan_present", "1"), ("long_slots", "20:30, 9:00, noon"),
        ("long_weekdays", "5"), ("long_weekdays", "6")]))
    assert (channel.quiz.longform_rounds, channel.quiz.longform_variant,
            channel.quiz.longform_every_days) == (8, "at_end", 7)
    assert channel.publishing.long_slots == ["09:00", "20:30"]
    assert channel.publishing.long_weekdays == [5, 6]


def test_the_host_is_never_told_to_explain_the_format():
    """Regression: told how the answers worked, the host kept saying so
    ("question re-read before each one", "questions first each time")."""
    system = " ".join(longform.LINKS_SYSTEM.lower().split())
    assert "read again" not in system.split("never explain")[1].split("- welcome")[1]
    assert "never explain the format" in system and "no dashes" in system
    seen = {}
    monkey_rounds = [{"category": "Science", "difficulty": "Hard"}, {"category": "Space", "difficulty": "Hard"}]

    def call_json(system, user, schema, **kwargs):
        seen["user"] = user
        return {"welcome": "w", "round_intros": ["r"], "finish_lines": ["f1", "f2"],
                "answers_intros": ["a1", "a2"], "signoff": "s", "title_options": ["t"],
                "description": "d", "thumbnail_line": "l"}

    original = longform.call_json
    longform.call_json = call_json
    try:
        links = longform.write_links(_channel(), monkey_rounds, "at_end", "Hard")
    finally:
        longform.call_json = original
    assert "read again" not in seen["user"] and "re-read" not in seen["user"]
    assert longform.link_lines(links) == ["w", "r", "f1", "f2", "a1", "a2", "s"]


def test_spaced_dashes_and_misread_words_are_fixed_for_the_voice_only():
    from pipeline import tts
    assert tts.speakable("among the stars - Space answers") == "among the stars, Space answers"
    assert tts.speakable("a well-known one") == "a well-known one"
    said = tts.speakable("Au. From the Latin aurum.", {"Au": "A U"})
    assert said == "A U. From the Latin aurum."
    # A long silence inside one line is a glitch, and is re-voiced.
    words = [WordTiming("among", 0, 0.3), WordTiming("the", 0.35, 0.5), WordTiming("wall", 3.4, 3.8)]
    assert tts.looks_glitched("among the stars", words)
