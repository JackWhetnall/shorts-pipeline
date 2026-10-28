"""
Decision 141. The owner, 28 Oct: notified on the phone "whenever a video
gets posted, and other updates/breakdowns of things", and told what to do
when a teaser goes out and its film must be linked; and a channel whose
teasers are copied to the phone by itself, "JUST FOR THIS CHANNEL", still
postable from the laptop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from core import notify, posting


def _channel(**publishing):
    return SimpleNamespace(key="why", channel_display_name="Why, Though?", archived=False, format="documentary",
                           output_dir="out", documentary=SimpleNamespace(teasers_linked=True),
                           publishing=SimpleNamespace(enabled=True, **publishing))


def test_nothing_is_sent_without_a_topic(monkeypatch):
    sent = []
    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: sent.append(a))
    assert notify.send("t", "m") is False and not sent


def test_a_teaser_out_says_to_link_its_film_in_studio(monkeypatch, tmp_path):
    from core import gallery, publish_queue
    film = tmp_path / "film.mp4"
    film.write_bytes(b"")
    monkeypatch.setattr(publish_queue, "film_of_teaser", lambda channel, path: film)
    monkeypatch.setattr(gallery, "load_publish_info", lambda path: {"title": "The Full Film",
                                                                    "youtube_url": "https://youtu.be/F"})
    row = {"name": "Why, Though?", "title": "A Teaser", "kind": "teaser", "relpath": "out/t.mp4",
           "places": [("YouTube", "https://www.youtube.com/watch?v=abc123")]}
    title, message, click = notify.out_message(_channel(), row)
    assert "link its film" in title and 'Related video to "The Full Film"' in message
    assert click == "https://studio.youtube.com/video/abc123/edit"


def test_the_first_run_only_marks_what_is_there_then_new_things_are_sent(monkeypatch):
    notify.save("yt-test-topic", "https://ntfy.sh", {"out": True, "needs": True, "daily": True, "weekly": True})
    posts = []
    monkeypatch.setattr(notify.requests, "post",
                        lambda url, data=None, headers=None, timeout=None: posts.append((url, headers["Title"]))
                        or SimpleNamespace(ok=True, status_code=200))
    rows = [{"channel": "why", "name": "Why, Though?", "title": "Old", "kind": "long", "relpath": "a.mp4",
             "when": datetime(2026, 10, 28, 9, tzinfo=timezone.utc), "places": [("YouTube", "https://youtu.be/a")]}]
    monkeypatch.setattr("core.digest.went_out", lambda channels, after: list(rows))
    monkeypatch.setattr("core.today.needs_you", lambda channels, url_for: [])
    monkeypatch.setattr(notify, "daily_message", lambda channels: "summary")
    monkeypatch.setattr(notify, "_app_link", lambda path="/m": "")
    channels = {"why": _channel()}
    morning = datetime(2026, 10, 28, 9, tzinfo=timezone.utc)
    assert notify.tick(channels, morning) == [] and posts == []      # first run: nothing old arrives
    rows.append({**rows[0], "title": "New", "relpath": "b.mp4"})
    sent = notify.tick(channels, morning)
    assert [t for t in sent] == ["Why, Though?: out on YouTube"]
    assert posts[0][0] == "https://ntfy.sh/yt-test-topic"
    assert notify.tick(channels, morning) == []                       # each once
    next_day = datetime(2026, 10, 29, 8, 5, tzinfo=timezone.utc)
    assert "daily" in notify.tick(channels, next_day)


def test_a_channel_can_copy_each_video_to_the_phone_and_the_pc_copy_stays(tmp_path, monkeypatch):
    from core import gallery
    video = tmp_path / "out" / "t.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    gallery.save_publish_info(video, {"title": "A Teaser"})
    staged = posting.stage(_channel(), video)
    copy = posting.to_phone(_channel(), video)
    posting.off_phone(video)                                          # clicked again: only the phone copy goes
    assert staged.exists() and not copy.exists() and not posting.on_phone(video)
