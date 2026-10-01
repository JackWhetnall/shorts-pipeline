"""
Reviewing a quiz round question by question (pipeline.quiz_review,
decision 055), and using the app from a phone (core.phone_access). The
model is faked: what's tested is what a verdict does to the round and the
bank.

- too easy moves the question to the channel's next easier level in the
  bank, where re-rating leaves it, frees it for another round, and swaps
  in a question at the round's level, rewriting only that question's lines;
- wrong takes it out of the bank for good, with the reason;
- with nothing to replace it, the question stays, marked;
- a remake reuses the voice of every line that didn't change;
- a phone must give the access code; this PC never does.
"""

from __future__ import annotations

import json

import pytest

from core.channels import ChannelConfig
from pipeline import quiz, quiz_review
from pipeline.facts import bank, store


@pytest.fixture
def conn(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "facts.db")
    monkeypatch.setattr(quiz, "QUESTION_BANK_DIR", tmp_path / "banks")
    monkeypatch.setattr(quiz.curriculum, "exists", lambda key: False)
    monkeypatch.setattr(quiz_review, "host_lines",
                        lambda channel, script, index, new: ("Next up.", f"It's {new['answer']}."))
    return store.connect()


def _channel():
    channel = ChannelConfig(key="pub", format="quiz", style_prompt="A friendly host.")
    channel.quiz.difficulties = ["Easy", "Medium", "Hard"]         # levels 2, 4, 5.5
    channel.quiz.questions = 3
    return channel


def _add(conn, question, answer, level, area="Space"):
    return bank.add(conn, {"question": question, "answer": answer, "level": level, "shape": "name"},
                    "Science", area, "ok", "ok", "written")


def _script(conn, level=4):
    ids = [_add(conn, "Which planet is known as the Red Planet?", "Mars", level),
           _add(conn, "What gas do plants take in from the air?", "Carbon dioxide", level, "Plants"),
           _add(conn, "How many legs does an insect have?", "Six", level, "Animals")]
    data = {"hook": "Science time.", "intro": "Here we go.", "outro": "Bye.",
            "questions": [{"lead_in": "" if i == 0 else f"Question {i + 1}.", "question": q, "answer": a,
                           "spoken_answer": f"{a}!", "bank_id": qid}
                          for i, (q, a, qid) in enumerate([
                              ("Which planet is known as the Red Planet?", "Mars", ids[0]),
                              ("What gas do plants take in from the air?", "Carbon dioxide", ids[1]),
                              ("How many legs does an insect have?", "Six", ids[2])])]}
    bank.mark_used(conn, "pub", ids)
    return quiz.to_script(data, _channel(), "Science", "Medium").to_jsonable(), ids


def test_too_easy_moves_it_down_a_level_frees_it_and_swaps_in_another(conn):
    script, ids = _script(conn)
    spare = _add(conn, "Which organ pumps blood around the body?", "Heart", 4, "Body")
    result = quiz_review.judge(_channel(), script, 1, "easy")
    assert result["swapped"] and result["moved_to"] == 2.0
    moved = conn.execute("SELECT level, owner_level FROM questions WHERE id = ?", (ids[1],)).fetchone()
    assert tuple(moved) == (2.0, 2.0)
    used = {r[0] for r in conn.execute("SELECT question_id FROM question_used WHERE channel = 'pub'")}
    assert ids[1] not in used and spare in used                  # free for an easier round; the new one taken
    q = script["quiz"]["questions"][1]
    assert (q["question"], q["bank_id"]) == ("Which organ pumps blood around the body?", spare)
    assert script["segments"][q["ask"]]["text"] == "Next up. Which organ pumps blood around the body?"
    assert script["segments"][q["reveal"]]["text"] == "It's Heart."
    assert script["segments"][script["quiz"]["questions"][2]["ask"]]["text"].startswith("Question 3.")
    assert script["quiz"]["review"][0]["verdict"] == "easy"


def test_re_rating_keeps_the_owners_level(conn, monkeypatch):
    from pipeline.facts import rate
    qid = _add(conn, "Which planet is known as the Red Planet?", "Mars", 4)
    bank.set_owner_level(conn, qid, 2)
    monkeypatch.setattr(rate, "rate", lambda questions: [(40.0, False)] * len(questions))
    rate.rate_bank(conn, only_unrated=False)
    assert conn.execute("SELECT level, known_pct FROM questions WHERE id = ?", (qid,)).fetchone()[0] == 2.0


