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

    state = {"connected": True, "fail": False, "fail_status": None, "fail_times": 0,
             "locked": False, "uploads": []}

    def upload(key, path, title, description, **kwargs):
        state["uploads"].append(title)
        if state["fail_times"]:
            state["fail_times"] -= 1
            raise ExternalServiceError("YouTube", "500 Internal error encountered.",
                                       user_message="YouTube wouldn't start the upload (HTTP 500).",
                                       status=state["fail_status"])
        if state["fail"]:
            raise ExternalServiceError("YouTube", "boom", user_message="YouTube said no.",
                                       status=state["fail_status"])
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

    def test_moving_the_time_later_the_same_day_doesnt_send_a_second_video(self, world):
        # Decision 101: 16:00 went out, the time was moved to 16:30, and a
        # second video went out at 16:36 as if 16:30 were a new slot.
        first, second = world.video("a"), world.video("b")
        assert len(publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 18, 5))) == 1
        world.channel.publishing.slots = ["18:30"]
        assert publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 18, 36)) == []
        assert [w for _, w in publish_queue.schedule_for(world.channel, now=local(2026, 9, 24, 18, 36))]             == [local(2026, 9, 25, 18, 30)]
        publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 25, 18, 31))
        assert gallery.load_publish_info(second)["youtube_url"]

    def test_a_video_being_sent_says_so_instead_of_moving_to_the_next_slot(self, world, monkeypatch):
        # Decision 102: at 16:01 the page showed the video going out Friday
        # while it was uploading for Wednesday's slot.
        first, second = world.video("a"), world.video("b")
        at = local(2026, 9, 24, 18, 1)
        seen = []

        def uploading(channel, path, **kw):
            seen.append(publish_queue.schedule_for(world.channel, now=at))
            return {"title": "A", "messages": []}
        monkeypatch.setattr(publish_queue, "put_out", uploading)
        publish_queue.publish_due({"c": world.channel}, now=at)
        (path, when), (_, next_when) = seen[0]
        assert Path(path).name == "a.mp4" and publish_queue.slot_text(when) == "Uploading now"
        assert next_when == local(2026, 9, 25, 18, 0)
        assert publish_queue._sending == {}
        assert publish_queue.slot_text(at - timedelta(minutes=1), now=at) == "Going out now"

    def test_a_missed_slot_is_made_up_once_and_not_after_a_long_gap(self, world):
        world.video("a"), world.video("b")
        # Off for most of a day: the 18:00 slot is made up at 09:00.
        assert len(publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 25, 9))) == 1
        assert publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 25, 9, 10)) == []

    def test_with_the_plan_on_and_no_times_it_goes_out_on_the_next_check(self, world):
        world.channel.publishing.slots = []
        path = world.video("a")
        assert publish_queue.schedule_for(world.channel)[0][1] is None
        publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 3))
        assert gallery.load_publish_info(path)["youtube_url"]

    def test_with_the_plan_off_an_approved_video_waits_approved(self, world):
        """Regression: with the plan off an approved video was sent at once,
        found nowhere to go and was put back in review."""
        world.channel.publishing.enabled = False
        path = world.video("a")
        assert publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 18, 1)) == []
        info = gallery.load_publish_info(path)
        assert info["queued_at"] and not gallery.is_out(info)

    def test_with_nowhere_to_publish_it_stays_approved(self, world):
        world.state["connected"] = False
        path = world.video("a")
        assert publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 18, 1)) == []
        assert gallery.load_publish_info(path)["queued_at"]

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

    def test_a_temporary_youtube_failure_is_tried_again_not_sent_back(self, world):
        """Regression (decision 077): on 6 Oct a single "500 Internal error
        encountered" sent Pub Quiz Buzz's approved video back to review and
        its slot went by."""
        path = world.video("a")
        world.state.update(fail_status=500, fail_times=2)
        at = local(2026, 9, 24, 18, 1)
        for minutes in (0, 5):
            results = publish_queue.publish_due({"c": world.channel}, now=at + timedelta(minutes=minutes))
            assert "trying again" in results[0]
            assert gallery.load_publish_info(path)["queued_at"]           # still queued
        publish_queue.publish_due({"c": world.channel}, now=at + timedelta(minutes=10))
        assert gallery.load_publish_info(path)["youtube_url"]
        assert len(world.state["uploads"]) == 3
        # And the slot is used once: nothing more goes out until the next one.
        world.video("b")
        assert publish_queue.publish_due({"c": world.channel}, now=at + timedelta(minutes=15)) == []

    def test_a_temporary_failure_that_lasts_goes_back_to_review_in_the_end(self, world):
        path = world.video("a")
        world.state.update(fail=True, fail_status=503)
        at = local(2026, 9, 24, 18, 1)
        results = [publish_queue.publish_due({"c": world.channel}, now=at + timedelta(minutes=5 * i))
                   for i in range(publish_queue.RETRY_TRIES)]
        assert all("trying again" in r[0] for r in results[:-1]) and "upload failed" in results[-1][0]
        assert not gallery.load_publish_info(path)["queued_at"]

    def test_a_refusal_goes_back_to_review_at_once(self, world):
        path = world.video("a")
        world.state.update(fail=True, fail_status=403)
        results = publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 18, 1))
        assert "upload failed" in results[0] and not gallery.load_publish_info(path)["queued_at"]

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
        monkeypatch.setattr(scheduler.voice_quota, "has_room_for", lambda n, **k: True)
        block = lambda **state: scheduler.generation_block(
            "c", world.channel, state={"queued": 0, "waiting": 0, **state}, active={})
        assert block() is None
        assert "queued" in block(queued=3)
        assert "waiting for a look" in block(waiting=3)
        world.channel.publishing.enabled = False
        assert "off" in block()

    def test_one_held_video_does_not_stop_the_channel(self, world, monkeypatch):
        monkeypatch.setattr(scheduler.voice_quota, "has_room_for", lambda n, **k: True)
        assert scheduler.generation_block(
            "c", world.channel, state={"queued": 1, "waiting": 1}, active={}) is None


