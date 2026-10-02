"""
What each quiz category covers, and the bank kept to it
(pipeline.facts.scope, decision 060). The owner renamed Mythology to
Ancient History and got Bigfoot, the Bible and Native American legends:
the questions and areas came across with the name. The model is faked.

- a category's scope steers its areas and every batch written for it;
- sorting files each question under the categories it fits, and leaves
  other channels' categories alone;
- a rename or an edited scope means the bank is sorted again before the
  next round;
- the page shows and edits the scopes.
"""

from __future__ import annotations

import pytest

from pipeline.facts import bank, scope, store


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "facts.db")
    return store.connect()


def _q(conn, question, answer, category, area="Misc"):
    return bank.add(conn, {"question": question, "answer": answer, "level": 4, "shape": "name"},
                    category, area, "ok", "ok", "written")


def _tags(conn, qid):
    return sorted(r[0] for r in conn.execute("SELECT category FROM question_tags WHERE question_id = ?", (qid,)))


@pytest.fixture
def fake_model(monkeypatch):
    """Scopes from a table; sorting by keyword, as a model reading them would."""
    import pipeline.llm as llm
    calls = []
    scopes = {"Ancient History": ("Ancient Greece, Rome and Egypt.", "Other myths go to Mythology."),
              "Modern History": ("From the fall of Rome to the Second World War.", "Not the ancient world."),
              "Mythology": ("Myths of every culture.", "")}

    def call_json(system, user, schema, **kw):
        calls.append((kw.get("operation"), user))
        if kw.get("operation") == "category_scope":
            name = user.split("\n")[0].split(": ", 1)[1]
            covers, excludes = scopes.get(name, (f"All about {name}.", ""))
            return {"covers": covers, "excludes": excludes}
        if kw.get("operation") in ("category_sort", "category_audit"):
            results = []
            for line in user.split("The questions:\n", 1)[1].splitlines():
                number, text = line.split(". ", 1)
                found = _fits(text)
                if kw["operation"] == "category_sort":
                    results.append({"number": int(number), "categories": found})
                else:
                    round_name = user.split("The round: ", 1)[1].split("\n", 1)[0]
                    results.append({"number": int(number), "belongs": round_name in found})
            return {"results": results}
        raise AssertionError(kw.get("operation"))
    monkeypatch.setattr(llm, "call_json", call_json)
    return calls


CATEGORIES = ["Ancient History", "Modern History", "Mythology"]


def _fits(text: str) -> list:
    found = []
    if any(w in text for w in ("Zeus", "Caesar", "pharaoh")):
        found.append("Ancient History")
    if any(w in text for w in ("Zeus", "Coyote", "Thor")):
        found.append("Mythology")
    if "Waterloo" in text:
        found.append("Modern History")
    return found


def test_sorting_files_each_question_where_its_scope_says(conn, fake_model):
    coyote = _q(conn, "What did Coyote steal in Native American legend?", "Fire", "Ancient History")
    zeus = _q(conn, "Who was king of the Greek gods?", "Zeus", "Ancient History")
    caesar = _q(conn, "Who crossed the Rubicon? Caesar", "Julius Caesar", "Modern History")
    waterloo = _q(conn, "In which battle was Napoleon finally beaten? Waterloo", "Waterloo", "Modern History")
    result = scope.sort(conn, CATEGORIES)
    assert _tags(conn, coyote) == ["Mythology"]
    assert _tags(conn, zeus) == ["Ancient History", "Mythology"]
    assert _tags(conn, caesar) == ["Ancient History"]
    assert _tags(conn, waterloo) == ["Modern History"]
    assert result == {"checked": 4, "removed": 2, "added": 3}
    assert scope.unsorted(conn, CATEGORIES) == []


def test_other_channels_categories_are_left_alone(conn, fake_model):
    qid = _q(conn, "What did Coyote steal?", "Fire", "Ancient History")
    conn.execute("INSERT INTO question_tags (question_id, category) VALUES (?, 'Folklore')", (qid,))
    conn.commit()
    scope.sort(conn, CATEGORIES)
    assert _tags(conn, qid) == ["Folklore", "Mythology"]


