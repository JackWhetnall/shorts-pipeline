"""
A restart in the night (decision 097): Windows restarted the PC for an
update at 00:14 on 14 October. A film stage cut short must be picked up
again rather than left "working" for ever, files must be whole or not
there, and a damaged record must never be replaced by a blank film.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as N

import pytest

from core import production
from core.paths import write_atomically


@pytest.fixture
def films(tmp_path, monkeypatch):
    monkeypatch.setattr(production, "CHANNELS_DIR", tmp_path)
    return tmp_path


def _film(stages: dict) -> dict:
    data = production.blank("t1", "Deep")
    for stage, state in stages.items():
        data["stages"][stage]["state"] = state
    return data


def test_a_stage_a_restart_cut_short_is_failed_flagged_and_explained(films):
    production.save("doc", _film({"pitch": "approved", "outline": "approved", "script": "working"}))
    production.save("doc", dict(_film({"pitch": "approved"}), subtopic_id="t2"))
    assert production.recover_interrupted(["doc"]) == [("doc", "t1", "script")]
    entry = production.load("doc", "t1")["stages"]["script"]
    assert entry["state"] == "failed" and entry["interrupted"] and "restarted" in entry["error"]
    assert production.recover_interrupted(["doc"]) == []                     # only once


def test_the_autopilot_starts_an_interrupted_stage_again_without_using_its_retry(monkeypatch):
    from core import auto_films
    import core.channels as config
    stages = {"pitch": {"state": "approved"}, "outline": {"state": "approved"},
              "script": {"state": "failed", "interrupted": True, "autopilot_retried": True}}
    data = {"stages": stages}
    monkeypatch.setattr(auto_films, "_busy", lambda k: False)
    monkeypatch.setattr(auto_films, "_next_film", lambda c: ({"id": "t1", "title": "T"}, data, False))
    monkeypatch.setattr(production, "update", lambda k, s, change, *a: change(data))
    started = []
    monkeypatch.setattr(auto_films, "start", lambda c, r, s: started.append(s) or "j")
    channel = N(key="doc", format="documentary", archived=False, publishing=N(enabled=True),
                animation=N(style={"approach": "acted"}),
                documentary=N(auto_make=True, ahead=3, teasers=0, overseen=True, hours="22-8"))
    monkeypatch.setattr(config, "within_hours", lambda text, hour: False)
    assert auto_films.step(channel) == "" and started == []                   # waits for its hours
    monkeypatch.setattr(config, "within_hours", lambda text, hour: True)
    assert auto_films.step(channel) and started == ["script"]
    assert "interrupted" not in stages["script"]


def test_a_damaged_record_is_left_alone_never_replaced_by_a_blank_film(films):
    production.save("doc", _film({"pitch": "approved"}))
    path = production._path("doc", "t1")
    path.write_text('{"subtopic_id": "t1", "stag', encoding="utf-8")
    with pytest.raises(production.ProductionError):
        production.load("doc", "t1")
    with pytest.raises(production.ProductionError):
        production.update("doc", "t1", lambda d: None)
    assert path.read_text(encoding="utf-8").endswith('"stag')                # untouched
    assert production.all_for("doc") == []                                   # the rest of the page still works
    assert production.load("doc", "t9")["stages"]["pitch"]["state"] == "todo"   # a new film is still blank


def test_files_are_written_whole_text_or_bytes(tmp_path):
    write_atomically(tmp_path / "a.json", json.dumps({"x": 1}))
    write_atomically(tmp_path / "b.jpg", b"\xff\xd8 picture")
    assert json.loads((tmp_path / "a.json").read_text()) == {"x": 1}
    assert (tmp_path / "b.jpg").read_bytes() == b"\xff\xd8 picture"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json", "b.jpg"]  # no temporary left
