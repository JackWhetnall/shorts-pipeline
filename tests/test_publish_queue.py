"""
The publishing queue and the scheduler that feeds it.

What matters: a video goes out once per slot and never twice; a missed
slot is made up once, not in a burst; a failed upload goes back to review
rather than vanishing or being marked published; a video due on TikTok or
Instagram is listed to post and leaves the review queue; and the
generator keeps a buffer without burying the review queue.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import gallery, publish_queue, scheduler
from core.channels import ChannelConfig
from core.errors import ExternalServiceError


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi).astimezone()


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    monkeypatch.setattr(publish_queue, "STATE_PATH", tmp_path / "state.json")
    channel = ChannelConfig(key="c", channel_display_name="Chan", voice="21m00Tcm4TlvDq8ikWAM",
                            style_prompt="x", topics=["t"])
    channel.output_dir = str(tmp_path / "out" / "c")
    channel.publishing.enabled = True
    channel.publishing.slots = ["18:00"]
    monkeypatch.setattr(gallery, "_channel_key_for", lambda path: "c")
    monkeypatch.setattr("core.channels.load_channels", lambda validate=True: {"c": channel})

    state = {"connected": True, "fail": False, "locked": False, "uploads": []}

    def upload(key, path, title, description, **kwargs):
        state["uploads"].append(title)
        if state["fail"]:
            raise ExternalServiceError("YouTube", "boom", user_message="YouTube said no.")
        return {"url": f"https://www.youtube.com/watch?v={len(state['uploads']):011d}",
                "locked_private": state["locked"]}

    monkeypatch.setattr(publish_queue.youtube, "connection", lambda key: {"connected": state["connected"]})
    monkeypatch.setattr(publish_queue.youtube, "upload", upload)

    def video(name, queued=True):
        path = Path(channel.output_dir) / "2026-09-24" / f"{name}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
        gallery.save_title_and_description(path, f"Title {name}", f"About {name}")
        if queued:
            publish_queue.enqueue(path, approved_by="you")
        return path

    return SimpleNamespace(channel=channel, video=video, state=state, tmp=tmp_path)


class TestSlots:
    def test_upcoming_slots_respect_days_and_times(self):
        plan = SimpleNamespace(slots=["09:00", "18:00"], weekdays=[0, 2])  # Mon, Wed
        # Wed 23 Sep 2026, 10:00 -> Wed 18:00, Mon 09:00, Mon 18:00
        slots = publish_queue.upcoming_slots(plan, local(2026, 9, 23, 10), 3)
        assert [(s.weekday(), s.hour) for s in slots] == [(2, 18), (0, 9), (0, 18)]

    def test_latest_slot_looks_back_across_days(self):
        plan = SimpleNamespace(slots=["18:00"], weekdays=[0, 1, 2, 3, 4, 5, 6])
        assert publish_queue.latest_slot(plan, local(2026, 9, 24, 17)).day == 23
        assert publish_queue.latest_slot(plan, local(2026, 9, 24, 19)).day == 24


class TestPublishing:
    def test_one_video_per_slot_never_twice(self, world):
        first, second = world.video("a"), world.video("b")
        at = local(2026, 9, 24, 18, 5)
        assert len(publish_queue.publish_due({"c": world.channel}, now=at)) == 1
        assert publish_queue.publish_due({"c": world.channel}, now=at + timedelta(minutes=5)) == []
        assert gallery.load_publish_info(first)["youtube_url"]
        assert not gallery.load_publish_info(second)["youtube_url"]
        # The next day's slot takes the next one.
        publish_queue.publish_due({"c": world.channel}, now=at + timedelta(days=1))
        assert gallery.load_publish_info(second)["youtube_url"]

    def test_a_missed_slot_is_made_up_once_and_not_after_a_long_gap(self, world):
        world.video("a"), world.video("b")
        # Off for most of a day: the 18:00 slot is made up at 09:00.
        assert len(publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 25, 9))) == 1
        assert publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 25, 9, 10)) == []

    def test_without_a_plan_it_goes_out_on_the_next_check(self, world):
        world.channel.publishing.enabled = False
        path = world.video("a")
        assert publish_queue.schedule_for(world.channel)[0][1] is None
        publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 3))
        assert gallery.load_publish_info(path)["youtube_url"]

    def test_a_failed_upload_goes_back_to_review_unpublished(self, world):
        path = world.video("a")
        world.state["fail"] = True
        results = publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 18, 1))
        info = gallery.load_publish_info(path)
        assert "upload failed" in results[0]
        assert not info["queued_at"] and not gallery.is_out(info)
        assert "back in review" in gallery.load_report(path)["autopilot"]["message"]
        # And nothing was handed off for TikTok on the strength of it.
        assert not info["handoff"]

    def test_posting_by_hand_lists_it_to_post_and_leaves_review(self, world):
        world.state["connected"] = False
        world.channel.publishing.post_tiktok = True
        world.channel.publishing.post_instagram = True
        path = world.video("a")
        publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 18, 1))

        info = gallery.load_publish_info(path)
        assert gallery.is_out(info) and not gallery.is_queued(info)
        waiting = publish_queue.awaiting_posts({"c": world.channel})
        assert waiting[0]["platforms"] == ["tiktok", "instagram"]

        publish_queue.mark_posted(path, "tiktok", "https://www.tiktok.com/@x/video/1")
        assert gallery.load_publish_info(path)["tiktok_url"]
        assert publish_queue.awaiting_posts({"c": world.channel})[0]["platforms"] == ["instagram"]
        publish_queue.mark_posted(path, "instagram")
        assert publish_queue.awaiting_posts({"c": world.channel}) == []

    def test_discarding_takes_a_video_out_of_the_queue(self, world):
        path = world.video("a")
        gallery.set_discarded(path, True, "script")
        assert publish_queue.queued(world.channel) == []


class TestGeneration:
    def test_fills_up_to_the_buffer_then_stops(self, world, monkeypatch):
        monkeypatch.setattr(scheduler.voice_quota, "has_room_for", lambda n: True)
        block = lambda **state: scheduler.generation_block(
            "c", world.channel, state={"queued": 0, "waiting": 0, **state}, active={})
        assert block() is None
        assert "queued" in block(queued=3)
        assert "waiting for a look" in block(waiting=3)
        world.channel.publishing.enabled = False
        assert "off" in block()

    def test_one_held_video_does_not_stop_the_channel(self, world, monkeypatch):
        monkeypatch.setattr(scheduler.voice_quota, "has_room_for", lambda n: True)
        assert scheduler.generation_block(
            "c", world.channel, state={"queued": 1, "waiting": 1}, active={}) is None
