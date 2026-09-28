"""
The fact store (pipeline.facts, decision 049). Wikidata, QLever and the
model are faked: what's tested is what's made of their answers.

- statements become facts only when usable: known values, English
  labels, dates stated to the year, one value for a forward question;
- a category tags its members, and an entity already in the store counts
  for a new category without being fetched again;
- levels are ranks within a category, and a round draws unused facts near
  its level, one per subject and answer;
- a fact is used once per channel whichever category it came through,
  and one stated both ways is one fact;
- a round is built on facts, each question's answer checked against its
  fact, and written without them when the store is short.
"""

from __future__ import annotations

import pytest

from pipeline.facts import categories, harvest, levels, pick, store, wikidata

E = "http://www.wikidata.org/entity/"
WDT = "http://www.wikidata.org/prop/direct/"


def _item_row(s, p, o, label, sl=50, desc=""):
    return {"s": E + s, "p": WDT + p, "o": E + o, "o_type": "uri", "oLabel": label,
            "oDescription": desc, "osl": str(sl)}


def _literal_row(s, p, value):
    return {"s": E + s, "p": WDT + p, "o": value, "o_type": "literal"}


class TestParsing:
    def test_only_usable_statements_become_facts(self):
        rows = [_item_row("Q142", "P36", "Q90", "Paris", 366),
                {"s": E + "Q897", "p": WDT + "P61", "o": "http://www.wikidata.org/.well-known/genid/x",
                 "o_type": "uri", "oLabel": "genid"},                       # "unknown value"
                _item_row("Q142", "P38", "Q4916", "Q4916"),                  # no English label
                _literal_row("Q897", "P246", "Au"),
                _literal_row("Q897", "P1086", "79.0"),
                _item_row("Q142", "P999", "Q1", "not a quiz property")]
        facts = harvest.parse_items(rows)
        assert [(f[1], f[3]) for f in facts] == [("P36", "Paris"), ("P246", "Au"), ("P1086", "79")]

    def test_dates_only_to_the_year_and_bc_said_so(self):
        rows = [{"s": E + "Q142", "prop": E + "P571", "t": "0900-01-01T00:00:00Z", "prec": "7"},
                {"s": E + "Q142", "prop": E + "P571", "t": "1792-01-01T00:00:00Z", "prec": "9"},
                {"s": E + "Q1", "prop": E + "P585", "t": "-0490-01-01T00:00:00Z", "prec": "9"}]
        assert [f[3] for f in harvest.parse_years(rows)] == ["1792", "490 BC"]


class FakeWikidata:
    """Answers the harvester's three query shapes from a small world."""

    def __init__(self):
        self.members = {}          # a class or anchor QID -> [(qid, label, sitelinks)]
        self.items = {}            # subject QID -> item/literal rows
        self.years = {}            # subject QID -> year rows
        self.fact_queries = 0

    def sparql(self, query, engine="wikidata"):
        if "wikibase:sitelinks ?sl" in query and "ORDER BY" in query:
            key = next(k for k in self.members if f"wd:{k}" in query)
            return [{"s": E + q, "sLabel": label, "sDescription": "", "sl": str(sl)}
                    for q, label, sl in self.members[key]]
        subjects = [q for q in set(self.items) | set(self.years) if f"wd:{q} " in query + " "]
        self.fact_queries += 1
        if "timePrecision" in query:
            return [r for q in subjects for r in self.years.get(q, [])]
        return [r for q in subjects for r in self.items.get(q, [])]


@pytest.fixture
def world(monkeypatch, tmp_path):
    fake = FakeWikidata()
    monkeypatch.setattr(wikidata, "sparql", fake.sparql)
    # Every entity has an English article read 100,000 times a year.
    monkeypatch.setattr(wikidata, "enwiki_titles", lambda qids: {q: f"Title {q}" for q in qids})
    monkeypatch.setattr(wikidata, "yearly_views", lambda titles: {q: 100_000 for q in titles})
    conn = store.connect(tmp_path / "facts.db")
    return fake, conn


