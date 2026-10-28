"""
Decision 139. The owner, 28 Oct:
- Insights showed Why, Though?, the biggest spender, at $0, and "38 videos
  waiting for review" with the review queue empty;
- the channels still being tried out cluttered Today and Insights;
- "a page ... that shows what went out yesterday (or since ... cleared)";
- Insights "doesn't show the trajectory ... these comparative insights
  should compare things on a week-by-week basis".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from core import digest, insights


def _video(**kw):
    return {"discarded": False, "published": False, "out": False, "queued": False, "set_aside": False, **kw}


def test_only_videos_waiting_for_a_look_are_awaiting_review():
    videos = [_video(queued=True), _video(queued=True), _video(set_aside=True), _video(), _video(published=True),
              _video(discarded=True)]
    totals = insights._totals(videos)
    assert totals["awaiting_review"] == 1 and totals["queued"] == 2


def test_a_channels_spend_is_everything_the_cost_log_has_for_it(monkeypatch):
    monkeypatch.setattr(insights.costs, "read_records", lambda: [
        {"channel_key": "why", "cost_usd": 1.5, "production": "t1"}, {"channel_key": "why", "cost_usd": 0.5},
        {"channel_key": "quiz", "cost_usd": 0.25}])
    channels = {"why": SimpleNamespace(channel_display_name="Why"), "quiz": SimpleNamespace(channel_display_name="Q")}
    rows = insights._by_channel([{**_video(), "channel_key": "why"}, {**_video(), "channel_key": "quiz"}], channels)
    assert {r["key"]: r["spend_usd"] for r in rows} == {"why": 2.0, "quiz": 0.25}


def _days(start: date, n: int, views):
    return [{"day": (start + timedelta(days=i)).isoformat(), "short_views": views(i), "long_views": 0,
             "long_minutes": 0.0, "subs_net": 0} for i in range(n)]


def test_weeks_compare_with_weeks_and_the_week_under_way_with_the_same_days():
    today = date(2026, 10, 28)                                   # a Wednesday
    monday = today - timedelta(days=today.weekday())
    # Two weeks ago 10 a day, last week 50 a day, this week Mon-Tue 60 a day.
    days = _days(monday - timedelta(weeks=2), 7, lambda i: 10) + _days(monday - timedelta(weeks=1), 7, lambda i: 50) \
        + _days(monday, 2, lambda i: 60)
    out = [((monday - timedelta(weeks=1)).isoformat(), False)] * 5
    w = insights._weeks_of(days, out, today)
    last = w["weeks"][-2]
    assert last["short_views"] == 350 and last["change"]["short_views"] == 400
    assert last["per_short"] == 70
    assert w["weeks"][-1]["partial"] and w["weeks"][-1]["change"]["short_views"] is None
    assert w["so_far"]["days"] == 2 and w["so_far"]["now"]["short_views"] == 120
    assert w["so_far"]["then"]["short_views"] == 100 and w["so_far"]["change"]["short_views"] == 20


def test_what_went_out_and_what_goes_out_next(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "SEEN_PATH", tmp_path / "seen.json")
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    assert digest.since(now) == datetime(2026, 10, 27, tzinfo=timezone.utc)   # yesterday, until cleared
    digest.clear(now)
    assert digest.since(now) == now
    video = tmp_path / "out" / "a.mp4"
    video.parent.mkdir()
    video.write_bytes(b"")
    from core import gallery
    monkeypatch.setattr(gallery, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(gallery, "resolve_output_dir", lambda d: tmp_path / "out")
    monkeypatch.setattr(gallery, "load_publish_info", lambda p: {
        "discarded": False, "title": "A Title", "published_at": "2026-10-28T13:00:00+00:00",
        "youtube_url": "https://youtu.be/x", "handoff": {"tiktok": {"posted_at": "2026-10-27T09:00:00+00:00"}}})
    channel = SimpleNamespace(channel_display_name="Why", output_dir="out", format="documentary")
    rows = digest.went_out({"why": channel}, now)
    assert len(rows) == 1 and rows[0]["places"] == [("YouTube", "https://youtu.be/x")]   # TikTok was before
    assert rows[0]["kind"] == "teaser"
    monkeypatch.setattr("core.publish_queue.in_order", lambda c: [
        (video, now + timedelta(hours=3)), (video, now + timedelta(days=1)), (video, now + timedelta(days=3))])
    coming = digest.going_out({"why": channel}, now)
    assert [r["day"] for r in coming] == ["Today", "Tomorrow"]


def test_channels_not_publishing_yet_are_left_out_unless_asked_for():
    from web import create_app, focus
    channels = {"live": SimpleNamespace(archived=False, publishing=SimpleNamespace(enabled=True)),
                "test": SimpleNamespace(archived=False, publishing=SimpleNamespace(enabled=False)),
                "old": SimpleNamespace(archived=True, publishing=SimpleNamespace(enabled=False))}
    app = create_app()
    with app.test_request_context("/"):
        assert list(focus.visible(channels)) == ["live"]
    with app.test_request_context("/", headers={"Cookie": f"{focus.TESTS_COOKIE}=1"}):
        assert list(focus.visible(channels)) == ["live", "test"]
