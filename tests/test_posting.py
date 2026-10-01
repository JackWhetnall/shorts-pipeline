"""
Posting to TikTok and Instagram by hand (core.posting, decision 059). The
owner: the To post page gave a title and two buttons, opened the wrong
browser profile, showed no file, no caption and no hashtags, and asked
for a link without saying what for.

- each platform gets its own caption with its own hashtags, what the
  video is about first;
- the video waits in one plain folder, named by its title, and leaves it
  once it's posted everywhere or discarded;
- the steps say what to do, platform by platform;
- a profile is named by who's signed in to it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import channel_profile, gallery, posting, publish_queue
from core.channels import ChannelConfig


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    monkeypatch.setattr(channel_profile, "CHANNELS_DIR", tmp_path / "channels")
    channel = ChannelConfig(key="buzz", channel_display_name="Pub Quiz Buzz", format="quiz")
    video = tmp_path / "out" / "buzz" / "2026-10-01" / "countries_tricky.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    gallery.save_title_and_description(video, "Country Shapes: Tricky", "Ten outlines to name.")
    video.with_name("countries_tricky_quiz.json").write_text(json.dumps({"category": "Countries"}))
    channel_profile.save("buzz", {"keywords": ["pub quiz", "geography quiz", "trivia night"]})
    return channel, video


def test_each_platform_gets_its_own_caption_and_hashtags(world):
    channel, video = world
    assert posting.hashtags(channel, video, "youtube") == ["#countriesquiz", "#countries", "#pubquizbuzz"]
    tiktok = posting.hashtags(channel, video, "tiktok")
    assert len(tiktok) == 5 and tiktok[0] == "#countriesquiz" and tiktok[-1] == "#pubquizbuzz"
    assert len(posting.hashtags(channel, video, "instagram")) <= 10
    assert posting.caption(video, "tiktok", channel).startswith("Country Shapes: Tricky\n\n#countriesquiz")
    insta = posting.caption(video, "instagram", channel)
    assert "Ten outlines to name." in insta and "#geographyquiz" in insta


def test_the_youtube_description_gets_its_hashtags_once(world):
    channel, video = world
    with_tags = posting.with_youtube_hashtags(channel, video, "Ten outlines to name.")
    assert with_tags.endswith("#countriesquiz #countries #pubquizbuzz")
    assert posting.with_youtube_hashtags(channel, video, "Own tags #geo") == "Own tags #geo"


def test_the_video_waits_in_one_plain_folder_until_its_posted_everywhere(world):
    channel, video = world
    gallery.save_queue_state(video, handoff={"tiktok": {"at": "x", "posted_at": None},
                                             "instagram": {"at": "x", "posted_at": None}})
    staged = posting.stage(channel, video)
    assert staged.name == "Pub Quiz Buzz - Country Shapes Tricky.mp4" and staged.read_bytes() == b"video"
    assert posting.stage(channel, video) == staged                 # the same file, not another copy
    publish_queue.mark_posted(video, "tiktok")
    assert staged.exists()
    publish_queue.mark_posted(video, "instagram", "https://instagram.com/reel/1")
    assert not staged.exists() and gallery.load_publish_info(video)["instagram_url"]


def test_a_discarded_video_leaves_the_folder(world):
    channel, video = world
    staged = posting.stage(channel, video)
    gallery.set_discarded(video, True, reason="other")
    assert not staged.exists()


def test_two_videos_with_one_title_dont_collide(world, tmp_path):
    channel, video = world
    other = video.with_name("countries_tricky_2.mp4")
    other.write_bytes(b"other")
    gallery.save_title_and_description(other, "Country Shapes: Tricky", "")
    a, b = posting.stage(channel, video), posting.stage(channel, other)
    assert a != b and b.read_bytes() == b"other"


def test_the_steps_show_whats_left_to_post(world):
    channel, video = world
    gallery.save_queue_state(video, handoff={"tiktok": {"at": "x", "posted_at": "y"},
                                             "instagram": {"at": "x", "posted_at": None}})
    plan = posting.plan(channel, video)
    assert [(p["key"], p["posted"]) for p in plan["platforms"]] == [("tiktok", True), ("instagram", False)]
    assert plan["file"].endswith(".mp4") and "Ctrl+V" in plan["platforms"][1]["steps"][1]
    assert plan["where"] == "your default browser"


def test_a_profile_is_named_by_whos_signed_in(monkeypatch, tmp_path):
    state = tmp_path / "Local State"
    state.write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Person 1", "user_name": "someone@example.com"},
        "Profile 1": {"name": "Jack"},
        "Shorts buzz": {"name": "Your Chrome"}}}}))
    monkeypatch.setitem(posting.BROWSERS["chrome"], "data", str(tmp_path))
    names = dict(posting.profiles("chrome"))
    assert names == {"Default": "Person 1 (someone@example.com)", "Profile 1": "Jack",
                     "Shorts buzz": "made for buzz"}


def test_descriptions_that_talk_about_production_are_written_again(monkeypatch, tmp_path):
    import pipeline.llm as llm
    monkeypatch.setattr(channel_profile, "CHANNELS_DIR", tmp_path)
    monkeypatch.setattr("core.curriculum.exists", lambda key: False)
    replies = iter([
        {"tagline": "Quiz rounds", "about": "Each round has a countdown clock and matching on-screen text.",
         "tiktok_bio": "x", "instagram_bio": "y", "keywords": []},
        {"tagline": "Quiz rounds", "about": "Get the one nobody else in the room knew.",
         "tiktok_bio": "x", "instagram_bio": "y", "keywords": []}])
    asked = []
    monkeypatch.setattr(llm, "call_json", lambda system, user, *a, **k: asked.append(user) or next(replies))
    channel = ChannelConfig(key="buzz", channel_display_name="Buzz", format="quiz",
                            style_prompt="Show matching on-screen text with a countdown.")
    words = channel_profile.generate(channel)
    assert words["about"] == "Get the one nobody else in the room knew."
    assert "on-screen" in asked[1] and "Show matching" not in asked[0]          # no host brief given