class TestPublishNow:
    """Publishing by hand from the video's page or Review: the owner, who
    had to go through the schedule or paste links, wanted one click that
    sends it to YouTube and opens TikTok and Instagram."""

    def test_it_uploads_to_youtube_and_hands_off_to_the_plans_platforms(self, world):
        world.channel.publishing.post_tiktok = True
        path = world.video("a", queued=False)
        result = publish_queue.publish_now(world.channel, path, privacy="unlisted")
        info = gallery.load_publish_info(path)
        assert world.state["uploads"] == ["Title a"] and info["youtube_url"] == result["youtube_url"]
        assert result["pending"] == ["tiktok"] and gallery.is_out(info)

    def test_handing_off_writes_its_captions_for_search(self, world, monkeypatch):
        """Decision 085."""
        from core import posting
        written = []
        monkeypatch.setattr(posting, "write_social", lambda channel, video: written.append(video))
        world.channel.publishing.post_tiktok = True
        path = world.video("a", queued=False)
        publish_queue.publish_now(world.channel, path)
        assert written == [path]

    def test_captions_that_cant_be_written_dont_fail_the_publish(self, world, monkeypatch):
        from core import posting

        def broken(channel, video):
            raise RuntimeError("no")
        monkeypatch.setattr(posting, "write_social", broken)
        world.channel.publishing.post_tiktok = True
        path = world.video("a", queued=False)
        assert publish_queue.publish_now(world.channel, path)["pending"] == ["tiktok"]

    def test_without_a_plan_a_channel_with_a_browser_profile_gets_both(self, world):
        world.channel.publishing.posting_profile = "Profile 3"
        path = world.video("a", queued=False)
        assert publish_queue.publish_now(world.channel, path)["pending"] == ["tiktok", "instagram"]

    def test_a_failed_upload_changes_nothing(self, world):
        world.channel.publishing.post_tiktok = True
        path = world.video("a", queued=False)
        world.state["fail"] = True
        with pytest.raises(ExternalServiceError):
            publish_queue.publish_now(world.channel, path)
        info = gallery.load_publish_info(path)
        assert not gallery.is_out(info) and not info["handoff"] and not info["youtube_url"]

    def test_it_is_never_uploaded_twice(self, world):
        world.channel.publishing.post_tiktok = True
        path = world.video("a", queued=False)
        publish_queue.publish_now(world.channel, path)
        again = publish_queue.publish_now(world.channel, path)
        assert len(world.state["uploads"]) == 1 and "already on YouTube" in again["messages"][0]

    def test_with_nowhere_to_send_it_says_so(self, world):
        world.state["connected"] = False
        path = world.video("a", queued=False)
        with pytest.raises(publish_queue.NowhereToPublish) as caught:
            publish_queue.publish_now(world.channel, path)
        assert "nowhere to publish" in caught.value.user_message

    def test_a_discarded_video_isnt_published(self, world):
        path = world.video("a", queued=False)
        gallery.set_discarded(path, True, reason="other")
        with pytest.raises(Exception) as caught:
            publish_queue.publish_now(world.channel, path)
        assert "discarded" in caught.value.user_message and world.state["uploads"] == []

    def test_a_long_video_goes_to_youtube_only(self, world):
        world.channel.publishing.post_tiktok = True
        path = world.video("a", queued=False)
        monkey = pytest.MonkeyPatch()
        monkey.setattr(gallery, "is_long", lambda p: True)
        try:
            assert publish_queue.publish_now(world.channel, path)["pending"] == []
        finally:
            monkey.undo()

    def test_the_route_saves_the_text_publishes_and_leads_to_the_posting_steps(self, world, monkeypatch, tmp_path):
        from core import posting
        from web import create_app
        monkeypatch.setattr(posting, "READY_DIR", tmp_path / "ready")
        monkeypatch.setattr(posting, "STAGED_INDEX", tmp_path / "staged.json")
        world.channel.publishing.post_tiktok = True
        world.channel.publishing.post_instagram = True
        path = world.video("a", queued=False)
        monkeypatch.setattr("web.blueprints.review.video_or_404", lambda relpath: path)
        monkeypatch.setattr("web.blueprints.review.load_channels", lambda validate=True: {"c": world.channel})
        client = create_app().test_client()
        client.get("/m/sign-in")
        with client.session_transaction() as s:
            token = s["_csrf_token"]
        res = client.post("/api/videos/x/publish-now", headers={"X-CSRF-Token": token},
                          json={"title": "My title", "description": "My words"})
        data = res.get_json()
        assert res.status_code == 200 and world.state["uploads"] == ["My title"]
        assert data["pending"] == ["tiktok", "instagram"] and data["next"]
        # The video is waiting, under its title, in the ready-to-post folder.
        assert [f.name for f in (tmp_path / "ready").iterdir()] == ["Chan - My title.mp4"]
        # Its search captions couldn't be written here (no Claude in tests), so
        # To post says it's the plain one, and offers to write them, priced.
        page = client.get("/to-post").get_data(as_text=True)
        assert "plain caption" in page and "Write for search &middot; $0.003" in page
        written = []
        monkeypatch.setattr(posting, "write_social", lambda channel, video: written.append(video))
        res = client.post("/api/videos/x/write-captions", headers={"X-CSRF-Token": token})
        assert res.status_code == 200 and written == [path]


