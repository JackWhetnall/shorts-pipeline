"""
Thumbnail tests (core.thumbnail_tests, core.reach, decision 083).

The owner: "we would need some thumbnails tested, with insights feedback
about which perform better. we would then need auto adjustment (A
performed best, B and C worse - how can we adjust B and C slightly to see
what it is about A that works; then continue comparisons in future)."
Shorts are rotated by the app; long videos use Studio's own test.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import reach, thumbnail_tests as tt
from pipeline import thumbnail_variants as tv

DAY = 86400


@pytest.fixture
def channel(tmp_path, monkeypatch):
    monkeypatch.setattr(tt, "CHANNELS_DIR", tmp_path)
    monkeypatch.setattr(reach, "CHANNELS_DIR", tmp_path)
    monkeypatch.setattr(tv, "render_short", lambda channel, video, recipe, out: out.write_bytes(b"j") or out)
    monkeypatch.setattr(tv, "render_long", lambda channel, video, recipe, out: out.write_bytes(b"j") or out)
    return SimpleNamespace(key="pqb")


def test_each_round_tries_the_recipe_against_two_single_changes(channel):
    data = tt.load("pqb")
    variants = tt.next_variants(data)
    assert [v[0] for v in variants] == ["A", "B", "C"] and variants[0][2] is None
    for label, recipe, change in variants[1:]:
        assert sum(recipe[n] != data["recipe"][n] for n in recipe) == 1 and recipe[change[0]] == change[2]


def test_a_winning_change_is_kept_and_pushed_further(channel):
    data = tt.load("pqb")
    r = {"variants": [{"label": l, "recipe": rc, "change": c} for l, rc, c in tt.next_variants(data)], "result": {}}
    tt.learn(data, r, "B")
    data["rounds"].append(r)
    name, before, after = r["variants"][1]["change"]
    assert data["recipe"][name] == after
    nxt = tt.next_variants(data)
    assert nxt[1][2][0] == name and nxt[1][2][1] == after                 # the same setting, a step on


def test_when_the_recipe_wins_the_changes_tried_get_smaller(channel):
    data = tt.load("pqb")
    data["recipe"]["text_scale"] = 1.0
    r = {"variants": [{"label": "A", "recipe": dict(data["recipe"]), "change": None},
                      {"label": "B", "recipe": {**data["recipe"], "text_scale": 1.15}, "change": ["text_scale", 1.0, 1.15]},
                      {"label": "C", "recipe": {**data["recipe"], "background": "dark"}, "change": ["background", "plain", "dark"]}],
         "result": {}}
    tt.learn(data, r, "A")
    assert data["steps"]["text_scale"] == pytest.approx(0.075) and "dark" in data["tried"]["background"]


def test_a_short_rotates_after_settling_and_each_starts_somewhere_else(channel):
    joined = 0.0
    first = {"joined": joined, "offset": 0}
    second = {"joined": joined, "offset": 1}
    assert tt.scheduled_label(first, joined + 1 * DAY) == "A"                         # settling
    assert [tt.scheduled_label(first, joined + (2 + 3 * k + 1) * DAY) for k in range(6)] == ["A", "B", "C"] * 2
    assert tt.scheduled_label(second, joined + 3 * DAY) == "B"
    assert tt.scheduled_label(first, joined + 30 * DAY) is None                        # done


def test_rotation_changes_the_thumbnail_on_youtube_when_due(channel, tmp_path, monkeypatch):
    from core import youtube
    sent = []
    monkeypatch.setattr(youtube, "set_thumbnail", lambda key, vid, path: sent.append((vid, path.name)))
    video = tmp_path / "space_easy.mp4"
    video.write_bytes(b"x")
    round_ = tt.join_rotation(channel, video, "vid12345678")
    assert {v["label"] for v in round_["variants"]} == {"A", "B", "C"}
    assert tt.join_rotation(channel, video, "vid12345678") is None              # not twice
    joined = tt.load("pqb")["rounds"][0]["videos"][0]["joined"]
    assert tt.rotate(channel, joined + 1 * DAY) == 0                              # still A
    assert tt.rotate(channel, joined + 6 * DAY) == 1 and sent == [("vid12345678", "space_easy_thumb_b.jpg")]
    assert tt.rotate(channel, joined + 6.5 * DAY) == 0


def test_a_finished_round_names_the_winner_from_click_through(channel, monkeypatch):
    data = tt.load("pqb")
    round_ = tt.start_round(data, "rotation")
    start = 1_000_000_000.0
    for i in range(tt.ROUND_SIZE):
        round_["videos"].append({"stem": f"v{i}", "path": f"v{i}.mp4", "video_id": f"id{i}", "joined": start,
                                 "offset": 0, "log": [[start + 2 * DAY, "A"], [start + 5 * DAY, "B"], [start + 8 * DAY, "C"]]})
    tt._save("pqb", data)
    from datetime import datetime, timezone

    def day(n):
        return datetime.fromtimestamp(start + n * DAY, timezone.utc).date().isoformat()
    figures = {}
    for n, ctr in ((3, 0.04), (4, 0.04), (6, 0.07), (7, 0.07), (9, 0.04), (10, 0.04)):
        figures[day(n)] = (200, ctr)
    monkeypatch.setattr(reach, "days", lambda key, vid: figures)
    done = tt.finish_rotations(channel, start + 40 * DAY)
    finished = tt.load("pqb")["rounds"][0]
    assert done == [finished["id"]] and finished["result"]["winner"] == "B"
    assert tt.load("pqb")["recipe"] == finished["variants"][1]["recipe"]


def test_studio_names_the_winner_for_a_long_video(channel, tmp_path):
    video = tmp_path / "quiz_night_2.mp4"
    video.write_bytes(b"x")
    round_ = tt.studio_round(channel, video)
    assert tt.studio_round(channel, video)["id"] == round_["id"]                  # made once
    assert all((tmp_path / f"quiz_night_2_thumb_{l}.jpg").exists() for l in "abc")
    tt.studio_result("pqb", round_["id"], "C")
    assert tt.load("pqb")["recipe"] == round_["variants"][2]["recipe"]


def test_reach_reports_are_read_once(channel, monkeypatch):
    calls = []

    class Response:
        def __init__(self, data=None, content=b""):
            self.status_code, self._data, self.content = 200, data, content

        def json(self):
            return self._data
    monkeypatch.setattr("core.youtube.access_token", lambda key: "t")
    body = b"date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n20261005,c,vidA,120,0.05\n"

    def get(url, headers=None, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/jobs"):
            return Response({"jobs": [{"id": "j1", "reportTypeId": reach.REPORT_TYPE}]})
        if url.endswith("/reports"):
            return Response({"reports": [{"id": "r1", "downloadUrl": "https://dl/r1"}]})
        return Response(content=body)
    monkeypatch.setattr(reach.requests, "get", get)
    assert reach.fetch("pqb") == 1 and reach.fetch("pqb") == 0
    assert reach.days("pqb", "vidA") == {"2026-10-05": (120, 0.05)}
    assert calls.count("https://dl/r1") == 1
