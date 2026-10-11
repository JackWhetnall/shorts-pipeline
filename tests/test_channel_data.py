"""
Renaming a channel carries all its data across (core.channel_data,
decision 057). The owner renamed the quiz channel and it showed no topics
and no videos: its topic plan, question memory and the rest were still
filed under the old name.

Every store keyed by channel is covered; nothing is overwritten; running
it twice changes nothing more.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from core import audience, channel_data, corpus, costs, curriculum, gallery, paths, publish_queue, youtube
from pipeline import quiz, similarity
from pipeline.facts import store

OLD, NEW = "the_pub_quiz_round", "pub_quiz_buzz"


@pytest.fixture
def world(monkeypatch, tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", cfg / "curricula")
    monkeypatch.setattr(quiz, "QUESTION_BANK_DIR", cfg / "question_banks")
    monkeypatch.setattr(corpus, "CORPORA_DIR", cfg / "corpora")
    monkeypatch.setattr(youtube, "TOKENS_DIR", cfg / "youtube_tokens")
    monkeypatch.setattr(similarity, "SCRIPT_HISTORY_PATH", cfg / "script_history.json")
    monkeypatch.setattr(publish_queue, "STATE_PATH", cfg / "publishing_state.json")
    monkeypatch.setattr(paths, "SCHEDULE_PATH", cfg / "schedule.json")
    monkeypatch.setattr(audience, "STATUS_PATH", tmp_path / "audience.json")
    monkeypatch.setattr(costs, "COST_LOG_PATH", cfg / "cost_log.jsonl")
    monkeypatch.setattr(gallery, "DISCARD_HISTORY_PATH", cfg / "discard.jsonl")
    monkeypatch.setattr(paths, "JOB_STATE_DIR", tmp_path / "jobs")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "facts.db")
    monkeypatch.setattr(paths, "LIBRARY_DB_PATH", tmp_path / "library.db")
    monkeypatch.setattr("core.channels.load_channels", lambda validate=True: {})
    return tmp_path, cfg


def _fill(tmp, cfg):
    (cfg / "curricula").mkdir()
    (cfg / "curricula" / f"{OLD}.json").write_text(json.dumps(
        {"version": 2, "channel": OLD, "topics": [{"id": "t1"}], "subtopics": [{"id": "s1", "topic": "t1"}]}))
    (cfg / "question_banks").mkdir()
    (cfg / "question_banks" / f"{OLD}.json").write_text("[]")
    (cfg / "youtube_tokens").mkdir()
    (cfg / "youtube_tokens" / f"{OLD}.json").write_text("{}")
    (cfg / "script_history.json").write_text(json.dumps({
        "other": [{"video": "output/other/a.mp4"}],
        OLD: [{"title": "x", "video": f"output/{OLD}/2026-10-01/x.mp4"},
              {"title": "y", "video": f"output\\{OLD}\\2026-10-01\\y.mp4"}]}))
    (cfg / "cost_log.jsonl").write_text(
        json.dumps({"channel_key": OLD, "cost_usd": 1}) + "\n" + "not json\n" +
        json.dumps({"channel_key": "other", "cost_usd": 2}) + "\n" + json.dumps({"cost_usd": 3}) + "\n")
    (cfg / "discard.jsonl").write_text(json.dumps({"channel": OLD, "stem": "z"}) + "\n")
    conn = store.connect()
    with conn:
        conn.execute("INSERT INTO used (fact_id, channel, round, used_at) VALUES (1, ?, '', 'now')", (OLD,))
        conn.execute("INSERT INTO used (fact_id, channel, round, used_at) VALUES (1, ?, '', 'now')", (NEW,))
        conn.execute("INSERT INTO used (fact_id, channel, round, used_at) VALUES (2, ?, '', 'now')", (OLD,))
        conn.execute("INSERT INTO question_used (question_id, channel, round, used_at) VALUES (7, ?, '', 'now')",
                     (OLD,))
    jobs = tmp_path_jobs = tmp / "jobs" / "j1"
    jobs.mkdir(parents=True)
    (jobs / "job.json").write_text(json.dumps({"channel_key": OLD, "result_path": f"output/{OLD}/d/v.mp4"}))
    lib = sqlite3.connect(tmp / "library.db")
    lib.execute("CREATE TABLE clips (filename TEXT, owner TEXT)")
    lib.execute("INSERT INTO clips VALUES ('a.mp4', ?)", (OLD,))
    lib.commit()
    lib.close()


def test_everything_filed_under_the_old_name_moves_to_the_new(world):
    tmp, cfg = world
    _fill(tmp, cfg)
    assert channel_data.migrate(OLD, NEW) == []
    plan = json.loads((cfg / "curricula" / f"{NEW}.json").read_text())
    assert plan["channel"] == NEW and plan["subtopics"] == [{"id": "s1", "topic": "t1"}]
    assert not (cfg / "curricula" / f"{OLD}.json").exists()
    assert (cfg / "question_banks" / f"{NEW}.json").exists() and (cfg / "youtube_tokens" / f"{NEW}.json").exists()
    history = json.loads((cfg / "script_history.json").read_text())
    assert OLD not in history and history["other"] == [{"video": "output/other/a.mp4"}]
    assert [e["video"] for e in history[NEW]] == [f"output/{NEW}/2026-10-01/x.mp4",
                                                  f"output\\{NEW}\\2026-10-01\\y.mp4"]
    lines = (cfg / "cost_log.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["channel_key"] == NEW and lines[1] == "not json"
    assert json.loads(lines[2])["channel_key"] == "other" and json.loads(lines[3]) == {"cost_usd": 3}
    assert json.loads((cfg / "discard.jsonl").read_text())["channel"] == NEW
    conn = store.connect()
    assert sorted(r[0] for r in conn.execute("SELECT fact_id FROM used WHERE channel = ?", (NEW,))) == [1, 2]
    assert conn.execute("SELECT COUNT(*) FROM used WHERE channel = ?", (OLD,)).fetchone()[0] == 0
    assert conn.execute("SELECT channel FROM question_used").fetchall()[0][0] == NEW
    job = json.loads((tmp / "jobs" / "j1" / "job.json").read_text())
    assert job == {"channel_key": NEW, "result_path": f"output/{NEW}/d/v.mp4"}
    assert sqlite3.connect(tmp / "library.db").execute("SELECT owner FROM clips").fetchone()[0] == NEW


def test_the_topic_plan_is_found_and_saved_under_the_new_name(world):
    tmp, cfg = world
    _fill(tmp, cfg)
    channel_data.migrate(OLD, NEW)
    assert curriculum.exists(NEW) and not curriculum.exists(OLD)
    data = curriculum.load(NEW)
    curriculum.save(data)                                   # writes where the name inside says
    assert not (cfg / "curricula" / f"{OLD}.json").exists()


def test_running_it_again_changes_nothing_more(world):
    tmp, cfg = world
    _fill(tmp, cfg)
    channel_data.migrate(OLD, NEW)
    before = {p: p.read_bytes() for p in cfg.rglob("*") if p.is_file()}
    assert channel_data.migrate(OLD, NEW) == []
    assert {p: p.read_bytes() for p in cfg.rglob("*") if p.is_file()} == before


def test_it_never_overwrites_what_the_new_name_already_has(world):
    tmp, cfg = world
    _fill(tmp, cfg)
    (cfg / "curricula" / f"{NEW}.json").write_text(json.dumps({"version": 2, "channel": NEW, "topics": []}))
    problems = channel_data.migrate(OLD, NEW)
    assert len(problems) == 1 and "topic plan" in problems[0]
    assert (cfg / "curricula" / f"{OLD}.json").exists()                  # still there, not lost
    assert json.loads((cfg / "curricula" / f"{NEW}.json").read_text())["topics"] == []
    assert (cfg / "question_banks" / f"{NEW}.json").exists()             # the others still moved


def test_a_record_the_new_name_already_has_is_joined_not_replaced(world):
    tmp, cfg = world
    _fill(tmp, cfg)
    history = json.loads((cfg / "script_history.json").read_text())
    history[NEW] = [{"title": "newer", "video": "output/x/n.mp4"}]
    (cfg / "script_history.json").write_text(json.dumps(history))
    channel_data.migrate(OLD, NEW)
    titles = [e["title"] for e in json.loads((cfg / "script_history.json").read_text())[NEW]]
    assert titles == ["x", "y", "newer"]


def test_a_store_that_fails_doesnt_stop_the_others(world, monkeypatch):
    tmp, cfg = world
    _fill(tmp, cfg)
    (cfg / "script_history.json").write_text("{ broken")
    problems = channel_data.migrate(OLD, NEW)
    assert any("originality history" in p for p in problems)
    assert (cfg / "curricula" / f"{NEW}.json").exists()
    assert json.loads((cfg / "cost_log.jsonl").read_text().splitlines()[0])["channel_key"] == NEW


def test_renaming_a_channel_does_it_all(world, monkeypatch):
    """The real rename (core.channel_admin) ends in this migration."""
    from core import channel_admin
    tmp, cfg = world
    _fill(tmp, cfg)
    monkeypatch.setattr(channel_admin, "read_raw", lambda: {OLD: {"channel_display_name": "x"}})
    monkeypatch.setattr(channel_admin, "write_raw", lambda entries: None)
    monkeypatch.setattr(channel_admin, "CHANNELS_DIR", tmp / "channels")
    monkeypatch.setattr(channel_admin, "PROJECT_ROOT", tmp)
    result = channel_admin.rename_channel(OLD, "Pub Quiz Buzz")
    assert result["new_key"] == NEW and result["problems"] == []
    assert curriculum.exists(NEW) and not curriculum.exists(OLD)


def test_a_documentarys_lessons_move_with_the_channel(world, monkeypatch):
    """Decision 086: what viewers taught a channel is filed in its own
    folder (core.lessons), which the rename moves."""
    from core import channel_admin, lessons
    tmp, cfg = world
    _fill(tmp, cfg)
    monkeypatch.setattr(channel_admin, "read_raw", lambda: {OLD: {"channel_display_name": "x"}})
    monkeypatch.setattr(channel_admin, "write_raw", lambda entries: None)
    monkeypatch.setattr(channel_admin, "CHANNELS_DIR", tmp / "channels")
    monkeypatch.setattr(channel_admin, "PROJECT_ROOT", tmp)
    monkeypatch.setattr(lessons, "CHANNELS_DIR", tmp / "channels")
    lessons.add(OLD, ["Open on the surprise, not the setting."], source="film_one")
    channel_admin.rename_channel(OLD, "Pub Quiz Buzz")
    assert lessons.texts(NEW) == ["Open on the surprise, not the setting."] and lessons.texts(OLD) == []
