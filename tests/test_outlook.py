"""
The Outlook page and the owner's other asks of 16 October (decision 107):
when the Partner Programme is reached and whether it's before the bar
rises, when a channel pays its way, Money narrowed to the chosen
channel, the channel page's queue in the order it goes out, and Insights
counting teasers with their film.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as N

from core import money, outlook, publish_queue

TODAY = date(2026, 10, 16)


def test_reaching_the_partner_programme_before_and_after_the_bar_rises():
    early = outlook.partner(hours=3000, subs=900, hours_pace=20, subs_pace=5, today=TODAY)
    assert early["before_change"] and early["date"] == TODAY + timedelta(days=50)
    late = outlook.partner(hours=100, subs=900, hours_pace=10, subs_pace=5, today=TODAY)
    assert not late["before_change"] and late["rule"] == money.YPP_AFTER   # 4,000 isn't made in time
    assert late["date"] == TODAY + timedelta(days=790)                   # 7,900 hours at 10 a day
    stalled = outlook.partner(hours=1, subs=5, hours_pace=0, subs_pace=0.3, today=TODAY)
    assert stalled["date"] is None and stalled["hours_a_day_needed"] > 30


def test_payback_waits_for_the_programme_and_grows_with_views():
    pay = outlook.payback(spent=30, monthly=30.4, views_a_day=500, growth=0, rpm=4.0,
                          from_day=TODAY + timedelta(days=10), today=TODAY)
    assert pay["pays_its_way"] == TODAY + timedelta(days=10)             # $2 a day earned against $1
    assert pay["all_back"] > pay["pays_its_way"]
    never = outlook.payback(spent=30, monthly=30.4, views_a_day=0, growth=0, rpm=4.0,
                            from_day=None, today=TODAY)
    assert never["pays_its_way"] is None and never["all_back"] is None


def test_the_picture_from_day_by_day_figures(monkeypatch):
    days = [{"day": (TODAY - timedelta(days=n)).isoformat(), "long_views": 10, "long_minutes": 120,
             "short_views": 1000, "subs_net": 2} for n in range(30, 0, -1)]
    monkeypatch.setattr("core.audience.status", lambda: {"why": {"subscribers": 100}})
    monkeypatch.setattr(outlook, "_spend_by_day", lambda key: [("2026-10-01", 5.0)])
    forecast = {"rows": [{"key": "why", "monthly": 20.0, "shorts": 1, "longs": 1}], "views": {}, "ypp": {},
                "settings": {"elevenlabs_monthly_usd": 0, "long_rpm": 4.0, "shorts_rpm": 0, "in_ypp": []}}
    monkeypatch.setattr("core.voice_quota.typical_video_credits", lambda key: 1)
    p = outlook.picture(N(key="why", channel_display_name="Why"), forecast, today=TODAY,
                        figures={"days": days, "fetched_at": 1})
    assert p["subs"] == 100 and p["hours"] == 60.0 and abs(p["hours_pace"] - 2) < 1e-9
    assert p["charts"]["subs"]["series"][0]["points"][0][1] == 42      # counted back from today's 100
    assert p["long_per_1000_shorts"] == 10.0
    assert p["ypp"]["date"] is None                                    # 8,000 h at 2 a day: past the horizon


def test_money_narrowed_to_one_channel(monkeypatch):
    monkeypatch.setattr("core.voice_quota.typical_video_credits", lambda key: 1)
    f = {"rows": [{"key": "a", "monthly": 10.0, "shorts": 3, "longs": 0},
                  {"key": "b", "monthly": 30.0, "shorts": 1, "longs": 0}],
         "views": {"a": {"long_views_30d": 0, "shorts_views_30d": 0}, "b": {"long_views_30d": 0, "shorts_views_30d": 0}},
         "ypp": {"a": 1, "b": 2}, "settings": {"elevenlabs_monthly_usd": 20, "long_rpm": 4, "shorts_rpm": 0, "in_ypp": []},
         "monthly": 60.0}
    a = money.for_channel(f, "a")
    assert a["monthly"] == 10 + 15 and list(a["ypp"]) == ["a"] and [r["key"] for r in a["rows"]] == ["a"]


def test_the_channel_queue_is_in_the_order_it_goes_out(monkeypatch):
    t = lambda d, h: datetime(2026, 10, d, h, tzinfo=timezone.utc)
    monkeypatch.setattr(publish_queue, "schedule_for", lambda channel, now=None: [
        ("short1", t(17, 18)), ("short2", t(18, 18)), ("long1", t(17, 16)), ("later", None)])
    assert [p for p, _ in publish_queue.in_order(None)] == ["long1", "short1", "short2", "later"]


def test_insights_counts_a_teaser_with_its_film(monkeypatch):
    from core import insights
    film = {"title": "Film", "channel_name": "Why", "channel_key": "why", "relpath": "why/longform/d/film.mp4",
            "published": True, "links": {"published_at": "2026-10-14"}, "report": {},
            "stats": {"views": 40, "avg_view_seconds": 300, "avg_view_percent": 30}}
    teaser = {"title": "Teaser", "channel_name": "Why", "channel_key": "why", "relpath": "why/d/t.mp4",
              "published": True, "links": {"published_at": "2026-10-15"},
              "report": {"teaser": True, "teaser_of_video": "longform/d/film.mp4"},
              "stats": {"views": 900, "avg_view_percent": 70}}
    other = dict(teaser, title="Quiz", relpath="why/d/q.mp4", report={})
    a = insights._audience([film, teaser, other])
    assert [r["name"] for r in a["longs"]] == ["Film"] and a["longs"][0]["teaser_views"] == 900
    assert [r["name"] for r in a["shorts"]] == ["Quiz"]
    assert abs(a["long_hours"] - 40 * 300 / 3600) < 1e-9


def test_renaming_a_channel_carries_its_outlook_figures(tmp_path, monkeypatch):
    from core import channel_data
    monkeypatch.setattr(outlook, "_cache_path", lambda key: tmp_path / f"{key}.json")
    (tmp_path / "old.json").write_text("{}")
    problems = []
    channel_data._move(outlook._cache_path("old"), outlook._cache_path("new"), problems, "outlook figures")
    assert (tmp_path / "new.json").exists() and not problems
    assert "outlook figures" in open("core/channel_data.py", encoding="utf-8").read()