def test_a_question_the_model_skipped_is_left_as_it_was(conn, fake_model, monkeypatch):
    import pipeline.llm as llm
    qid = _q(conn, "Who was king of the Greek gods?", "Zeus", "Ancient History")
    for name in CATEGORIES:
        scope.save(conn, name, f"All about {name}.", "", edited=False)
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"results": []})
    scope.sort(conn, CATEGORIES)
    assert _tags(conn, qid) == ["Ancient History"]


def test_a_rename_means_a_new_scope_and_a_new_sort(conn, fake_model):
    scope.sort(conn, CATEGORIES)
    assert scope.unsorted(conn, CATEGORIES) == []
    bank.rename_category(conn, "Mythology", "Ancient History")
    assert scope.get(conn, "Ancient History") is None and scope.get(conn, "Mythology") is None
    assert "Ancient History" in scope.unsorted(conn, CATEGORIES)


def test_an_edited_scope_is_kept_and_sorted_again(conn, fake_model):
    scope.sort(conn, CATEGORIES)
    conn.execute("INSERT OR REPLACE INTO bank_areas (category, areas) VALUES ('Ancient History', '[\"Old\"]')")
    conn.commit()
    saved = scope.save(conn, "Ancient History", "Greece and Rome only.", "Egypt is History.")
    assert saved["edited"] == 1 and not saved["sorted_at"]
    assert scope.unsorted(conn, CATEGORIES) == ["Ancient History"]
    assert bank._stored_areas(conn, "Ancient History") == []          # worked out again from it
    with pytest.raises(ValueError):
        scope.save(conn, "Ancient History", "  ", "")


def test_the_scope_steers_areas_and_batches(conn, fake_model, monkeypatch):
    from pipeline import quiz
    import pipeline.llm as llm
    seen = []
    real = llm.call_json

    def spy(system, user, schema, **kw):
        if kw.get("operation") in ("bank_areas", "bank_write"):
            seen.append(user)
            return {"areas": ["Greek gods"]} if kw["operation"] == "bank_areas" else {"questions": []}
        return real(system, user, schema, **kw)
    monkeypatch.setattr(llm, "call_json", spy)
    monkeypatch.setattr(quiz, "verify", lambda *a, **k: [])
    bank.write_batch(conn, "Ancient History", 4, CATEGORIES)
    assert all("Ancient Greece, Rome and Egypt." in text for text in seen) and len(seen) == 2


def test_a_round_sorts_the_bank_first(conn, monkeypatch):
    from core.channels import ChannelConfig
    from pipeline import quiz
    from pipeline.facts import keep
    sorted_for = []
    monkeypatch.setattr(scope, "sort_if_needed", lambda c, names, say=None: sorted_for.append(names))
    monkeypatch.setattr(keep, "quiz_categories", lambda channel: CATEGORIES)
    channel = ChannelConfig(key="buzz", format="quiz")
    quiz._bank_questions(channel, "Ancient History", "Easy", 3)
    assert sorted_for == [CATEGORIES]


def test_the_categories_page_shows_and_saves_scopes(conn, fake_model, monkeypatch):
    from core.channels import ChannelConfig
    from pipeline.facts import keep
    from web import create_app
    import web.blueprints.curriculum as page
    channel = ChannelConfig(key="buzz", format="quiz")
    monkeypatch.setattr(page, "channel_or_404", lambda key: channel)
    monkeypatch.setattr(keep, "quiz_categories", lambda c: CATEGORIES + ["General Knowledge"])
    monkeypatch.setattr(scope, "sort_in_background", lambda names: None)
    scope.save(conn, "Modern History", "From the fall of Rome to 1945.", "", edited=False)
    client = create_app().test_client()
    html = client.get("/channels/buzz/curriculum/categories").get_data(as_text=True)
    assert "From the fall of Rome to 1945." in html and "Not written yet" in html and "Anything at all" in html
    client.get("/m/sign-in")
    with client.session_transaction() as s:
        token = s["_csrf_token"]
    client.post("/channels/buzz/curriculum/categories/save",
                data={"csrf_token": token, "category": "Ancient History", "covers": "Greece and Rome.",
                      "excludes": "Egypt."})
    assert scope.get(conn, "Ancient History")["covers"] == "Greece and Rome."
    client.post("/channels/buzz/curriculum/categories/save",
                data={"csrf_token": token, "category": "Mythology", "action": "write"})
    assert scope.get(conn, "Mythology")["covers"] == "Myths of every culture."
    assert client.post("/channels/buzz/curriculum/categories/save",
                       data={"csrf_token": token, "category": "Nonsense"}).status_code == 404