def _countries(fake):
    fake.members["Q6256"] = [("Q142", "France", 420), ("Q750", "Bolivia", 300), ("Q34", "Sweden", 380)]
    fake.items = {
        "Q142": [_item_row("Q142", "P36", "Q90", "Paris", 366), _item_row("Q142", "P37", "Q150", "French", 352)],
        "Q750": [_item_row("Q750", "P36", "Q1491", "La Paz", 158), _item_row("Q750", "P36", "Q2907", "Sucre", 152)],
        "Q34": [_item_row("Q34", "P36", "Q1754", "Stockholm", 279)],
    }


class TestHarvest:
    def test_a_category_tags_its_members_and_stores_their_facts(self, world):
        fake, conn = world
        _countries(fake)
        store.save_category(conn, "Geography", {"sets": [{"name": "countries", "kind": "class",
                                                            "classes": ["Q6256"], "size": "small"}]})
        result = harvest.harvest(conn, "Geography")
        assert result["members"] == 3 and result["fetched"] == 3
        rows = {(r["subject"], r["value_label"]): r for r in store.category_facts(conn, "Geography")}
        assert rows[("Q142", "Paris")]["values_for_subject"] == 1
        # Bolivia has two capitals: neither can be asked forwards.
        assert rows[("Q750", "La Paz")]["values_for_subject"] == 2

    def test_a_new_category_counts_facts_already_there_without_fetching_them(self, world):
        fake, conn = world
        _countries(fake)
        store.save_category(conn, "Geography", {"sets": [{"name": "countries", "kind": "class",
                                                            "classes": ["Q6256"]}]})
        harvest.harvest(conn, "Geography")
        before = fake.fact_queries
        fake.members["Q999"] = [("Q142", "France", 420)]
        store.save_category(conn, "Europe", {"sets": [{"name": "European countries", "kind": "class",
                                                         "classes": ["Q999"]}]})
        result = harvest.harvest(conn, "Europe")
        assert result["fetched"] == 0 and fake.fact_queries == before
        assert {r["value_label"] for r in store.category_facts(conn, "Europe")} == {"Paris", "French"}

    def test_a_set_goes_deeper_each_time_it_grows(self, world):
        fake, conn = world
        _countries(fake)
        spec = {"sets": [{"name": "countries", "kind": "class", "classes": ["Q6256"]}]}
        store.save_category(conn, "Geography", spec)
        harvest.harvest(conn, "Geography")
        assert store.category(conn, "Geography")["spec"]["sets"][0]["fetched"] == 3
        seen = []
        original = harvest.members
        harvest.members = lambda s, offset, limit: seen.append(offset) or []
        try:
            harvest.harvest(conn, "Geography")                 # already harvested: nothing to do
            harvest.harvest(conn, "Geography", grow=True)
        finally:
            harvest.members = original
        assert seen == [3]


def test_a_set_that_finds_nothing_is_skipped_for_good(world):
    fake, conn = world
    fake.members["Q404"] = []
    store.save_category(conn, "Odd", {"sets": [{"name": "nothing", "kind": "class", "classes": ["Q404"]}]})
    harvest.harvest(conn, "Odd")
    assert store.category(conn, "Odd")["spec"]["sets"][0]["method"] == "skipped"


