"""
core.music_library: finding, keeping and crediting each channel's music.
Openverse and the model are faked; nothing is downloaded.
"""

from __future__ import annotations

import json

import pytest

from core import music_library
from core.channels import ChannelConfig
from core.errors import PipelineError


def result(i, licence="by", seconds=120, title=None):
    return {"id": f"id{i}", "title": title or f"Track {i}", "creator": "Someone", "license": licence,
            "license_version": "4.0", "duration": seconds * 1000, "url": f"https://x/{i}.mp3",
            "foreign_landing_url": "https://x", "source": "freesound", "genres": [],
            "tags": [{"name": "calm"}]}


class Response:
    def __init__(self, data=None, content=b"", status=200):
        self._data, self.content, self.status_code = data or {}, content, status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise music_library.requests.HTTPError("bad")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(music_library, "REGISTRY", tmp_path / "music" / "registry.json")
    monkeypatch.setattr(music_library, "CANDIDATES", tmp_path / "cache")
    monkeypatch.setattr(music_library, "CHANNELS_DIR", tmp_path / "channels")
    return tmp_path


def test_only_licences_a_monetised_video_can_use(world, monkeypatch):
    monkeypatch.setattr(music_library.requests, "get", lambda *a, **k: Response({"results": [
        result(1, "by"), result(2, "cc0"), result(3, "by-nc"), result(4, "by-sa"),
        result(5, "pdm"), result(6, "by", seconds=10)]}))
    assert [t["id"] for t in music_library._search("calm")] == ["id1", "id2", "id5"]


def _fake_suggest(monkeypatch, results):
    monkeypatch.setattr(music_library.requests, "get", lambda *a, **k: Response({"results": results}))
    monkeypatch.setattr(music_library, "_judge", lambda pool, description: [dict(c, why="fits") for c in pool])


def test_a_track_another_channel_uses_is_never_suggested(world, monkeypatch):
    _fake_suggest(monkeypatch, [result(1), result(2)])
    monkeypatch.setattr(music_library.requests, "get", lambda url, **k: Response(
        {"results": [result(1), result(2)]}) if "openverse" in url else Response(content=b"mp3"))
    music_library.add("wren", music_library.suggest("wren", "d", ["calm"])["tracks"][0])
    ids = [t["id"] for t in music_library.suggest("pastor", "d", ["calm"])["tracks"]]
    assert "id1" not in ids and "id2" in ids
    with pytest.raises(PipelineError) as err:
        music_library.add("pastor", music_library.candidate("id1"))
    assert "Another channel" in err.value.user_message


def test_adding_and_removing_keeps_the_registry_and_the_credit(world, monkeypatch):
    _fake_suggest(monkeypatch, [result(1)])
    track = music_library.suggest("pastor", "d", ["calm"])["tracks"][0]
    monkeypatch.setattr(music_library.requests, "get", lambda *a, **k: Response(content=b"mp3"))
    path = music_library.add("pastor", track)
    assert path.read_bytes() == b"mp3"
    assert music_library.credit_for(path) == "Music: Track 1 by Someone (CC BY 4.0)."
    assert music_library.owner("id1") == "pastor"
    assert [t["title"] for t in music_library.tracks("pastor")] == ["Track 1"]
    music_library.remove("pastor", path.name)
    assert not path.exists() and music_library.owner("id1") == ""


def test_public_domain_music_needs_no_credit():
    assert music_library.credit({"licence": "cc0", "title": "T"}) == ""


def test_a_narrow_search_is_widened_when_too_little_suits(world, monkeypatch):
    queries = []

    def search(query):
        queries.append(query)
        return [dict(result(len(queries)), id=f"q{len(queries)}")]

    monkeypatch.setattr(music_library, "_search", search)
    monkeypatch.setattr(music_library, "_judge", lambda pool, d: [dict(c, why="") for c in pool])
    found = music_library.suggest("c", "d", ["ethereal lo-fi magic"])
    assert queries[0] == "ethereal lo-fi magic" and queries[1:] == music_library.BROADER
    assert len(found["tracks"]) == 1 + len(music_library.BROADER)


def test_auto_fill_never_breaks_a_render(world, monkeypatch):
    def down(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(music_library, "suggest", down)
    assert music_library.auto_fill(ChannelConfig(key="c")) == []


def test_auto_fill_adds_the_best_few(world, monkeypatch):
    _fake_suggest(monkeypatch, [result(i) for i in range(6)])
    monkeypatch.setattr(music_library, "_moods", lambda description: ["calm piano"])
    monkeypatch.setattr(music_library.requests, "get", lambda url, **k: Response(
        {"results": [result(i) for i in range(6)]}) if "openverse" in url else Response(content=b"mp3"))
    added = music_library.auto_fill(ChannelConfig(key="c"))
    assert len(added) == music_library.AUTO_TRACKS


class TestPages:
    @pytest.fixture
    def client(self, world, monkeypatch):
        from web import create_app
        monkeypatch.setattr("web.blueprints.music.channel_or_404",
                            lambda key: ChannelConfig(key=key, style_prompt="Warm."))
        monkeypatch.setattr("web.blueprints.music.save_channel", lambda channel: None)
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()
        with client.session_transaction() as session:
            session["_csrf_token"] = "t"
        client.environ_base["HTTP_X_CSRF_TOKEN"] = "t"
        return client

    def test_suggestions_come_back_as_json(self, client, monkeypatch):
        monkeypatch.setattr(music_library, "suggest", lambda key, d, moods: {
            "moods": ["calm piano"], "tracks": [{"id": "id1", "title": "T"}]})
        data = client.get("/channels/pastor/music/suggest").get_json()
        assert data["tracks"][0]["id"] == "id1"

    def test_add_and_remove(self, client, monkeypatch):
        added, removed = [], []
        monkeypatch.setattr(music_library, "candidate", lambda i: {"id": i})
        monkeypatch.setattr(music_library, "add", lambda key, t: added.append((key, t["id"])))
        monkeypatch.setattr(music_library, "remove", lambda key, f: removed.append((key, f)))
        monkeypatch.setattr(music_library, "tracks", lambda key: [])
        assert client.post("/channels/pastor/music/add", json={"id": "id1"}).status_code == 200
        assert client.post("/channels/pastor/music/remove", json={"file": "a.mp3"}).status_code == 200
        assert added == [("pastor", "id1")] and removed == [("pastor", "a.mp3")]