def test_questions_a_batch_answer_left_out_are_asked_again(conn, fake_model, monkeypatch):
    """Seven Native American legends in a row stayed in Ancient History
    because the answer for their batch stopped short of them."""
    import pipeline.llm as llm
    real = llm.call_json
    first = {"done": False}

    def short_first(system, user, schema, **kw):
        result = real(system, user, schema, **kw)
        if kw.get("operation") == "category_sort" and not first["done"]:
            first["done"] = True
            result = {"results": result["results"][:1]}          # stops after the first
        return result
    monkeypatch.setattr(llm, "call_json", short_first)
    ids = [_q(conn, f"What did Coyote steal, version {n}?", "Fire", "Ancient History") for n in range(3)]
    scope.sort(conn, CATEGORIES)
    assert all(_tags(conn, qid) == ["Mythology"] for qid in ids)



def test_the_check_takes_out_what_the_sort_let_through(conn, fake_model, monkeypatch):
    """Sorting into a dozen categories at once left the Bible in Ancient
    History; judged against that one definition, it goes."""
    import pipeline.llm as llm
    real = llm.call_json

    def lenient_sort(system, user, schema, **kw):
        result = real(system, user, schema, **kw)
        if kw.get("operation") == "category_sort":
            for r in result["results"]:
                r["categories"] = sorted(set(r["categories"]) | {"Ancient History"})
        return result
    monkeypatch.setattr(llm, "call_json", lenient_sort)
    bible = _q(conn, "On which day did God rest?", "The seventh", "Ancient History")
    zeus = _q(conn, "Who was king of the Greek gods?", "Zeus", "Ancient History")
    scope.sort(conn, CATEGORIES)
    assert _tags(conn, bible) == [] and _tags(conn, zeus) == ["Ancient History", "Mythology"]


def test_a_question_goes_only_if_both_checks_say_it_doesnt_belong(conn, fake_model, monkeypatch):
    """Taken out on either "no", Edwin Hubble left Space."""
    import pipeline.llm as llm
    monkeypatch.setattr(scope, "AUDIT_PASSES", 2)
    scope.save(conn, "Space", "Astronomy and spaceflight.", "", edited=False)
    hubble = _q(conn, "Who proved other galaxies exist beyond the Milky Way?", "Edwin Hubble", "Space")
    answers = iter([False, True])
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"results": [{"number": 1, "belongs": next(answers)}]})
    assert scope.audit(conn, "Space") == 0 and _tags(conn, hubble) == ["Space"]
    answers = iter([False, False])
    assert scope.audit(conn, "Space") == 1 and _tags(conn, hubble) == []



def test_a_written_round_asking_outside_its_category_is_found(conn, fake_model):
    coyote = _q(conn, "What did Coyote steal?", "Fire", "Ancient History")
    zeus = _q(conn, "Who was king of the Greek gods?", "Zeus", "Ancient History")
    scope.sort(conn, CATEGORIES)
    round_ = {"category": "Ancient History", "questions": [
        {"question": "What did Coyote steal?", "bank_id": coyote},
        {"question": "Who was king of the Greek gods?", "bank_id": zeus},
        {"question": "Written with the round", "answer": "x"}]}
    assert scope.outside(conn, round_) == ["What did Coyote steal?"]
    assert scope.outside(conn, {**round_, "category": "General Knowledge"}) == []
