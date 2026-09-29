"""
The question bank (pipeline.facts.bank, decision 050). The model and the
fact check are faked: what's tested is what the bank does with them.

- a batch's repeats are dropped, what fails the check is kept as
  rejected (so it's never written again), tags are only known categories;
- the same fact asked again is a repeat; the same answer to a different
  question isn't;
- a round draws unused checked questions near its level, one per answer,
  and is used once per channel;
- a round from the bank keeps its questions word for word and isn't
  checked again;
- stocking writes where a channel is shortest, within its limits.
"""

from __future__ import annotations

import pytest

from core.channels import ChannelConfig
from pipeline.facts import bank, keep, store


def _q(question, answer, level=4, shape="name", tags=()):
    return {"question": question, "answer": answer, "alternatives": [], "note": "", "level": level,
            "shape": shape, "tags": list(tags)}


def test_answers_compare_without_case_articles_or_plurals():
    assert bank.answer_key("The Earthquakes") == bank.answer_key("earthquake")
    assert bank.answer_key("Glass") == "glass"


def test_a_question_that_asks_twice_is_malformed():
    assert bank.malformed("What is the process called by which nature favours traits called?")
    assert bank.malformed("What is the name of the boundary layer called?")
    assert bank.malformed("What is the general term for offspring inheriting traits called?")
    assert not bank.malformed("What is the study of earthquakes called?")
    assert bank.malformed("Name the largest planet")
    assert not bank.malformed("What do we call animals that have a backbone?")


def test_the_same_fact_again_is_a_repeat_but_the_same_answer_elsewhere_isnt():
    existing = [("What is the capital of France?", "Paris")]
    assert bank.is_repeat("Which city is the capital of France?", "Paris", existing)
    assert not bank.is_repeat("In which city is the Louvre museum?", "Paris", existing)


def test_a_batch_is_checked_deduplicated_and_tagged(monkeypatch, tmp_path):
    from pipeline import quiz, llm
    conn = store.connect(tmp_path / "f.db")
    bank.add(conn, _q("What is the largest ocean on Earth?", "Pacific Ocean"), "Geography", "Oceans", "ok", "ok",
             "written")
    monkeypatch.setattr(bank, "areas", lambda conn, category: ["Oceans"])
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"questions": [
        _q("Which is the largest ocean on Earth?", "The Pacific", tags=["Science", "Made Up"]),
        _q("What is the saltiest large sea?", "Dead Sea", level=14, tags=["Science"]),
        _q("Which sea has no coastline?", "Sargasso Sea"),
    ]})
    monkeypatch.setattr(quiz, "verify", lambda category, difficulty, qs, operation="": (
        ["ok" if q["answer"] != "Sargasso Sea" else "wrong" for q in qs]))
    result = bank.write_batch(conn, "Geography", 4, ["Geography", "Science"])
    assert result == {"written": 3, "kept": 1, "rejected": 1, "repeats": 1}
    row = conn.execute("SELECT * FROM questions WHERE answer = 'Dead Sea'").fetchone()
    assert row["level"] == 10 and row["status"] == "ok"
    tags = {r[0] for r in conn.execute("SELECT category FROM question_tags WHERE question_id = ?", (row["id"],))}
    assert tags == {"Geography", "Science"}
    rejected = conn.execute("SELECT status FROM questions WHERE answer = 'Sargasso Sea'").fetchone()[0]
    assert rejected == "rejected"


WORDS = ("volcano glacier comet enzyme proton neuron galaxy fossil crystal magnet photon quasar tundra "
         "delta plasma nebula mantle cortex spleen retina isotope alloy lichen algae coral geyser "
         "monsoon aurora tsunami meteor").split()


def _stock(conn, n=30, category="Science"):
    for i in range(n):
        bank.add(conn, _q(f"What is special about the {WORDS[i]}?", f"Answer {WORDS[i]}", level=1 + (i % 10),
                          shape=["name", "superlative", "only"][i % 3]),
                 category, f"Area {i % 5}", "ok", "ok", "written")


def test_a_round_draws_unused_questions_near_its_level_once_per_channel(tmp_path):
    conn = store.connect(tmp_path / "f.db")
    _stock(conn)
    chosen = bank.for_round(conn, "pub", "Science", 5, 3, seed=1)
    assert len(chosen) == 3 and all(abs(q["level"] - 5) <= 2 for q in chosen)
    assert len({q["answer_key"] for q in chosen}) == 3
    bank.mark_used(conn, "pub", [q["id"] for q in chosen])
    again = bank.for_round(conn, "pub", "Science", 5, 30)
    assert not {q["id"] for q in chosen} & {q["id"] for q in again}
    # General knowledge draws on every category.
    assert len(bank.pool(conn, "other", "General Knowledge")) == 30