class TestMembersLookup:
    def test_qlevers_answer_is_used_only_if_it_looks_right(self, monkeypatch):
        calls = []

        def sparql(query, engine="wikidata"):
            calls.append(engine)
            if engine == "qlever":           # unsorted, obscure first: seen under load
                return [{"s": E + "Q1", "sLabel": "A", "sl": "10"}, {"s": E + "Q2", "sLabel": "B", "sl": "90"}]
            return [{"s": E + "Q3", "sLabel": "Titanic", "sl": "137"}]
        monkeypatch.setattr(wikidata, "sparql", sparql)
        spec = {"name": "films", "kind": "class", "classes": ["Q11424"]}
        assert [r[1] for r in harvest.members(spec, 0, 10)] == ["Titanic"]
        assert calls == ["qlever", "wikidata"] and spec["method"] == "one level"
        calls.clear()
        harvest.members(spec, 10, 10)                 # the next page goes straight there
        assert calls == ["wikidata"]

    def test_qlevers_rows_below_the_fame_floor_are_dropped(self, monkeypatch):
        """QLever answers nothing with the fame filter in, so it's applied after."""
        def sparql(query, engine="wikidata"):
            assert "FILTER(?sl" not in query and "P31/wdt:P279*" not in query
            return [{"s": E + "Q2", "sLabel": "Earth", "sl": "368"}, {"s": E + "Q9", "sLabel": "Obscure", "sl": "3"}]
        monkeypatch.setattr(wikidata, "sparql", sparql)
        spec = {"name": "planets", "kind": "class", "classes": ["Q634"]}
        assert [r[1] for r in harvest.members(spec, 0, 10)] == ["Earth"] and spec["method"] == "ranked"

    def test_a_class_too_big_for_every_way_is_skipped_for_good(self, monkeypatch):
        def sparql(query, engine="wikidata"):
            raise wikidata.QueryTimeout("Wikidata", "slow", user_message="")
        monkeypatch.setattr(wikidata, "sparql", sparql)
        spec = {"name": "stars", "kind": "class", "classes": ["Q523"]}
        assert harvest.members(spec, 0, 10) == [] and spec["method"] == "skipped"


def _read(conn, views: dict) -> None:
    """How many times a year each entity's article is read."""
    conn.executemany("UPDATE entities SET views = ? WHERE qid = ?", [(v, q) for q, v in views.items()])
    conn.commit()


