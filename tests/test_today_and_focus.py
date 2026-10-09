"""
Today's failed videos, and looking at one channel in a browser (decision 080).

The owner: "A Minute Pastor video didn't finish" with a "See it" button
that went to Activity, where the video was long gone, with nothing about
why, whether it was remade, and no way to clear it. And, keeping a
browser profile per channel, a channel switcher that filters Review and
To post, with counts on the menu that keep up.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from core import today


def test_a_failure_says_what_when_and_what_it_was_doing(monkeypatch):
    from core import jobs
    monkeypatch.setattr(jobs, "read_log", lambda job_id, tail=40: [
        "[3/5] Matching footage...", "  [footage] scoring", "[4/5] Preparing 16 background clip(s)..."])
    now = time.time()
    job = {"id": "j", "status": "error", "finished_at": now - 3 * 86400,
           "error": "Something went wrong while generating this video. The technical details are in the log below.",
           "seed": {"reference": "2 Kings 2:16"}}
    detail = today.failure_detail(job, now)
    assert detail.startswith("2 Kings 2:16, ") and "(3 days ago)" in detail
    assert "stopped while preparing 16 background clip(s)" in detail
    assert "Something went wrong" not in detail and "Retry" in detail and "Discard" in detail
    job["error"] = "The voice allowance has run out."
    assert "The voice allowance has run out." in today.failure_detail(job, now)


def test_a_failure_has_retry_and_discard_and_clears_once_made_since(monkeypatch, tmp_path):
    from core import gallery, jobs
    channel = SimpleNamespace(archived=False, channel_display_name="Minute Pastor", output_dir="mp")
    job = {"id": "j1", "status": "error", "finished_at": 100.0, "error": "x", "seed": {"reference": "2 Kings 2:16"}}
    monkeypatch.setattr(jobs, "latest_failed_for_channel", lambda key: job)
    monkeypatch.setattr(jobs, "read_log", lambda job_id, tail=40: [])
    dismissed = []
    monkeypatch.setattr(jobs, "dismiss_job", lambda job_id: dismissed.append(job_id))
    monkeypatch.setattr(gallery, "resolve_output_dir", lambda d: tmp_path)
    url_for = lambda endpoint, **kw: f"/{endpoint}/{kw.get('job_id', '')}"
    items = today._failed({"minute_pastor": channel}, url_for, time.time(), None)
    assert items[0].action == "Retry" and items[0].post and items[0].url == "/today.retry/j1"
    assert items[0].extra == [("Discard", "/today.dismiss/j1", True)]
    (tmp_path / "2026-10-07").mkdir()
    (tmp_path / "2026-10-07" / "2_kings_2_16.mp4").write_bytes(b"x")
    assert today._failed({"minute_pastor": channel}, url_for, time.time(), None) == []
    assert dismissed == ["j1"]


@pytest.fixture
def client(monkeypatch):
    from web import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _token(client):
    html = client.get("/").get_data(as_text=True)
    marker = 'name="csrf-token" content="'
    start = html.index(marker) + len(marker)
    return html[start:html.index('"', start)]


def test_the_focus_is_this_browsers_and_filters_review_and_the_counts(client, monkeypatch):
    from core.channels import load_channels
    channels = load_channels(validate=False)
    key = next(iter(channels))
    token = _token(client)
    response = client.post("/focus", data={"channel": key, "next": "/review", "csrf_token": token})
    assert response.status_code == 302 and response.headers["Location"].endswith("/review")
    assert f"focus_channel={key}" in response.headers.get("Set-Cookie", "")
    html = client.get("/review").get_data(as_text=True)
    assert ">Channel<" in html and f"/channels/{key}" in html
    assert set(client.get("/api/nav-counts").get_json()) == {"review_waiting", "to_post", "active_job_count"}
    # "All" clears it; somewhere outside the app is never where it sends you.
    response = client.post("/focus", data={"channel": "", "next": "//evil.example", "csrf_token": token})
    assert response.headers["Location"].endswith("/") and "focus_channel=;" in response.headers.get("Set-Cookie", "")


def test_rows_are_kept_for_the_focused_channel_only(client):
    from web import focus
    rows = [{"channel_key": "a"}, {"channel_key": "b"}]
    with client.application.test_request_context(headers={"Cookie": "focus_channel=a"}):
        assert focus.keep(rows, channels={"a": 1, "b": 2}) == [{"channel_key": "a"}]
    with client.application.test_request_context(headers={"Cookie": "focus_channel=gone"}):
        assert focus.keep(rows, channels={"a": 1, "b": 2}) == rows
