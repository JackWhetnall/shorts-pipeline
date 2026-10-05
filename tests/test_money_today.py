"""
The Money page's arithmetic (core.money) and Today's list of what needs
the owner (core.today), decision 067. The owner asked for both: no
overview of what the system does by itself, no projected costs, no
warning before the Claude credit or the voice allowance ran out, and
unfinished channels forgotten.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from core import money, today
from core.channels import ChannelConfig

NOW = datetime(2026, 10, 5, 12, 0).timestamp()
DAY = 86400


def _rec(service, cost, days_ago=0, job="", channel="", operation="op"):
    return {"service": service, "cost_usd": cost, "ts": NOW - days_ago * DAY, "job_id": job,
            "channel_key": channel, "operation": operation}


def test_spend_is_split_by_account_and_window():
    records = [_rec("claude", 1.0, 1), _rec("claude", 2.0, 10), _rec("claude", 4.0, 40),
               _rec("openai-image", 0.5, 2), _rec("elevenlabs", 9.0, 1)]
    out = money.spend(records, NOW)
    assert out["anthropic"] == {"7d": 1.0, "30d": 3.0, "all": 7.0}
    assert out["openai"]["all"] == 0.5
    assert "elevenlabs" not in out                       # a subscription, not metered here


def test_a_channels_cost_per_video_is_its_recent_median_without_the_voice():
    records = []
    for i, cost in enumerate([0.10, 0.20, 0.30, 5.00]):
        records += [_rec("claude", cost, 20 - i, job=f"j{i}", channel="pub"),
                    _rec("elevenlabs", 1.0, 20 - i, job=f"j{i}", channel="pub")]
    assert money.cost_per_video(records, "pub") == pytest.approx(0.25)
    assert money.cost_per_video(records, "other") == 0.0


def test_videos_a_month_follow_the_publishing_plan():
    channel = ChannelConfig(key="mp")
    assert money.shorts_per_month(channel) == 0.0       # not publishing
    channel.publishing.enabled = True
    channel.publishing.weekdays = [0, 2, 4, 6]
    assert money.shorts_per_month(channel) == pytest.approx(4 * money.MONTH_DAYS / 7)
    quiz = ChannelConfig(key="pqb", format="quiz")
    quiz.publishing.enabled = True
    assert money.longs_per_month(quiz) == pytest.approx(money.MONTH_DAYS / 7)       # Sat 19:00


def test_the_balance_is_what_was_loaded_less_what_was_spent_since():
    saved = {**money.DEFAULTS, "balances": {"anthropic": {"usd": 40.0, "at": 0}}}
    records = [_rec("claude", 30.0, 20), _rec("claude", 6.0, 1), _rec("openai-image", 3.0, 1)]
    assert money.balance("anthropic", records, saved) == pytest.approx(4.0)
    assert money.balance("openai", records, saved) is None            # never entered
    # A top-up entered today: only spend from now on comes off it.
    saved["balances"]["anthropic"] = {"usd": 50.0, "at": NOW - 0.5 * DAY}
    assert money.balance("anthropic", records, saved) == pytest.approx(50.0)
    left = money.runway(4.0, 0.5, NOW)
    assert round(left["days"]) == 8 and left["until"] == date(2026, 10, 13)


def test_a_set_balance_is_saved_and_read_back():
    money.set_balance("anthropic", 25, now=NOW)
    assert money.settings()["balances"]["anthropic"] == {"usd": 25.0, "at": NOW}


def test_the_voice_pace_is_the_counters_last_week_not_its_monthly_average():
    """Regression: the cycle average said 390 characters a day; the counter
    had gone from 4,381 on 30 Sep to 11,061 on 5 Oct, about 1,340."""
    history = {"2026-09-30": 4381, "2026-10-05": 11061}
    assert money.voice_pace(history, NOW) == pytest.approx(1336, abs=1)
    # A reset in between: only readings since it count.
    assert money.voice_pace({"2026-09-28": 29000, "2026-10-01": 500, "2026-10-05": 4500}, NOW) == 1000
    quota = SimpleNamespace(used=11061, limit=30000, remaining=18939,
                            resets_at=datetime(2026, 10, 7).timestamp())
    v = money.voice(quota, NOW, history)
    assert v["runs_out"] is None                         # lasts the two days to its reset
    assert v["month_need"] > v["limit"]                  # but a month at this pace doesn't fit


def test_the_voice_runs_out_before_its_reset_and_says_how_long_its_dry():
    quota = SimpleNamespace(used=25000, limit=30000, remaining=5000,
                            resets_at=datetime(2026, 10, 20).timestamp())
    v = money.voice(quota, NOW, {"2026-09-28": 18000, "2026-10-05": 25000})
    assert v["runs_out"] == date(2026, 10, 10) and v["dry_days"] == 9


def test_the_partner_programme_pace_is_against_the_old_bar_before_february():
    row = {"hours": 1000.0, "shorts_views_90d": 5, "subscribers": 120}
    y = money.ypp(row, date(2026, 10, 5))
    assert y["rule"] == money.YPP_BEFORE and y["days_to_change"] == 119
    assert y["hours_per_day_needed"] == pytest.approx(3000 / 119)
    assert money.ypp(row, date(2027, 3, 1))["rule"] == money.YPP_AFTER


def test_payback_counts_only_channels_in_the_programme():
    saved = {**money.DEFAULTS, "long_rpm": 4.0, "in_ypp": ["a"]}
    views = {"a": {"long_views_30d": 5000, "shorts_views_30d": 0},
             "b": {"long_views_30d": 5000, "shorts_views_30d": 0}}
    p = money.payback(30.0, saved, views)
    assert p["earning"] == pytest.approx(20.0) and p["would_earn"] == pytest.approx(40.0)
    assert p["views_needed"] == pytest.approx(7500)


# --- Today ---------------------------------------------------------------------------

def _url_for(endpoint, **kwargs):
    return f"/{endpoint}/" + "/".join(str(v) for v in kwargs.values())


@pytest.fixture
def quiet(monkeypatch):
    """Every source empty unless a test fills one."""
    from core import drafts, gallery, jobs, youtube
    monkeypatch.setattr(youtube, "connection", lambda key: {"connected": True, "stats": True, "expired": False})
    monkeypatch.setattr(gallery, "video_state_counts", lambda *a, **k: {
        "waiting": 0, "queued": 0, "published": 1, "active": 1, "unpublished": 0, "discarded": 0, "total": 1})
    monkeypatch.setattr(jobs, "latest_failed_for_channel", lambda key: None)
    monkeypatch.setattr(drafts, "all_drafts", lambda: [])
    monkeypatch.setattr("core.launch.stages", lambda channel, state=None: ([], []))


def test_a_dead_youtube_connection_comes_first(quiet, monkeypatch):
    """Regression: Minute Pastor's connection died around 1 Oct and the
    only sign was a line on Insights."""
    from core import drafts, youtube
    channel = ChannelConfig(key="mp", channel_display_name="Minute Pastor")
    monkeypatch.setattr(youtube, "connection", lambda key: {"connected": True, "stats": True, "expired": True})
    monkeypatch.setattr(drafts, "all_drafts", lambda: [{"id": "d1", "created_at": NOW - 10 * DAY,
                                                         "channel": {"name_options": ["Second Look Maths"]}}])
    items = today.needs_you({"mp": channel}, _url_for, now=NOW)
    assert items[0].severity == today.BAD and "can't upload" in items[0].title
    assert items[0].action == "Reconnect" and items[0].outside
    assert any("Second Look Maths" in i.title for i in items)


def test_a_stalled_setup_says_how_long_and_offers_to_archive(quiet, monkeypatch):
    from core import gallery, launch
    channel = ChannelConfig(key="wren", channel_display_name="Wren's Guide")
    stage = launch.Stage("sample", "Make and approve a first video", "you", done=False)
    monkeypatch.setattr("core.launch.stages", lambda c, state=None: ([launch.Stage("content", "x", "you", True), stage], []))
    monkeypatch.setattr(gallery, "video_state_counts", lambda *a, **k: {
        "waiting": 0, "queued": 0, "published": 0, "active": 1, "unpublished": 1, "discarded": 0, "total": 1})
    monkeypatch.setattr(gallery, "latest_video_mtime", lambda d: NOW - 12 * DAY)
    item = next(i for i in today.needs_you({"wren": channel}, _url_for, now=NOW) if "setting up" in i.title)
    assert "12 days" in item.detail and item.action == "Resume"
    assert [label for label, _, post in item.extra if post] == ["Archive"]


def test_money_running_short_is_said_in_time(quiet):
    forecast = {"claude_balance": 3.5, "claude": {"days": 2.0}, "voice": None}
    items = today.needs_you({}, _url_for, now=NOW, forecast=forecast)
    assert items[0].severity == today.BAD and "$3.50 left" in items[0].title
    v = {"limit": 30000, "per_day": 1336.0, "month_need": 40614, "runs_out": None}
    items = today.needs_you({}, _url_for, now=NOW, forecast={"claude_balance": 30, "claude": {"days": 60},
                                                            "voice": v})
    assert any("won't cover a month" in i.title for i in items)


def test_a_source_that_fails_is_reported_not_hidden(quiet, monkeypatch):
    from core import jobs

    def broken(key):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(jobs, "latest_failed_for_channel", broken)
    items = today.needs_you({"mp": ChannelConfig(key="mp")}, _url_for, now=NOW)
    assert any(i.title == "Couldn't check failed videos" for i in items)


def test_the_schedule_reads_like_a_person_would_say_it():
    plan = ChannelConfig(key="x").publishing
    assert today.schedule_label(plan) == "Off"
    plan.enabled = True
    assert today.schedule_label(plan) == "Daily 18:00"
    plan.weekdays, plan.slots = [0, 2, 4, 6], ["11:00"]
    assert today.schedule_label(plan) == "Mon Wed Fri Sun 11:00"


def test_today_and_money_render(monkeypatch, tmp_path):
    from core.channels import channel_to_sparse_dict, write_raw
    from tests.test_web import csrf
    from web import create_app
    path = tmp_path / "channels.json"
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
    channel = ChannelConfig(key="pub", format="quiz", style_prompt="host", voice="21m00Tcm4TlvDq8ikWAM")
    channel.publishing.enabled = True
    write_raw({"pub": channel_to_sparse_dict(channel)}, path)
    client = create_app().test_client()
    page = client.get("/").get_data(as_text=True)
    assert "Needs you" in page and "Running by itself" in page and "Tell the app your Claude balance" in page
    assert client.get("/money").status_code == 200
    client.post("/money/balance", data={"csrf_token": csrf(client), "provider": "anthropic", "usd": "40"})
    assert "$40.00 left" in client.get("/money").get_data(as_text=True)
    assert client.get("/channels").status_code == 200