def test_wrong_takes_it_out_of_the_bank_with_the_reason(conn):
    script, ids = _script(conn)
    _add(conn, "Which organ pumps blood around the body?", "Heart", 4, "Body")
    quiz_review.judge(_channel(), script, 0, "invalid", "two right answers")
    status, verdict = conn.execute("SELECT status, verdict FROM questions WHERE id = ?", (ids[0],)).fetchone()
    assert status == "rejected" and verdict == "owner: two right answers"
    assert script["quiz"]["questions"][0]["answer"] == "Heart"
    assert script["segments"][script["quiz"]["questions"][0]["ask"]]["text"] == \
        "Which organ pumps blood around the body?"               # the first question has no lead-in


def test_a_replacement_mustnt_clash_with_the_round(conn):
    script, _ = _script(conn)
    _add(conn, "Which planet is nicknamed the Red Planet by astronomers?", "Mars", 4, "Planets")
    _add(conn, "What is the chemical symbol for gold?", "Au", 4, "Elements")
    quiz_review.judge(_channel(), script, 2, "hard")
    assert script["quiz"]["questions"][2]["answer"] == "Au"


def test_with_nothing_to_replace_it_the_question_stays_marked(conn, monkeypatch):
    script, _ = _script(conn)
    monkeypatch.setattr(bank, "write_batch", lambda *a, **k: {"kept": 0})
    result = quiz_review.judge(_channel(), script, 1, "invalid")
    assert not result["swapped"] and script["quiz"]["questions"][1]["flagged"] == "invalid"
    assert script["quiz"]["questions"][1]["answer"] == "Carbon dioxide"


def test_fine_keeps_it_and_clears_the_fact_check_hold(conn):
    script, ids = _script(conn)
    script["quiz"]["unverified"] = [1, 3]
    quiz_review.judge(_channel(), script, 0, "ok")
    assert script["quiz"]["questions"][0]["approved"] and script["quiz"]["unverified"] == [3]
    assert conn.execute("SELECT owner_level FROM questions WHERE id = ?", (ids[0],)).fetchone()[0] == 4.0


def test_a_question_from_outside_the_bank_is_taken_in_when_moved(conn):
    script, _ = _script(conn)
    q = script["quiz"]["questions"][2]
    q.pop("bank_id")
    q["question"], q["answer"] = "What colour is a ripe banana?", "Yellow"
    quiz_review.judge(_channel(), script, 2, "easy", )
    row = conn.execute("SELECT level, owner_level, status FROM questions WHERE question = ?",
                       ("What colour is a ripe banana?",)).fetchone()
    assert tuple(row) == (2.0, 2.0, "ok")


def test_levels_step_to_the_channels_neighbours():
    channel = _channel()
    assert quiz_review.neighbour_level(channel, 4, -1) == 2.0
    assert quiz_review.neighbour_level(channel, 4, 1) == 5.5
    assert quiz_review.neighbour_level(channel, 5.5, 1) == 7.0     # beyond the hardest
    assert quiz_review.neighbour_level(channel, 2, -1) == 1.0


def test_a_made_shorts_draft_records_what_changed(conn, tmp_path):
    script, _ = _script(conn)
    video = tmp_path / "science_medium.mp4"
    video.write_bytes(b"")
    quiz.script_sidecar(video).write_text(json.dumps(script), encoding="utf-8")
    _add(conn, "Which organ pumps blood around the body?", "Heart", 4, "Body")
    drafted = quiz_review.draft(_channel(), video)
    quiz_review.judge(_channel(), drafted, 1, "hard")
    quiz_review.save_draft(video, drafted)
    assert quiz_review.swapped(_channel(), video) == [2]
    assert quiz_review.made_script(_channel(), video)["quiz"]["questions"][1]["answer"] == "Carbon dioxide"


def test_forgetting_a_remade_round_lets_its_questions_be_asked_again(conn):
    script, _ = _script(conn)
    from pipeline.plan import Script
    quiz.remember("pub", "science_medium", Script.from_jsonable(script))
    candidate = {"question": "How many legs does an insect have?", "answer": "Six"}
    assert quiz.repeats([candidate], "pub") == [0]
    assert quiz.forget("pub", "science_medium")
    assert quiz.repeats([candidate], "pub") == []


# --- the voice of a remake ---------------------------------------------------------