class TestNumberOrder:
    """The owner: videos must go out #1, #2, #3, not in approval order."""

    def _numbered(self, world, name, number, queued=True):
        import json
        path = world.video(name, queued=False)
        path.with_name(f"{name}_quiz.json").write_text(json.dumps({"number": number}))
        if queued:
            publish_queue.enqueue(path, approved_by="you")
        return path

    def test_numbered_shorts_go_out_in_number_order_whatever_order_they_were_approved(self, world):
        three = self._numbered(world, "c", 3)
        one = self._numbered(world, "a", 1)
        two = self._numbered(world, "b", 2)
        plain = world.video("plain")
        assert publish_queue.queued(world.channel) == [one, two, three, plain]

    def test_a_number_waits_while_a_lower_one_is_still_in_review(self, world):
        self._numbered(world, "two", 2, queued=False)          # made, not yet approved
        three = self._numbered(world, "three", 3)
        assert publish_queue.waiting_for(world.channel, three) == 2
        assert publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 18, 1)) == []
        assert world.state["uploads"] == []

    def test_discarding_the_lower_number_releases_the_wait(self, world):
        two = self._numbered(world, "two", 2, queued=False)
        three = self._numbered(world, "three", 3)
        gallery.set_discarded(two, True, reason="other")
        assert publish_queue.waiting_for(world.channel, three) == 0
        assert len(publish_queue.publish_due({"c": world.channel}, now=local(2026, 9, 24, 18, 1))) == 1

    def test_the_going_out_page_lists_them_in_order_with_the_wait(self, world, monkeypatch):
        from web import create_app
        self._numbered(world, "two", 2, queued=False)
        self._numbered(world, "three", 3)
        self._numbered(world, "one", 1)
        monkeypatch.setattr("web.blueprints.review.load_channels", lambda validate=True: {"c": world.channel})
        html = create_app().test_client().get("/queued").get_data(as_text=True)
        assert html.index("#1") < html.index("#3") and "Waits for #2, still in review" in html


