"""
Questions from elsewhere (pipeline.facts.intake, sources; decision 061).
The model and the network are faked.

- raw questions are held once, and processed a batch at a time within a
  budget, resuming where a run stopped;
- what the bank has already is dropped; what doesn't suit a pub quiz read
  aloud is dropped; what fails the fact check is kept as rejected; the
  rest go in rewritten, rated and filed;
- Open Trivia DB: kept categories only, its HTML entities undone, and its
  credit on any round that uses one of its questions;
- websites: robots.txt obeyed, only quiz-looking pages on the same site,
  and the site's pace.
"""

from __future__ import annotations

import json

import pytest

from pipeline.facts import bank, intake, store


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "facts.db")
    return store.connect()


def _raw(question, answer, wrong=()):
    return {"question": question, "answer": answer, "wrong": list(wrong), "difficulty": "easy",
            "category": "General Knowledge"}


@pytest.fixture
def model(monkeypatch):
    """One call per batch: rewrites by prefixing "Name", unsure about
    anything about dwarf planets, rates everything 92% known, files
    everything mentioning a planet under Space. `close` keeps a question's
    wording instead, for the website test."""
    import pipeline.llm as llm
    from pipeline.facts import scope
    calls = []
    monkeypatch.setattr(scope, "ensure", lambda conn, name, names: {"covers": f"All about {name}.", "excludes": ""})
    state = {"close": False}

    def call_json(system, user, schema, **kw):
        calls.append(kw.get("operation"))
        assert kw.get("operation") == "intake_process"
        results = []
        for line in user.split("The questions:\n", 1)[1].splitlines():
            number, rest = line.split(". ", 1)
            question, answer = rest.split(" Answer: ")
            answer = answer.split(" (set with")[0]
            ours = question if state["close"] else f"Name the {question.rstrip('?').lower()}?"
            results.append({"number": int(number), "keep": "which of these" not in question.lower(),
                            "question": ours, "answer": answer, "alternatives": [], "note": "", "shape": "name",
                            "area": "Planets", "correct": "dwarf" not in question.lower(), "percent": 92,
                            "kid": True, "categories": ["Space"] if "planet" in question.lower() else []})
        return {"results": results}
    monkeypatch.setattr(llm, "call_json", call_json)
    return calls, state


def test_the_same_raw_question_is_held_once(conn):
    assert intake.add_raw(conn, "opentdb", [_raw("What is the largest planet?", "Jupiter")]) == 1
    assert intake.add_raw(conn, "opentdb", [_raw("What is the largest planet?", "Jupiter")]) == 0
    assert intake.pending(conn) == 1


def test_processing_drops_repeats_and_misfits_and_keeps_the_rest_rewritten_and_rated(conn, model):
    calls, _ = model
    bank.add(conn, {"question": "Which planet is the largest in the Solar System?", "answer": "Jupiter",
                    "level": 3}, "Space", "Planets", "ok", "ok", "written")
    intake.add_raw(conn, "opentdb", [
        _raw("Which planet is the largest in the Solar System?", "Jupiter"),       # the bank has it
        _raw("Which of these is a gas giant?", "Saturn", ["Mars", "Venus"]),      # needs its options
        _raw("Which dwarf planet was demoted in 2006?", "Pluto"),                 # fails the check
        _raw("What planet is called the Red Planet?", "Mars")], origin="https://opentdb.com")
    result = intake.process(conn, ["Space"], budget_usd=5, say=None)
    status = dict(conn.execute("SELECT json_extract(raw, '$.answer'), status FROM intake").fetchall())
    assert status == {"Jupiter": "duplicate", "Saturn": "skipped", "Pluto": "rejected", "Mars": "added"}
    mars = conn.execute("SELECT * FROM questions WHERE answer = 'Mars'").fetchone()
    assert mars["question"].startswith("Name the")                            # the rewrite, not the original
    assert mars["source"] == "opentdb" and mars["origin"] == "https://opentdb.com" and mars["level"] == 1.0
    assert mars["area"] == "Planets"
    assert [r[0] for r in conn.execute("SELECT category FROM question_tags WHERE question_id = ?", (mars["id"],))] \
        == ["Space"]
    assert "Imported 1 questions" in result and intake.pending(conn) == 0
    assert calls == ["intake_process"]                     # one call did it all


def test_a_websites_wording_is_never_kept(conn, model):
    _, state = model
    state["close"] = True
    intake.add_raw(conn, "web:quiz.example", [_raw("What planet is called the Red Planet?", "Mars")],
                   origin="https://quiz.example/1")
    intake.add_raw(conn, "opentdb", [_raw("What is the largest planet?", "Jupiter")])
    intake.process(conn, ["Space"], budget_usd=5)
    status = dict(conn.execute("SELECT source, status FROM intake").fetchall())
    # Open Trivia DB's licence allows adapting it closely; a website's doesn't.
    assert status == {"web:quiz.example": "skipped", "opentdb": "added"}


def test_a_rewrite_that_still_leans_on_options_is_dropped(conn, model, monkeypatch):
    import pipeline.llm as llm
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"results": [{
        "number": 1, "keep": True, "question": "Which soft drink was introduced before the others?",
        "answer": "Dr Pepper", "alternatives": [], "note": "", "shape": "first", "area": "Soft drinks",
        "correct": True, "percent": 15, "kid": False, "categories": []}]})
    intake.add_raw(conn, "opentdb", [_raw("Which of these soft drinks came first?", "Dr Pepper", ["Coca-Cola"])])
    intake.process(conn, ["Space"], budget_usd=5)
    assert conn.execute("SELECT status FROM intake").fetchone()[0] == "skipped"


