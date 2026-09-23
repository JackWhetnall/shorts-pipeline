"""
`core.audience`: reading back how published videos are doing.

Every Google call is faked. What matters: the right videos are asked
about, a missing Analytics API still leaves the view counts, a video
YouTube no longer returns keeps its last numbers, and nothing is fetched
more often than it needs to be.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import audience, gallery


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


@pytest.mark.parametrize("url, expected", [
    ("https://youtube.com/shorts/hVBo_XAUGu0?feature=share", "hVBo_XAUGu0"),
    ("https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk"),
    ("https://youtu.be/abcdefghijk", "abcdefghijk"),
    ("https://www.tiktok.com/@x/video/1", ""),
    ("", ""),
])
def test_video_ids_come_out_of_every_url_shape(url, expected):
    assert audience.video_id(url) == expected


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(audience, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    channel = SimpleNamespace(output_dir=str(tmp_path / "c"))

    def video(name, url="", discarded=False):
        path = Path(channel.output_dir) / "2026-09-20" / f"{name}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        if url:
            gallery.save_publish_info(path, {"youtube_url": url})
        if discarded:
            gallery.set_discarded(path, True, "other")
        return path

    state = {"stats": True, "calls": [], "analytics_status": 200, "missing": set()}
    monkeypatch.setattr(audience.youtube, "connection", lambda key: {"stats": state["stats"]})
    monkeypatch.setattr(audience.youtube, "access_token", lambda key: "token")

    def fake_get(url, headers=None, params=None, timeout=None):
        state["calls"].append((url, params))
        if url == audience.DATA_URL:
            ids = [i for i in params["id"].split(",") if i not in state["missing"]]
            return FakeResponse(200, {"items": [
                {"id": i, "statistics": {"viewCount": "120", "likeCount": "7"}} for i in ids]})
        if state["analytics_status"] != 200:
            return FakeResponse(state["analytics_status"], {"error": {"errors": [
                {"reason": "accessNotConfigured"}]}})
        ids = params["filters"].split("==")[1].split(",")
        return FakeResponse(200, {
            "columnHeaders": [{"name": n} for n in
                              ("video", "views", "averageViewDuration",
                               "averageViewPercentage", "subscribersGained")],
            "rows": [[i, 120, 21, 64.5, 2] for i in ids]})

    monkeypatch.setattr(audience.requests, "get", fake_get)
    return SimpleNamespace(channel=channel, video=video, state=state)


def test_published_videos_get_views_and_retention(world):
    shorts = world.video("a", "https://youtube.com/shorts/AAAAAAAAAAA")
    world.video("waiting")                                   # not published
    world.video("dropped", "https://youtu.be/BBBBBBBBBBB", discarded=True)

    result = audience.refresh({"c": world.channel})

    assert result == {"c": {"updated": 1, "error": ""}}
    stats = gallery.load_stats(shorts)
    assert (stats["views"], stats["likes"]) == (120, 7)
    assert (stats["avg_view_percent"], stats["avg_view_seconds"], stats["subscribers_gained"]) == (64.5, 21, 2)
    data_call = next(p for u, p in world.state["calls"] if u == audience.DATA_URL)
    assert data_call["id"] == "AAAAAAAAAAA"


def test_without_the_analytics_api_views_still_arrive(world):
    path = world.video("a", "https://youtube.com/shorts/AAAAAAAAAAA")
    world.state["analytics_status"] = 403
    result = audience.refresh({"c": world.channel})

    assert result["c"]["updated"] == 1
    assert "retention couldn't be read" in result["c"]["error"]
    assert "API Library" in result["c"]["error"]
    assert gallery.load_stats(path)["views"] == 120
    assert audience.status()["c"]["error"] == result["c"]["error"]


def test_a_video_youtube_no_longer_returns_keeps_its_last_numbers(world):
    path = world.video("a", "https://youtube.com/shorts/AAAAAAAAAAA")
    gallery.save_stats(path, {"views": 999, "fetched_at": 0})
    world.state["missing"] = {"AAAAAAAAAAA"}
    audience.refresh({"c": world.channel})
    assert gallery.load_stats(path)["views"] == 999


def test_fresh_numbers_are_not_fetched_again_until_due(world):
    path = world.video("a", "https://youtube.com/shorts/AAAAAAAAAAA")
    gallery.save_stats(path, {"views": 5, "fetched_at": time.time()})
    assert audience.refresh({"c": world.channel}) == {}
    assert not world.state["calls"]
    assert audience.refresh({"c": world.channel}, force=True)["c"]["updated"] == 1


def test_a_channel_without_the_statistics_permission_is_left_alone(world):
    world.video("a", "https://youtube.com/shorts/AAAAAAAAAAA")
    world.state["stats"] = False
    assert audience.refresh({"c": world.channel}) == {}
    assert not world.state["calls"]
