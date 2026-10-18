"""
The growth tools of decision 114: teasers that send viewers to the
linked film, A/B test options for each film, films into playlists and
the channel's keywords, and where a film's viewers left.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as N

from core import playlists, youtube
from pipeline.documentary import teasers


def test_a_linked_channels_teasers_end_on_tap_the_link():
    linked = teasers.system(N(documentary=N(teasers_linked=True)))
    unlinked = teasers.system(N(documentary=N(teasers_linked=False)))
    assert "Tap the link below" in linked and "Check out our channel" not in linked
    assert "Check out our channel" in unlinked and "{ending}" not in unlinked


def test_only_a_documentary_channel_asks_to_manage_youtube(monkeypatch):
    monkeypatch.setattr(youtube, "client_config", lambda: {"client_id": "c"})
    from urllib.parse import parse_qs, urlparse
    scopes = lambda url: set(parse_qs(urlparse(url).query)["scope"][0].split())
    assert youtube.MANAGE_SCOPE not in scopes(youtube.authorize_url("http://x/cb", "s"))
    assert youtube.MANAGE_SCOPE in scopes(youtube.authorize_url("http://x/cb", "s", (youtube.MANAGE_SCOPE,)))


class _Api:
    def __init__(self):
        self.made, self.added = [], []

    def get(self, url, headers=None, params=None, timeout=None):
        if url.endswith("/playlists"):
            return N(status_code=200, json=lambda: {"items": [{"id": "PL1", "snippet": {"title": "The Ocean, Explained"}}]})
        raise AssertionError(url)

    def post(self, url, headers=None, params=None, timeout=None, json=None):
        if url.endswith("/playlists"):
            self.made.append(json["snippet"]["title"])
            return N(status_code=200, json=lambda: {"id": "PL2"})
        self.added.append(json["snippet"]["playlistId"])
        return N(status_code=200, json=lambda: {})


def test_a_film_goes_into_its_playlist_or_a_new_one(monkeypatch, tmp_path):
    api = _Api()
    monkeypatch.setattr(playlists, "requests", N(get=api.get, post=api.post, RequestException=Exception))
    monkeypatch.setattr(playlists, "PLACED_PATH", tmp_path / "placed.json")
    monkeypatch.setattr(playlists, "can_manage", lambda key: True)
    monkeypatch.setattr(playlists, "_headers", lambda key: {})
    monkeypatch.setattr(youtube, "_json_or_raise", lambda response, doing: response.json())
    monkeypatch.setattr(playlists.gallery, "load_publish_info", lambda v: {"title": "How Deep Is the Ocean?",
                                                                         "description": ""})
    picks = iter(["The Ocean, Explained", "Your Body's Strange Habits"])
    monkeypatch.setattr(playlists, "_choose", lambda title, about, existing: next(picks))
    channel = N(key="why")
    assert playlists.add_film(channel, tmp_path / "ocean.mp4", "vid1") == "The Ocean, Explained"
    assert playlists.add_film(channel, tmp_path / "hiccups.mp4", "vid2") == "Your Body's Strange Habits"
    assert api.made == ["Your Body's Strange Habits"] and api.added == ["PL1", "PL2"]
    assert json.loads((tmp_path / "placed.json").read_text())["why"] == {"vid1": "The Ocean, Explained",
                                                                         "vid2": "Your Body's Strange Habits"}


def test_without_the_permission_nothing_is_tried(monkeypatch, tmp_path):
    monkeypatch.setattr(playlists, "can_manage", lambda key: False)
    assert playlists.add_film(N(key="why"), tmp_path / "a.mp4", "v") == ""
    assert playlists.ensure_keywords(N(key="why")) is False


def test_where_viewers_left_reads_youtubes_three_value_curve(monkeypatch, tmp_path):
    # YouTube's curve rows are [position, still watching, relative]: the first try unpacked two.
    from web.blueprints import gallery as page
    video = tmp_path / "film.mp4"
    monkeypatch.setattr("pipeline.documentary.thumbs.is_documentary", lambda v: True)
    monkeypatch.setattr(page.gallery_core, "load_stats", lambda v: {"curve": [[0.01, 1.0, 0.2], [0.5, 0.25, 0.1],
                                                                            [1.0, 0.1, 0.05]]})
    monkeypatch.setattr(page.gallery_core, "load_report", lambda v: {"video_seconds": 540})
    monkeypatch.setattr("core.retention.for_video", lambda v: {"kept_30s": 60, "end": 10,
                                                                "drops": [{"scene": 3, "at": 8, "lost": 35.8}]})
    r = page._retention(video)
    assert r["chart"]["series"][0]["points"][1] == [270.0, 25.0] and r["chart"]["x"] == "seconds"
    assert r["kept_30s"] == 60 and r["drops"][0]["at"] == 8


def test_ab_options_are_listed_with_their_studio_page(monkeypatch, tmp_path):
    from web.blueprints import gallery as page
    monkeypatch.setattr("pipeline.documentary.thumbs.is_documentary", lambda v: True)
    monkeypatch.setattr("pipeline.documentary.thumbs.load_ab", lambda v: {"titles": ["A", "B", "C"],
                                                                         "thumbs": ["x", "y", "z"]})
    ab = page._ab_options(tmp_path / "film.mp4", {"youtube_url": "https://www.youtube.com/watch?v=abcdefghijk"})
    assert ab["titles"] == ["A", "B", "C"] and ab["thumbs"] == ["thumb_1.jpg", "thumb_2.jpg", "thumb_3.jpg"]
    assert ab["studio"] == "https://studio.youtube.com/video/abcdefghijk/edit"