class TestRoundsFromTheBank:
    def _channel(self):
        channel = ChannelConfig(key="pub", format="quiz", style_prompt="host")
        channel.quiz.questions = 3
        return channel

    def test_the_questions_stay_word_for_word_and_arent_checked_again(self, monkeypatch):
        from pipeline import quiz
        conn = store.connect()
        _stock(conn)
        monkeypatch.setattr(quiz, "verify", lambda *a, **k: pytest.fail("checked again"))
        monkeypatch.setattr(quiz, "call_json", lambda system, user, schema, **k: {
            "hook": "Know your science?", "intro": "Question one.", "outro": "Bye.",
            "title_options": ["Science"], "description_body": "d",
            "questions": [{"number": n, "lead_in": f"Number {n}.", "spoken_answer": f"It's answer {n}."}
                          for n in (1, 2, 3)]})
        script = quiz._write_checked(self._channel(), "Science", "Hard")
        stored = {r["question"]: r["answer"] for r in conn.execute("SELECT question, answer FROM questions")}
        for q in script.quiz["questions"]:
            assert stored[q["question"]] == q["answer"] and q.get("bank_id")
        assert script.quiz["questions"][0]["spoken_answer"] == "It's answer 1."
        assert store.connect().execute("SELECT COUNT(*) FROM question_used WHERE channel = 'pub'").fetchone()[0] == 3

    def test_without_enough_in_the_bank_the_round_is_written_as_before(self, monkeypatch):
        from pipeline import quiz
        assert quiz._bank_questions(self._channel(), "Science", "Hard", 3) == []


def test_stocking_writes_where_shortest_within_its_limits(monkeypatch, tmp_path):
    from core import curriculum
    conn = store.connect(tmp_path / "f.db")
    channel = ChannelConfig(key="pub", format="quiz")
    channel.quiz.difficulties = ["Easy", "Hard"]
    monkeypatch.setattr(keep, "quiz_categories", lambda channel: ["Science", "Music"])
    written = []
    monkeypatch.setattr(bank, "write_batch", lambda conn, name, level, names: written.append((name, level)))
    monkeypatch.setattr(keep, "BANK_BATCHES", 3)
    monkeypatch.setattr(bank, "spent_today", lambda: 0.0)
    keep.stock_bank(conn, channel)
    assert len(written) == 3
    written.clear()
    monkeypatch.setattr(bank, "spent_today", lambda: 99.0)
    assert "budget" in keep.stock_bank(conn, channel, say=lambda m: written.append(m) or None) or written
    assert not [w for w in written if isinstance(w, tuple)]


def test_the_day_spend_counts_only_the_banks_own_calls(monkeypatch):
    import time
    from core import costs
    now = time.time()
    monkeypatch.setattr(costs, "read_records", lambda: [
        {"operation": "bank_write", "ts": now - 60, "cost_usd": 0.05},
        {"operation": "bank_verify", "ts": now - 60, "cost_usd": 0.02},
        {"operation": "quiz_verify", "ts": now - 60, "cost_usd": 0.50},
        {"operation": "bank_write", "ts": now - 90000, "cost_usd": 1.00}])
    assert bank.spent_today() == pytest.approx(0.07)


def test_a_round_the_bank_cant_supply_writes_bank_questions_first(monkeypatch):
    """Regression: with the bank short, a Fiendish Geography round fell back
    to stored facts ("the highest peak of Euboea") instead of writing
    proper pub-quiz questions."""
    from pipeline import quiz
    channel = ChannelConfig(key="pub", format="quiz", style_prompt="host")
    channel.quiz.questions = 3

    def write_batch(conn, category, level, names, *args, **kwargs):
        _stock(conn, 30, category)
        return {"kept": 30}
    monkeypatch.setattr(bank, "write_batch", write_batch)
    monkeypatch.setattr(quiz, "_facts", lambda *a, **k: pytest.fail("fell back to facts"))
    monkeypatch.setattr(quiz, "call_json", lambda system, user, schema, **k: {
        "hook": "Know your places?", "intro": "Question one.", "outro": "Bye.", "title_options": ["t"],
        "description_body": "d", "questions": [{"number": n, "lead_in": "", "spoken_answer": "x"} for n in (1, 2, 3)]})
    script = quiz._write_checked(channel, "Geography", "Fiendish")
    assert all(q.get("bank_id") for q in script.quiz["questions"])