class TestClocksGoingBack:
    """25 Oct 2026: just after the clocks went back, latest_slot read
    Saturday's 16:30 as 17:30 (today's offset on another day's time), took
    it for a missed slot, and a film went out at 02:05 on Sunday."""

    PLAN = SimpleNamespace(slots=["16:30"], weekdays=[1, 5])

    def test_the_latest_slot_agrees_with_the_upcoming_ones_across_the_change(self):
        start = datetime(2026, 10, 24, 12, 0).astimezone()
        for hours in range(0, 60):
            now = start + timedelta(hours=hours)
            upcoming = publish_queue.upcoming_slots(self.PLAN, now - timedelta(days=8), 50)
            expected = max(s for s in upcoming if s <= now)
            assert publish_queue.latest_slot(self.PLAN, now) == expected, now

    def test_no_film_goes_out_on_the_sunday_after_saturdays(self):
        saturday = datetime(2026, 10, 24, 16, 30).astimezone()
        if saturday.utcoffset() == datetime(2026, 10, 26, 16, 30).astimezone().utcoffset():
            pytest.skip("this machine's clock has no change on 25 Oct")
        sunday = datetime(2026, 10, 25, 2, 5).astimezone()
        due = publish_queue.latest_slot(self.PLAN, sunday)
        assert due == saturday
        assert publish_queue._filled(self.PLAN, due, saturday + timedelta(minutes=5))


class TestDistinctTitles:
    """25 Oct: "Before the Stop Sign Existed" was queued twice, an old
    teaser render beside the new one. The owner: "make sure that all videos
    have distinct titles!" """

    def test_a_film_channels_video_isnt_sent_under_a_title_another_has(self, world):
        world.channel.format = "documentary"
        first, second = world.video("one"), world.video("two")
        gallery.save_title_and_description(second, "Title one", "About two")
        assert publish_queue.title_clash(world.channel, second) == first
        result = publish_queue._send(world.channel, second)
        assert "same title" in result and not gallery.is_queued(gallery.load_publish_info(second))
        assert world.state["uploads"] == []

    def test_the_frozen_channels_are_left_as_they_are(self, world):
        world.video("one")
        second = world.video("two")
        gallery.save_title_and_description(second, "Title one", "About two")
        assert publish_queue.title_clash(world.channel, second) is None     # not a documentary channel


def test_remade_teasers_retire_the_old_renders(tmp_path, monkeypatch):
    from pipeline.documentary import run
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    monkeypatch.setattr(run, "_root", lambda channel: tmp_path / "out" / "c")
    old, out, new = (tmp_path / "out" / "c" / "d" / f"{n}.mp4" for n in ("old", "out", "new"))
    for p in (old, out, new):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"v")
        gallery.save_title_and_description(p, p.stem, "")
    gallery.save_publish_info(out, {"youtube_url": "https://youtu.be/xxxxxxxxxxx"})
    data = {"teasers": {"videos": ["d/old.mp4", "d/out.mp4", "d/new.mp4"]}}
    assert run.retire_teasers(SimpleNamespace(key="c"), data, keep=["d/new.mp4"]) == ["d/old.mp4"]
    assert gallery.load_publish_info(old)["discarded"] and not gallery.load_publish_info(out).get("discarded")