def test_a_remake_reuses_every_unchanged_lines_voice(monkeypatch, tmp_path):
    import numpy as np
    from core.channels import Pacing
    from pipeline import tts
    from pipeline.plan import Segment, WordTiming
    monkeypatch.setattr(tts, "VOICE_CACHE_DIR", tmp_path / "voices")
    said = []

    def fake(text, voice_id, out_path, speed=1.0, **kw):
        said.append(text)
        open(out_path, "wb").write(b"mp3")
        return [WordTiming(text.split()[0], 0.0, 0.5)], np.zeros((4410, 1)), tts.SAMPLE_RATE

    monkeypatch.setattr(tts, "synthesize_segment", fake)
    monkeypatch.setattr(tts, "decode_audio_file", lambda path, fps: np.zeros((4410, 1)))
    monkeypatch.setattr(tts, "_stitch", lambda results, segments, out: ([], np.zeros((1, 1)), tts.SAMPLE_RATE))
    lines = [Segment("Hello there."), Segment("Which planet is red?"), Segment("Mars.")]
    tts.generate_voiceover(lines, None, "v", str(tmp_path / "a.mp3"), Pacing())
    assert len(said) == 3
    said.clear()
    lines[2] = Segment("Jupiter.")
    assert tts.characters_to_voice(lines, None, Pacing(), 0, "v", 1.0, reuse=True) == len("Jupiter.")
    tts.generate_voiceover(lines, None, "v", str(tmp_path / "b.mp3"), Pacing(), reuse=True)
    assert said == ["Jupiter."]
    said.clear()
    tts.generate_voiceover(lines, None, "v", str(tmp_path / "c.mp3"), Pacing())
    assert len(said) == 3                                        # not a remake: voiced afresh


def test_a_remake_is_carried_by_its_seed():
    from pipeline.plan import Seed
    seed = Seed(type="topic", topic="Science: Medium", topic_id="t1", number=4, remake_of="science_medium")
    assert Seed.from_jsonable(seed.to_jsonable()).remake_of == "science_medium"
    assert "remake_of" not in Seed(type="topic", topic="x").to_jsonable()


# --- phone access ------------------------------------------------------------------

@pytest.fixture
def phone(monkeypatch, tmp_path):
    from core import phone_access
    monkeypatch.setattr(phone_access, "PATH", tmp_path / "phone.json")
    monkeypatch.setattr(phone_access, "_tries", {})
    from web import create_app
    app = create_app()
    app.config["TESTING"] = True
    return phone_access, app.test_client()


LAN = {"REMOTE_ADDR": "192.168.1.20"}


def test_this_pc_never_needs_the_code(phone):
    _, client = phone
    assert client.get("/m/sign-in").status_code == 200
    assert client.get("/phone").status_code == 200


def test_a_phone_is_refused_while_phone_access_is_off(phone):
    _, client = phone
    assert client.get("/m", environ_base=LAN).status_code == 403


def test_a_phone_signs_in_with_the_code_and_stays_signed_in(phone):
    phone_access, client = phone
    code = phone_access.set_enabled(True)["code"]
    first = client.get("/m/review", environ_base=LAN)
    assert first.status_code == 302 and "/m/sign-in" in first.headers["Location"]
    client.get("/m/sign-in", environ_base=LAN)
    with client.session_transaction() as s:
        token = s["_csrf_token"]
    signed = client.post("/m/sign-in", data={"code": code, "next": "/m/review", "csrf_token": token},
                         environ_base=LAN)
    assert signed.status_code == 302 and signed.headers["Location"].endswith("/m/review")
    assert client.get("/m", environ_base=LAN).status_code == 200
    phone_access.change_code()                                    # a new code signs phones out
    assert client.get("/m", environ_base=LAN).status_code == 302


def test_wrong_codes_run_out(phone):
    phone_access, _ = phone
    code = phone_access.set_enabled(True)["code"]
    for _ in range(phone_access.MAX_TRIES):
        assert not phone_access.check("192.168.1.20", "000000" if code != "000000" else "111111")
    assert not phone_access.check("192.168.1.20", code)           # even the right one, for a while
    assert phone_access.check("192.168.1.21", code)


def test_a_phone_cant_turn_phone_access_on_or_off(phone):
    phone_access, client = phone
    phone_access.set_enabled(True)
    with client.session_transaction() as s:
        s["phone"] = phone_access.token()
    assert client.get("/phone", environ_base=LAN).status_code == 403