def test_processing_stops_at_its_budget_and_carries_on_next_time(conn, model, monkeypatch):
    intake.add_raw(conn, "opentdb", [_raw(f"What is moon number {n}?", f"Moon{n}x") for n in range(60)])
    spent = iter([0.0, 5.0, 5.0])
    monkeypatch.setattr(intake, "spent_since", lambda since: next(spent))
    intake.process(conn, ["Space"], budget_usd=1)
    assert intake.pending(conn) == 60 - intake.BATCH


def test_opentdb_keeps_pub_quiz_categories_and_undoes_its_entities(monkeypatch):
    from pipeline.facts.sources import opentdb

    class Response:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data
    calls = []

    def get(url, params=None, timeout=0):
        calls.append((url, dict(params or {})))
        if url == opentdb.TOKEN_API:
            return Response({"token": "T"})
        if url == opentdb.CATEGORIES_API:
            return Response({"trivia_categories": [{"id": 9, "name": "General Knowledge"},
                                                   {"id": 15, "name": "Entertainment: Video Games"}]})
        asked = [p for u, p in calls if u == opentdb.API]
        if len(asked) == 1:
            return Response({"response_code": 0, "results": [{
                "question": "Which country&#039;s flag has a maple leaf?", "correct_answer": "Canada",
                "incorrect_answers": ["France"], "difficulty": "easy", "category": "General Knowledge"}]})
        # Fewer than 50 left: the API says "token spent" for 50, yet gives a smaller amount.
        if params.get("amount") == 25 and not any(p.get("amount") == 25 for p in asked[:-1]):
            return Response({"response_code": 0, "results": [{
                "question": "What is the capital of Peru?", "correct_answer": "Lima", "incorrect_answers": [],
                "difficulty": "easy", "category": "General Knowledge"}]})
        return Response({"response_code": 4, "results": []})
    monkeypatch.setattr(opentdb.requests, "get", get)
    items = opentdb.fetch(sleep=lambda s: None)
    assert items[0] == {"question": "Which country's flag has a maple leaf?", "answer": "Canada",
                        "wrong": ["France"], "difficulty": "easy", "category": "General Knowledge"}
    assert [i["answer"] for i in items] == ["Canada", "Lima"]           # the last few taken too
    assert all(p.get("category") != 15 for u, p in calls if u == opentdb.API)


def test_a_round_using_an_opentdb_question_credits_it(monkeypatch):
    from core.channels import ChannelConfig
    from pipeline import quiz
    from pipeline.facts.sources import opentdb
    import pipeline.llm as llm
    channel = ChannelConfig(key="buzz", format="quiz", style_prompt="x")
    channel.quiz.questions = 2
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"hook": "", "intro": "Hi.", "outro": "Bye.",
                                                          "title_options": ["T"], "description_body": "",
                                                          "questions": []})
    monkeypatch.setattr(quiz, "call_json", llm.call_json, raising=False)
    monkeypatch.setattr("pipeline.facts.bank.mark_used", lambda *a, **k: None)
    script = quiz._round_from_bank(channel, "Space", "Easy", [
        {"question": "Q1?", "answer": "A1", "note": "", "bank_id": 1, "source": "opentdb"},
        {"question": "Q2?", "answer": "A2", "note": "", "bank_id": 2, "source": "written"}])
    assert opentdb.CREDIT in script.quiz["credits"]


class _Page:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        pass


def test_websites_are_read_only_where_robots_allows_and_only_quiz_pages(monkeypatch):
    from pipeline.facts.sources import web
    pages = {
        "https://quiz.example/robots.txt": "User-agent: *\nDisallow: /private\nCrawl-delay: 7",
        "https://quiz.example/pub-quiz/": '<p>What is the capital of France? Paris</p>'
                                          '<a href="/pub-quiz-2/">more</a><a href="/about/">about</a>'
                                          '<a href="https://other.example/quiz/">elsewhere</a>'
                                          '<a href="/private/quiz-answers/">secret</a>',
        "https://quiz.example/pub-quiz-2/": "<p>How many legs has a spider? Eight</p>",
        "https://no.example/robots.txt": "User-agent: *\nDisallow: /",
    }
    monkeypatch.setattr(web.requests, "get", lambda url, timeout=0, headers=None: _Page(pages.get(url, ""), 200))
    waits = []
    read = list(web.crawl(["https://quiz.example/pub-quiz/", "https://no.example/quiz/"], set(),
                          sleep=lambda s: waits.append(s)))
    assert [url for url, _ in read] == ["https://quiz.example/pub-quiz/", "https://quiz.example/pub-quiz-2/"]
    assert "capital of France" in read[0][1]
    assert waits and all(w <= 7.0 for w in waits) and max(waits) > 6.0     # the site's own delay



def test_two_runs_never_work_on_the_same_questions(conn):
    """The app's hourly run and a run by hand once processed the same rows
    side by side, paying twice."""
    intake.add_raw(conn, "opentdb", [_raw(f"What is moon number {n}?", f"Moon{n}x") for n in range(30)])
    first, second = intake._claim(conn), intake._claim(conn)
    assert len(first) == intake.BATCH and len(second) == 30 - intake.BATCH
    assert not {r["id"] for r in first} & {r["id"] for r in second}
    assert intake._claim(conn) == [] and intake.pending(conn) == 30
