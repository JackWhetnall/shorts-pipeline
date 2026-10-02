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
    """Rewrites by prefixing "Name", fails the check on anything about
    dwarf planets, rates everything 92% known, files everything under Space."""
    import pipeline.llm as llm
    from pipeline import quiz
    from pipeline.facts import rate, scope
    calls = []

    def call_json(system, user, schema, **kw):
        calls.append(kw.get("operation"))
        if kw.get("operation") == "intake_rewrite":
            results = []
            for line in user.splitlines():
                number, rest = line.split(". ", 1)
                question, answer = rest.split(" Answer: ")
                answer = answer.split(" (set with")[0]
                results.append({"number": int(number), "keep": "which of these" not in question.lower(),
                                "question": f"Name the {question.rstrip('?').lower()}?", "answer": answer,
                                "alternatives": [], "note": "", "shape": "name", "area": "Planets"})
            return {"results": results}
        raise AssertionError(kw.get("operation"))
    monkeypatch.setattr(llm, "call_json", call_json)
    monkeypatch.setattr(quiz, "verify", lambda c, d, qs, operation="", effort="": [
        "wrong" if "dwarf" in q["question"].lower() else "ok" for q in qs])
    monkeypatch.setattr(rate, "rate", lambda qs, operation="": [(92.0, True)] * len(qs))
    filed = []
    monkeypatch.setattr(scope, "file_new", lambda conn, ids, names, say=None: filed.extend(ids) or {})
    return calls, filed


def test_the_same_raw_question_is_held_once(conn):
    assert intake.add_raw(conn, "opentdb", [_raw("What is the largest planet?", "Jupiter")]) == 1
    assert intake.add_raw(conn, "opentdb", [_raw("What is the largest planet?", "Jupiter")]) == 0
    assert intake.pending(conn) == 1


def test_processing_drops_repeats_and_misfits_and_keeps_the_rest_rewritten_and_rated(conn, model):
    calls, filed = model
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
    assert mars["area"] == "Planets" and filed == [mars["id"]]
    assert "Imported 1 questions" in result and intake.pending(conn) == 0


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