def test_signing_in_only_sends_you_somewhere_in_the_app():
    from web import create_app
    from web.blueprints.phone import _safe_next
    with create_app().test_request_context():
        assert _safe_next("/m/review") == "/m/review"
        assert _safe_next("//evil.example/") == "/m"
        assert _safe_next("https://evil.example/") == "/m"


def test_remaking_discards_the_short_and_makes_its_round_again_from_the_draft(conn, monkeypatch, tmp_path):
    """The owner: a round with one bad question is swapped and remade, not
    written again from scratch."""
    from web import create_app
    from web.blueprints import quiz_review as page
    script, _ = _script(conn)
    video = tmp_path / "science_medium.mp4"
    video.write_bytes(b"")
    quiz.script_sidecar(video).write_text(json.dumps(script), encoding="utf-8")
    quiz.round_sidecar(video).write_text(json.dumps({"number": 7, "questions": []}), encoding="utf-8")
    drafted = json.loads(json.dumps(script))
    drafted["quiz"]["questions"][1]["question"] = "Which organ pumps blood around the body?"
    quiz_review.save_draft(video, drafted)
    done = {}
    monkeypatch.setattr(page, "video_or_404", lambda relpath: video)
    monkeypatch.setattr(page, "_channel_of", lambda v: _channel())
    monkeypatch.setattr(page.curriculum, "exists", lambda key: True)
    monkeypatch.setattr(page.curriculum, "subtopics", lambda key: [
        {"id": "t9", "title": "Science: Medium", "video_stem": "science_medium"}])
    monkeypatch.setattr(page.curriculum, "set_script", lambda key, sid, s: done.update(script=(sid, s)))
    from core import remake
    monkeypatch.setattr(remake, "start", lambda channel, v, script=None: done.update(remade=(v, script)))
    client = create_app().test_client()
    client.get("/m/sign-in")
    with client.session_transaction() as s:
        token = s["_csrf_token"]
    assert client.post("/videos/x/questions/remake", data={"csrf_token": token}).status_code == 302
    assert done["script"][0] == "t9" and done["script"][1]["quiz"]["questions"][1]["question"].startswith("Which organ")
    assert done["remade"][0] == video and done["remade"][1] == done["script"][1]
    assert not quiz_review.draft_path(video).exists()


def test_a_short_made_before_scripts_were_kept_is_rebuilt_from_its_meta(conn, tmp_path):
    """The three shorts waiting for review when question review arrived had
    no script beside them; their lines are all in _meta.txt."""
    video = tmp_path / "general_knowledge_easy.mp4"
    video.write_bytes(b"")
    qid = _add(conn, "What is the capital city of France?", "Paris", 2, "Capitals")
    video.with_name("general_knowledge_easy_meta.txt").write_text(
        "Title options:\n  - Easy Round\n  - Ten Easy Ones\n\n"
        "[segment 0]\nFancy your chances?\n\n[segment 1]\nLet's go.\n\n"
        "[segment 2]\nWhat is the capital city of France?\n\n[segment 3]\nParis, of course.\n\n"
        "[segment 4]\nLast one. How many legs does an insect have?\n\n[segment 5]\nSix.\n\n"
        "[segment 6]\nHow many did you get?\n\n", encoding="utf-8")
    video.with_name("general_knowledge_easy_description.txt").write_text(
        "An easy round.\n\nSupport us: https://example.com", encoding="utf-8")
    quiz.round_sidecar(video).write_text(json.dumps({"category": "General Knowledge", "difficulty": "Easy",
        "number": 2, "questions": [{"question": "What is the capital city of France?", "answer": "Paris"},
                                   {"question": "How many legs does an insect have?", "answer": "Six"}]}),
        encoding="utf-8")
    script = quiz_review.made_script(_channel(), video)
    qs = script["quiz"]["questions"]
    assert [(q["ask"], q["reveal"]) for q in qs] == [(2, 3), (4, 5)]
    assert qs[0]["bank_id"] == qid and qs[1]["spoken_answer"] == "Six."
    assert script["quiz"]["hook"] == "Fancy your chances?" and script["title_options"][1] == "Ten Easy Ones"
    assert script["description_body"] == "An easy round."
    assert script["segments"][2]["pause_after"] == float(_channel().quiz.countdown_seconds)
    assert quiz_review.lead_in_of(script, qs[1]) == "Last one."
    from pipeline.plan import Script
    assert Script.from_jsonable(script).quiz["questions"][1]["answer"] == "Six"