def _stocked(conn, n=40):
    """A category of n subjects, each with one fact, fame falling."""
    store.upsert_entities(conn, [(f"Q{i}", f"Thing {i}", "", 400 - i * 9) for i in range(n)])
    _read(conn, {f"Q{i}": 2_000_000 // (i + 1) for i in range(n)})
    store.save_category(conn, "Things", {"sets": []})
    store.add_members(conn, "Things", [f"Q{i}" for i in range(n)])
    store.replace_facts(conn, [f"Q{i}" for i in range(n)], [
        {"subject": f"Q{i}", "property": "P50", "value": f"Q{1000 + i}", "value_label": f"Author {i}",
         "value_description": "", "value_sitelinks": 400 - i * 9, "kind": "item", "values_for_subject": 1,
         "hardness": levels.hardness("P50", 400 - i * 9, 400 - i * 9)} for i in range(n)])


class TestPicking:
    def test_levels_are_ranks_within_the_category(self, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        _stocked(conn)
        facts = {f["subject"]: f for f in pick.pool(conn, "Things", False)}
        assert facts["Q0"]["level"] == 1.0 and facts["Q39"]["level"] == 10.0
        easy = pick.for_round(conn, "ch", "Things", 1.0, 3, seed=1)
        hard = pick.for_round(conn, "ch", "Things", 10.0, 3, seed=1)
        assert max(f["level"] for f in easy) < min(f["level"] for f in hard)

    def test_a_fact_is_used_once_per_channel_whatever_the_category(self, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        _stocked(conn, 12)
        store.save_category(conn, "Also", {"sets": []})
        store.add_members(conn, "Also", [f"Q{i}" for i in range(12)])
        first = pick.for_round(conn, "ch", "Things", 5, 12, seed=1)
        store.mark_used(conn, "ch", [f["id"] for f in first])
        assert pick.for_round(conn, "ch", "Also", 5, 5) == []
        assert len(pick.for_round(conn, "other channel", "Also", 5, 5)) == 5

    def test_one_subject_and_one_answer_per_round(self, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        store.upsert_entities(conn, [("Q1", "Hamlet", "", 200), ("Q2", "Macbeth", "", 190)])
        _read(conn, {"Q1": 900_000, "Q2": 800_000})
        store.save_category(conn, "Plays", {"sets": []})
        store.add_members(conn, "Plays", ["Q1", "Q2"])
        make = lambda s, p, v, label: {"subject": s, "property": p, "value": v, "value_label": label,
                                       "value_description": "", "value_sitelinks": 300, "kind": "item",
                                       "values_for_subject": 1, "hardness": 1.0}
        store.replace_facts(conn, ["Q1", "Q2"], [make("Q1", "P50", "Q692", "William Shakespeare"),
                                                 make("Q1", "P407", "Q1860", "English"),
                                                 make("Q2", "P50", "Q692", "William Shakespeare")])
        chosen = pick.for_round(conn, "ch", "Plays", 5, 3, seed=2)
        assert len({f["subject"] for f in chosen}) == len(chosen)
        assert len({f["value_label"] for f in chosen}) == len(chosen)

    def test_a_fact_stated_both_ways_is_one_fact(self, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        store.upsert_entities(conn, [("Q1", "Film One", "", 100), ("Q2", "Film Two", "", 90)])
        _read(conn, {"Q1": 300_000, "Q2": 200_000})
        make = lambda s, p, v, label: {"subject": s, "property": p, "value": v, "value_label": label,
                                       "value_description": "", "value_sitelinks": 90, "kind": "item",
                                       "values_for_subject": 1, "hardness": 1.0}
        store.replace_facts(conn, ["Q1", "Q2"], [make("Q1", "P156", "Q2", "Film Two"),
                                                 make("Q2", "P155", "Q1", "Film One")])
        first = conn.execute("SELECT id FROM facts WHERE property = 'P156'").fetchone()[0]
        store.mark_used(conn, "ch", [first])
        assert len(store.used_ids(conn, "ch")) == 2

    def test_backwards_only_when_nobody_else_has_the_value(self, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        store.upsert_entities(conn, [("Q750", "Bolivia", "", 300)])
        _read(conn, {"Q750": 1_500_000})
        store.save_category(conn, "Geo", {"sets": []})
        store.add_members(conn, "Geo", ["Q750"])
        make = lambda v, label: {"subject": "Q750", "property": "P36", "value": v, "value_label": label,
                                 "value_description": "", "value_sitelinks": 150, "kind": "item",
                                 "values_for_subject": 2, "hardness": 1.0}
        store.replace_facts(conn, ["Q750"], [make("Q1491", "La Paz"), make("Q2907", "Sucre")])
        asks = {f["value_label"]: f["ask"] for f in pick.pool(conn, "Geo", False)}
        assert asks == {"La Paz": "backward", "Sucre": "backward"}
        assert pick.answers_for({"ask": "backward", "subject_label": "Bolivia", "value_label": "Sucre"}) == ["Bolivia"]


class TestDefining:
    def test_ids_are_checked_against_wikidata(self, monkeypatch, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        monkeypatch.setattr(categories, "propose", lambda name, note="": {"general": False, "sets": [
            {"kind": "class", "name": "Planets", "items": [{"label": "planet", "qid": "Q111"}],
             "where_property": "", "where_values": [], "size": "small"},
            {"kind": "class", "name": "Nothing", "items": [{"label": "nothing at all", "qid": "Q1"}],
             "where_property": "", "where_values": [], "size": "small"}]})
        monkeypatch.setattr(wikidata, "labels", lambda qids: {"Q111": ("Mars", ""), "Q1": ("universe", "")})
        monkeypatch.setattr(wikidata, "search", lambda name, limit=7: (
            [{"id": "Q634", "label": "planet", "description": ""}] if name == "planet" else []))
        spec = categories.define(conn, "Space")
        # The guess that named the wrong thing is replaced by a search;
        # one with no match at all is left out.
        assert [s["classes"] for s in spec["sets"]] == [["Q634"]]
        assert store.category(conn, "space")["spec"] == spec

    def test_general_knowledge_is_every_fact_and_costs_nothing(self, monkeypatch, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        monkeypatch.setattr(categories, "propose", lambda *a, **k: pytest.fail("no model call"))
        assert categories.define(conn, "General Knowledge") == {"general": True, "sets": []}
        _stocked(conn, 5)
        assert len(pick.pool(conn, "General Knowledge", True)) == 5


class TestRoundsFromFacts:
    def _channel(self):
        from core.channels import ChannelConfig
        channel = ChannelConfig(key="pub", format="quiz", style_prompt="host")
        channel.quiz.questions = 3
        return channel

    def _fake_writer(self, monkeypatch, answer_for):
        from pipeline import quiz
        seen = {}

        def call_json(system, user, schema, **kwargs):
            if "fact checker" in str(system)[:200].lower():
                return {"checks": []}
            seen.setdefault("users", []).append(user)
            ids = [line.split(":")[0] for line in user.splitlines() if line.startswith("F")]
            return {"hook": "Know your books?", "intro": "Question one.", "outro": "Bye.",
                    "title_options": ["t"], "description_body": "d",
                    "questions": [{"lead_in": "", "question": f"Who wrote thing {i}?", "answer": answer_for(fid),
                                   "spoken_answer": answer_for(fid), "fact": fid}
                                  for i, fid in enumerate(ids)]}
        monkeypatch.setattr(quiz, "call_json", call_json)
        monkeypatch.setattr(quiz, "verify", lambda category, difficulty, questions: ["ok"] * len(questions))
        return seen

    def test_a_round_is_built_on_unused_facts_and_marks_them_used(self, monkeypatch):
        from pipeline import quiz
        conn = store.connect()
        _stocked(conn)
        authors = {f"F{r['id']}": r["value_label"] for r in conn.execute("SELECT id, value_label FROM facts")}
        seen = self._fake_writer(monkeypatch, lambda fid: authors[fid])
        channel = self._channel()
        script = quiz._write_checked(channel, "Things", "Hard")
        assert not script.quiz["unverified"]
        assert all(q.get("fact_id") for q in script.quiz["questions"])
        assert "The facts:" in seen["users"][0] and "Already asked" not in seen["users"][0]
        assert store.used_ids(conn, "pub") == {q["fact_id"] for q in script.quiz["questions"]}

    def test_an_answer_that_isnt_its_facts_is_replaced(self, monkeypatch):
        from pipeline import quiz
        conn = store.connect()
        _stocked(conn)
        authors = {f"F{r['id']}": r["value_label"] for r in conn.execute("SELECT id, value_label FROM facts")}
        wrong = {"first": True}

        def answer(fid):
            if wrong.pop("first", False):
                return "Someone Made Up"
            return authors[fid]
        self._fake_writer(monkeypatch, answer)
        script = quiz._write_checked(self._channel(), "Things", "Hard")
        assert "Someone Made Up" not in [q["answer"] for q in script.quiz["questions"]]
        assert not script.quiz["unverified"]

    def test_a_category_the_store_cant_supply_is_written_as_before(self, monkeypatch):
        from pipeline import quiz
        seen = self._fake_writer(monkeypatch, lambda fid: "x")
        quiz._facts(self._channel(), "Unknown", "Hard", 9)       # no category: nothing
        assert quiz._facts(self._channel(), "Unknown", "Hard", 9) == []
        assert "users" not in seen


def test_the_facts_page_shows_each_category(monkeypatch, tmp_path):
    from core.channels import channel_to_sparse_dict, write_raw, ChannelConfig
    from web import create_app
    path = tmp_path / "channels.json"
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
    write_raw({"pub": channel_to_sparse_dict(ChannelConfig(key="pub", format="quiz", style_prompt="host",
                                                            voice="21m00Tcm4TlvDq8ikWAM"))}, path)
    client = create_app().test_client()
    assert client.get("/facts").status_code == 200
    _stocked(store.connect(), 12)
    page = client.get("/facts").get_data(as_text=True)
    assert "Things" in page and "12" in page


def test_one_category_wikidata_wont_answer_doesnt_stop_the_rest(monkeypatch, tmp_path):
    """Regression: the first automatic run failed outright on one refusal."""
    from core.channels import ChannelConfig
    from core.errors import ExternalServiceError
    from pipeline.facts import keep
    conn = store.connect(tmp_path / "f.db")
    tried = []

    def one(conn, channel, name, say):
        tried.append(name)
        if name == "Science":
            raise ExternalServiceError("Wikidata", "no", user_message="Wikidata didn't answer.")
        return True
    monkeypatch.setattr(keep, "_stock_one", one)
    result = keep.stock(conn, ChannelConfig(key="q", format="quiz"), names=["Science", "Space"])
    assert tried == ["Science", "Space"]
    assert "Stocked Space." in result and "Science" in result


class TestQuality:
    """Regression: the first real harvest of Space rated "221 Eos orbits
    the Sun" as easy as it gets, and offered "19 Fortuna came after 18
    Melpomene". Asteroids are in dozens of Wikipedias by bot, but hardly
    anyone reads about them."""

    def _fact(self, s, p, v, label, sitelinks=300):
        return {"subject": s, "property": p, "value": v, "value_label": label, "value_description": "",
                "value_sitelinks": sitelinks, "kind": "item", "values_for_subject": 1, "hardness": 0.0}

    def test_things_hardly_anyone_reads_about_are_not_asked(self, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        store.upsert_entities(conn, [("Q1", "Mars", "", 290), ("Q2", "221 Eos", "", 60)])
        _read(conn, {"Q1": 1_300_000, "Q2": 4_000})
        store.save_category(conn, "Space", {"sets": []})
        store.add_members(conn, "Space", ["Q1", "Q2"])
        store.replace_facts(conn, ["Q1", "Q2"], [self._fact("Q1", "P61", "Q9", "Galileo"),
                                                 self._fact("Q2", "P61", "Q8", "Johann Palisa")])
        assert [f["subject_label"] for f in pick.pool(conn, "Space", False)] == ["Mars"]

    def test_an_answer_most_of_the_category_shares_gives_itself_away(self, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        things = [(f"Q{i}", f"Body {chr(65 + i)}", "", 100) for i in range(14)]
        store.upsert_entities(conn, things)
        _read(conn, {q: 200_000 for q, *_ in things})
        store.save_category(conn, "Space", {"sets": []})
        store.add_members(conn, "Space", [q for q, *_ in things])
        facts = [self._fact(q, "P397", "Q525", "Sun") for q, *_ in things[:10]]
        facts += [self._fact(q, "P397", f"Q9{i}", f"Planet {chr(65 + i)}") for i, (q, *_) in enumerate(things[10:])]
        store.replace_facts(conn, [q for q, *_ in things], facts)
        assert "Sun" not in {f["value_label"] for f in pick.pool(conn, "Space", False)}

    def test_numbered_sequences_are_not_asked(self, tmp_path):
        conn = store.connect(tmp_path / "f.db")
        store.upsert_entities(conn, [("Q1", "19 Fortuna", "", 60), ("Q2", "The Two Towers", "", 90)])
        _read(conn, {"Q1": 50_000, "Q2": 900_000})
        store.save_category(conn, "Mixed", {"sets": []})
        store.add_members(conn, "Mixed", ["Q1", "Q2"])
        store.replace_facts(conn, ["Q1", "Q2"], [self._fact("Q1", "P155", "Q3", "18 Melpomene"),
                                                 self._fact("Q2", "P155", "Q4", "The Fellowship of the Ring")])
        assert [f["subject_label"] for f in pick.pool(conn, "Mixed", False)] == ["The Two Towers"]

    def test_facts_are_only_fetched_for_things_people_read_about(self, world, monkeypatch):
        fake, conn = world
        _countries(fake)
        monkeypatch.setattr(wikidata, "yearly_views", lambda titles: {q: (100_000 if q != "Q34" else 50)
                                                                      for q in titles})
        store.save_category(conn, "Geography", {"sets": [{"name": "countries", "kind": "class",
                                                            "classes": ["Q6256"]}]})
        assert harvest.harvest(conn, "Geography")["fetched"] == 2
