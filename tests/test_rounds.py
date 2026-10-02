"""
Quiz rounds made ahead (pipeline.facts.rounds, decision 062). The owner:
a second set of General Knowledge should be ready to go, with no
calculation and no model calls; a round's difficulty should be
consistent; and a category that's running out should say so rather than
writing questions mid-script.
"""

from __future__ import annotations

import json

import pytest

from core.channels import ChannelConfig
from pipeline.facts import bank, rounds, store


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "facts.db")
    conn = store.connect()
    channel = ChannelConfig(key="buzz", format="quiz")
    channel.quiz.questions = 3
    channel.quiz.difficulties = ["Easy (2)", "Hard (6)"]
    monkeypatch.setattr("pipeline.facts.keep.quiz_categories", lambda c: ["Science", "General Knowledge"])
    monkeypatch.setattr("pipeline.quiz._all_questions", lambda key: [])
    return conn, channel


WORDS = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa " \
        "quebec romeo sierra tango uniform victor whisky xray yankee zulu".split()


def _stock(conn, category, level, n, start=0):
    ids = []
    for i in range(start, start + n):
        word = WORDS[i % len(WORDS)] + str(i)
        ids.append(bank.add(conn, {"question": f"What is the {word} thing?", "answer": f"Z{word}",
                                   "level": level, "shape": ["name", "only", "first"][i % 3]},
                            category, f"Area {i % 4}", "ok", "ok", "written"))
    return ids


def test_rounds_are_made_ahead_within_their_level_and_share_nothing(world):
    conn, channel = world
    _stock(conn, "Science", 2, 12)
    _stock(conn, "Science", 6, 12, start=40)
    made = rounds.assemble(conn, channel)
    assert made["Science"] == {"Easy": 3, "Hard": 3}
    seen = set()
    for row in conn.execute("SELECT * FROM ready_rounds WHERE category = 'Science'"):
        ids = json.loads(row["questions"])
        levels = [conn.execute("SELECT level FROM questions WHERE id = ?", (i,)).fetchone()[0] for i in ids]
        assert len(ids) == 3 and not seen & set(ids)
        assert all(abs(lv - row["level"]) <= 1.25 for lv in levels) and levels == sorted(levels)
        seen |= set(ids)


def test_a_category_short_of_questions_has_fewer_rounds_and_says_so(world):
    conn, channel = world
    _stock(conn, "Science", 2, 4)              # one Easy round's worth, no Hard
    rounds.assemble(conn, channel)
    status = rounds.status(conn, channel)["Science"]
    assert status["sets"] == 0 and status["short"] == ["Hard"] and status["state"] == "dry"
    _stock(conn, "Science", 6, 12, start=40)
    _stock(conn, "Science", 2, 12, start=60)
    rounds.assemble(conn, channel)
    assert rounds.status(conn, channel)["Science"]["state"] == "ready"


def test_general_knowledge_takes_what_the_named_categories_leave(world):
    conn, channel = world
    _stock(conn, "Science", 2, 9)
    rounds.assemble(conn, channel)
    science = {i for (q,) in conn.execute("SELECT questions FROM ready_rounds WHERE category = 'Science'")
               for i in json.loads(q)}
    general = {i for (q,) in conn.execute(
        "SELECT questions FROM ready_rounds WHERE category = 'General Knowledge'") for i in json.loads(q)}
    assert len(science) == 9 and not general & science


def test_a_plan_entry_claims_a_round_once_and_using_it_spends_it(world):
    conn, channel = world
    _stock(conn, "Science", 2, 12)
    rounds.assemble(conn, channel)
    first = rounds.claim(conn, "buzz", "Science", "Easy", "s1")
    assert rounds.claim(conn, "buzz", "Science", "Easy", "s1")["id"] == first["id"]       # the same one
    assert rounds.ready(conn, "buzz", "Science", "Easy") == 2
    assert rounds.available(conn, "buzz", "Science", "Easy", "s1")
    rounds.used(conn, first["id"])
    assert len(rounds.questions_of(conn, first)) == 3
    rounds.release(conn, "buzz", "s2")
    assert rounds.claim(conn, "buzz", "Science", "Hard", "s3") is None


def test_a_question_taken_out_of_the_bank_leaves_its_round(world):
    conn, channel = world
    _stock(conn, "Science", 2, 6)
    rounds.assemble(conn, channel)
    row = rounds.claim(conn, "buzz", "Science", "Easy", "s1")
    first = json.loads(row["questions"])[0]
    bank.reject(conn, first, "wrong")
    assert first not in [q["bank_id"] for q in rounds.questions_of(conn, row)]


def test_another_set_is_planned_only_when_one_is_ready(world, monkeypatch, tmp_path):
    from core import curriculum
    from pipeline import quiz
    conn, channel = world
    monkeypatch.setattr("core.curriculum.CURRICULA_DIR", tmp_path / "curricula")
    data = curriculum.start("buzz", "quiz", [{"title": "Science"}])
    topic = data["topics"][0]["id"]
    curriculum.add_subtopics("buzz", topic, quiz.subtopic_rows("Science", channel.quiz.difficulties))
    assert quiz.next_round(channel, topic) == 0                       # nothing ready: no new set
    _stock(conn, "Science", 2, 12)
    _stock(conn, "Science", 6, 12, start=40)
    rounds.assemble(conn, channel)
    assert quiz.next_round(channel, topic) == 2
    new = [s for s in curriculum.subtopics("buzz") if "(round 2)" in s["title"]]
    assert all(conn.execute("SELECT 1 FROM ready_rounds WHERE subtopic = ?", (s["id"],)).fetchone() for s in new)


def test_making_a_round_takes_its_questions_without_writing_any(world, monkeypatch):
    from pipeline import quiz
    conn, channel = world
    _stock(conn, "Science", 2, 6)
    rounds.assemble(conn, channel)
    asked = []
    monkeypatch.setattr(quiz, "_round_from_bank", lambda c, cat, diff, qs: asked.append(qs) or "script")
    assert quiz._ready_round(channel, "Science", "Easy", "s1") == "script"
    assert len(asked[0]) == 3 and all(q["bank_id"] for q in asked[0])
    assert conn.execute("SELECT used_at FROM ready_rounds WHERE subtopic = 's1'").fetchone()[0]
