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
from pipeline.facts import bank, keep, scope, store


@pytest.fixture(autouse=True)
def _scopes_known(monkeypatch):
    """Every category's scope is already written and the bank sorted to it
    (pipeline.facts.scope has its own tests), so the faked model here only
    answers for batches."""
    monkeypatch.setattr(scope, "ensure", lambda conn, name, names: {"covers": f"All about {name}.",
                                                                    "excludes": ""})
    monkeypatch.setattr(scope, "sort_if_needed", lambda conn, names, say=None: False)
    monkeypatch.setattr(scope, "file_new", lambda conn, ids, names, say=None: {})


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
    assert result == {"written": 3, "kept": 1, "rejected": 1, "repeats": 1, "levels": [10.0]}
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


class TestDifficulty:
    """Regression: an Easy round asked for Diners Club (the first credit
    card) and "cask": the writer, asked for level 2, called them level 2."""

    def test_the_level_comes_from_the_share_of_people_who_know_it(self):
        from pipeline.facts import rate
        assert rate.level_for(95, True) == 1 and rate.level_for(82, True) == 2
        assert rate.level_for(15, False) == 8 and rate.level_for(3, False) == 10
        # The easy levels also need a ten-year-old to have a good guess.
        assert rate.level_for(92, False) == 3

    def test_a_batch_is_levelled_by_the_rater_not_the_writer(self, monkeypatch, tmp_path):
        from pipeline import llm, quiz
        from pipeline.facts import rate
        conn = store.connect(tmp_path / "f.db")
        monkeypatch.setattr(bank, "areas", lambda conn, category: ["Money"])
        monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"questions": [
            _q("Which company issued the first credit card?", "Diners Club", level=2)]})
        monkeypatch.setattr(quiz, "verify", lambda *a, **k: ["ok"])
        monkeypatch.setattr(rate, "rate", lambda qs: [(15.0, False)])
        bank.write_batch(conn, "Business", 2, ["Business"])
        row = conn.execute("SELECT level, known_pct FROM questions").fetchone()
        assert (row[0], row[1]) == (8, 15)

    def test_an_easy_round_never_widens_towards_harder(self, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        _stock(conn)       # levels 1-10, three at each
        chosen = bank.for_round(conn, "pub", "Science", 1.5, 10)
        assert chosen and max(q["level"] for q in chosen) <= 2.25


def test_a_round_takes_its_own_categorys_questions_before_borrowed_ones(tmp_path):
    """Regression: a Geography round was Senna, the Nurburgring and a cash
    machine: sport and firsts questions tagged Geography."""
    conn = store.connect(tmp_path / "f.db")
    import json
    with conn:
        conn.execute("INSERT INTO bank_areas (category, areas) VALUES ('Geography', ?)", (json.dumps(["Rivers"]),))
    for i, w in enumerate(WORDS[:8]):
        bank.add(conn, _q(f"Which river is the {w}?", f"River {w}", level=5), "Geography", "Rivers", "ok", "ok",
                 "written")
        bank.add(conn, _q(f"Which racetrack is the {w}?", f"Track {w}", level=5, tags=["Geography"]), "Sport",
                 "Motorsport", "ok", "ok", "written", ["Geography", "Sport"])
    chosen = bank.for_round(conn, "pub", "Geography", 5, 6)
    assert all(q["area"] == "Rivers" for q in chosen)
    assert not bank.for_round(conn, "pub", "Geography", 5, 12, borrow=False)[8:]
    assert bank.counts(conn, "pub", "Geography", [("Hard", 5)])["Hard"] == 8


def test_clearing_written_scripts_gives_their_questions_back(monkeypatch, tmp_path):
    """The owner: scripts written by earlier versions should be clearable in
    one go, to be written afresh."""
    from core import curriculum
    monkeypatch.setattr(curriculum, "CURRICULUM_DIR", tmp_path, raising=False)
    conn = store.connect(tmp_path / "f.db")
    _stock(conn, 3)
    bank.mark_used(conn, "pub", [1, 2])
    data = {"topics": [{"id": "t1", "title": "Science"}], "subtopics": [
        {"id": "s1", "topic": "t1", "title": "Science: Easy", "status": curriculum.PENDING,
         "script": {"quiz": {"questions": [{"bank_id": 1}, {"bank_id": 2}]}}},
        {"id": "s2", "topic": "t1", "title": "Science: Hard", "status": curriculum.USED,
         "script": {"quiz": {"questions": [{"bank_id": 3}]}}}]}
    monkeypatch.setattr(curriculum, "load", lambda key: data)
    monkeypatch.setattr(curriculum, "save", lambda d: None)
    removed = curriculum.clear_scripts("pub")
    assert len(removed) == 1 and data["subtopics"][0]["script"] is None
    assert data["subtopics"][1]["script"] is not None          # a made video's script stays
    assert bank.release(conn, "pub", removed) == 2
    assert conn.execute("SELECT COUNT(*) FROM question_used").fetchone()[0] == 0


def test_a_renamed_category_keeps_its_questions_but_not_its_meaning(tmp_path):
    """Its questions come along as candidates; its areas don't, since the
    new name may mean something else (Mythology renamed Ancient History
    kept asking about Bigfoot). They're worked out again from its new
    scope, and the bank is sorted to it (pipeline.facts.scope)."""
    import json
    conn = store.connect(tmp_path / "f.db")
    _stock(conn, 4, "Flags & Countries")
    with conn:
        conn.execute("INSERT INTO bank_areas (category, areas) VALUES ('Flags & Countries', ?)", (json.dumps(["A"]),))
    bank.rename_category(conn, "Flags & Countries", "Flags")
    assert len(bank.pool(conn, "pub", "Flags")) == 4 and not bank.pool(conn, "pub", "Flags & Countries")
    assert bank._stored_areas(conn, "Flags") == [] and bank._stored_areas(conn, "Flags & Countries") == []


def test_a_question_that_says_its_answer_is_refused():
    """Regression: "Which continent appears at the centre of the flag of the
    African Union?" (Africa) went out in a Tricky round."""
    assert bank.gives_away("Which continent appears at the centre of the flag of the African Union?", "Africa")
    assert bank.gives_away("In which country is the famous Monaco Grand Prix held?", "Monaco")
    assert bank.gives_away("Which Czech city gave its name to the lager style Pilsner?", "Pilsen")
    # Sharing only a generic word, a number's unit, or part of a longer answer is fine.
    assert not bank.gives_away("Which ocean is the largest on Earth?", "The Pacific Ocean")
    assert not bank.gives_away("Roughly how many miles long is a marathon race?", "26.2 miles")
    assert not bank.gives_away("In which battle of 1346 did the longbow prove decisive?", "Battle of Crécy")
    assert not bank.gives_away("What was the title of the first Harry Potter book?",
                               "Harry Potter and the Philosopher's Stone")


def test_a_batch_for_the_easiest_rounds_is_given_the_raters_yardstick(tmp_path, monkeypatch):
    """Written for Easy, questions came back rated hard, and the easy
    levels of every category stayed empty."""
    import pipeline.llm as llm
    from pipeline import quiz
    conn = store.connect(tmp_path / "f.db")
    monkeypatch.setattr(bank, "areas", lambda conn, category: ["Planets"])
    asked = []
    monkeypatch.setattr(llm, "call_json", lambda system, user, *a, **k: asked.append(user) or {"questions": []})
    monkeypatch.setattr(quiz, "verify", lambda *a, **k: [])
    bank.write_batch(conn, "Space", 1.5, ["Space"])
    bank.write_batch(conn, "Space", 6, ["Space"])
    assert "four in five British adults" in asked[0] and "four in five" not in asked[1]


def test_an_easy_batch_is_shown_how_its_own_category_was_judged(tmp_path, monkeypatch):
    """The general yardstick wasn't enough: Ancient History's "obvious"
    questions (Julius Caesar, 75%) were still too hard for Easy."""
    import pipeline.llm as llm
    from pipeline import quiz
    conn = store.connect(tmp_path / "f.db")
    for question, answer, level, pct in (("Which civilisation built the Colosseum?", "The Romans", 2, 85),
                                         ("Who was assassinated in 44 BC?", "Julius Caesar", 3, 75)):
        qid = bank.add(conn, _q(question, answer, level=level), "Ancient History", "Rome", "ok", "ok", "written")
        conn.execute("UPDATE questions SET known_pct = ? WHERE id = ?", (pct, qid))
    monkeypatch.setattr(bank, "areas", lambda conn, category: ["Rome"])
    asked = []
    monkeypatch.setattr(llm, "call_json", lambda system, user, *a, **k: asked.append((user, k)) or {"questions": []})
    monkeypatch.setattr(quiz, "verify", lambda *a, **k: [])

    bank.write_batch(conn, "Ancient History", 1.5, ["Ancient History"])
    bank.write_batch(conn, "Ancient History", 6, ["Ancient History"])

    easy, hard = asked[0][0], asked[1][0]
    assert "Easy enough" in easy and "The Romans): 85%" in easy
    assert "too hard" in easy and "Julius Caesar): 75%" in easy
    assert "Easy enough" not in hard
    assert asked[0][1]["effort"] == "low"


def _short_channel(monkeypatch):
    channel = ChannelConfig(key="pub", format="quiz")
    channel.quiz.difficulties = ["Easy"]
    monkeypatch.setattr(keep, "quiz_categories", lambda channel: ["Ancient History"])
    monkeypatch.setattr(bank, "spent_today", lambda: 0.0)
    monkeypatch.setattr(keep, "BANK_BATCHES", 1)
    return channel


def test_a_slot_that_writing_doesnt_fill_is_rested(monkeypatch, tmp_path):
    """Ancient History near Easy was written for 16 times in a few days,
    each batch giving a question or two easy enough."""
    conn = store.connect(tmp_path / "f.db")
    channel = _short_channel(monkeypatch)
    written = []
    monkeypatch.setattr(bank, "write_batch", lambda conn, name, level, names: written.append(level) or
                        {"kept": 20, "levels": [1.0] + [5.0] * 19})
    said = []
    for _ in range(keep.REST_AFTER + 1):
        keep.stock_bank(conn, channel, say=said.append)

    assert len(written) == keep.REST_AFTER
    assert any("resting it until" in m for m in said)


def test_a_slot_that_writing_does_fill_is_never_rested(monkeypatch, tmp_path):
    conn = store.connect(tmp_path / "f.db")
    channel = _short_channel(monkeypatch)
    written = []
    monkeypatch.setattr(bank, "write_batch", lambda conn, name, level, names: written.append(level) or
                        {"kept": 20, "levels": [1.0] * 3 + [5.0] * 17})
    for _ in range(keep.REST_AFTER + 2):
        keep.stock_bank(conn, channel)
    assert len(written) == keep.REST_AFTER + 2


def test_a_rested_slot_is_tried_again_after_its_rest(monkeypatch, tmp_path):
    conn = store.connect(tmp_path / "f.db")
    for _ in range(keep.REST_AFTER):
        keep._record_write(conn, "Ancient History", 1.5, [5.0])
    assert keep.resting_until(conn, "Ancient History", 1.5)
    assert keep.resting_until(conn, "Ancient History", 3.0) is None        # another slot
    conn.execute("UPDATE bank_writes SET at = at - ?", (keep.REST_DAYS * 86400 + 1,))
    assert keep.resting_until(conn, "Ancient History", 1.5) is None
