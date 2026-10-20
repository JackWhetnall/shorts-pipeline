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

Decision 085, the owner: the captions "arent really descriptions at all,
just eg the verse number or licencing. really needs to be better for SEO".

- each is written for search, its search phrase first, kept beside the
  video, and never names a quiz answer;
- without one, the description's words about the video, never its
  reference line, links or YouTube hashtags; a licence line goes last.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.errors import PipelineError

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
    assert len(posting.hashtags(channel, video, "instagram")) == 5      # Instagram's limit
    assert posting.caption(video, "tiktok", channel).startswith(
        "Country Shapes: Tricky\n\nTen outlines to name.\n\n#countriesquiz")
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
    # Instagram first (decision 119).
    assert [(p["key"], p["posted"]) for p in plan["platforms"]] == [("instagram", False), ("tiktok", True)]
    assert plan["file"].endswith(".mp4") and "Ctrl+V" in plan["platforms"][0]["steps"][0]
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


# --- opening the right account's upload page (from the first version) ----------------
# Nothing is launched: `subprocess.Popen` and `webbrowser.open` are recorded.
# What matters: the channel's own profile is the one opened, arguments go as
# a list rather than through a shell, and with no profile the default
# browser still works.

@pytest.fixture
def launched(monkeypatch):
    calls = {"popen": [], "web": []}
    monkeypatch.setattr(posting.subprocess, "Popen", lambda args: calls["popen"].append(args))
    monkeypatch.setattr(posting.webbrowser, "open", lambda url: calls["web"].append(url))
    monkeypatch.setattr(posting, "_exe", lambda browser: f"C:/{browser}.exe" if browser else None)
    return calls


def _pastor(**plan):
    channel = ChannelConfig(key="minute_pastor", voice="21m00Tcm4TlvDq8ikWAM", style_prompt="x")
    for name, value in plan.items():
        setattr(channel.publishing, name, value)
    return channel


def test_opens_the_channels_own_profile_with_the_video_ready(launched, world):
    _, video = world
    channel = _pastor(posting_browser="chrome", posting_profile="Shorts minute_pastor")
    result = posting.start_post(channel, video, "tiktok")
    # Only the browser: no Explorer window (the path goes on the clipboard instead).
    assert launched["popen"] == [["C:/chrome.exe", "--profile-directory=Shorts minute_pastor",
                                  posting.UPLOAD_URLS["tiktok"]]]
    assert Path(result["file"]).exists() and result["platform"] == "TikTok"


def test_without_a_profile_it_uses_the_default_browser(launched, world):
    posting.start_post(_pastor(), world[1], "instagram")
    assert launched["web"] == [posting.UPLOAD_URLS["instagram"]]


def test_an_unknown_platform_is_refused(launched, world):
    with pytest.raises(PipelineError):
        posting.start_post(_pastor(), world[1], "myspace")
    assert launched["popen"] == [] and launched["web"] == []


def test_setting_up_a_profile_names_it_for_the_channel_and_opens_both_logins(launched):
    channel = _pastor()
    folder = posting.set_up_profile(channel)
    assert folder == "Shorts minute_pastor"
    assert channel.publishing.posting_browser == "chrome"
    args = launched["popen"][0]
    assert f"--profile-directory={folder}" in args
    assert posting.LOGIN_URLS["tiktok"] in args and posting.LOGIN_URLS["instagram"] in args


# --- written for search (decision 085) ----------------------------------------------

MP_DESCRIPTION = ("A man born blind gets his sight back.\n\n#JohnGospel #Faith\n\nReference: John 9:12\n\n"
                  "Support the channel: https://patreon.com/x\n\nMusic: Calm by Someone (CC BY 4.0).")


def test_the_plain_caption_keeps_only_what_the_description_says_about_the_video(world):
    channel, video = world
    gallery.save_title_and_description(video, "The Man Who Couldn't Answer", MP_DESCRIPTION)
    insta = posting.caption(video, "instagram", channel)
    assert insta.startswith("The Man Who Couldn't Answer\n\nA man born blind gets his sight back.\n\n#")
    assert "Reference:" not in insta and "#JohnGospel" not in insta and "patreon" not in insta
    assert insta.endswith("Music: Calm by Someone (CC BY 4.0).")      # CC BY asks for it wherever it's shown
    assert posting.caption(video, "tiktok", channel).endswith("Music: Calm by Someone (CC BY 4.0).")


def test_a_render_reports_credits_are_the_licence_lines(world):
    channel, video = world
    video.with_name("countries_tricky_report.json").write_text(json.dumps({"artwork": ["Map: Someone (CC BY-SA)."]}))
    assert posting.credits(video) == ["Map: Someone (CC BY-SA)."]


@pytest.fixture
def writer(monkeypatch):
    calls = []

    def fake(system, prompt, schema, **kw):
        calls.append({"prompt": prompt, **kw})
        return {"tiktok": {"caption": "Countries quiz — ten tricky outlines. #geo",
                           "hashtags": ["#CountriesQuiz", "geography trivia", "#pubquizbuzz", "#a b"]},
                "instagram": {"caption": "Countries quiz: is the answer France?", "hashtags": ["#quiz"]}}
    monkeypatch.setattr("pipeline.llm.call_json", fake)
    return calls


def test_captions_are_written_for_search_and_never_give_an_answer_away(world, writer):
    channel, video = world
    video.with_name("countries_tricky_quiz.json").write_text(json.dumps({
        "category": "Countries", "difficulty": "Tricky",
        "questions": [{"question": "Which country is shaped like a boot?", "answer": "Italy"},
                      {"question": "Whose capital is Paris?", "answer": "France", "spoken_answer": "France."}]}))
    gallery.save_queue_state(video, handoff={"tiktok": {"at": "x", "posted_at": None},
                                             "instagram": {"at": "x", "posted_at": None}})
    posting.write_social(channel, video)
    prompt = writer[0]["prompt"]
    assert prompt.startswith("Search phrase: Countries quiz") and "shaped like a boot" in prompt
    assert "Italy" not in prompt and "France" not in prompt
    assert writer[0]["model"] == "claude-haiku-5-5" and writer[0]["operation"] == "social_caption"
    tiktok = posting.caption(video, "tiktok", channel)
    assert tiktok == "Countries quiz, ten tricky outlines. geo\n\n#countriesquiz #geographytrivia #pubquizbuzz"
    plan = posting.plan(channel, video)
    by_key = {p["key"]: p for p in plan["platforms"]}
    assert by_key["tiktok"]["for_search"]
    # Instagram's named an answer, so it's the plain one, and To post says so.
    assert not by_key["instagram"]["for_search"] and "France" not in by_key["instagram"]["caption"]


def test_a_retitled_video_goes_back_to_its_plain_caption(world, writer):
    channel, video = world
    posting.write_social(channel, video)
    assert posting.social(video)
    gallery.save_title_and_description(video, "Outlines of the World", "Ten outlines to name.")
    assert posting.social(video) == {}
    assert posting.caption(video, "tiktok", channel).startswith("Outlines of the World")


def test_the_captions_file_belongs_to_the_video(world, writer):
    channel, video = world
    posting.write_social(channel, video)
    assert posting.social_path(video) in gallery.sidecars_of(video)


def test_to_post_opens_each_platform_once_and_copies_the_thumbnail_too(world, tmp_path, monkeypatch):
    # Decision 120, the owner: the open buttons once at the top, then per
    # video its location, thumbnail and caption; the link box always there.
    from core.channels import channel_to_sparse_dict, write_raw
    from web import create_app
    channel, video = world
    channel.output_dir = str(video.parent.parent)
    channel.publishing.post_tiktok = channel.publishing.post_instagram = True
    path = tmp_path / "channels.json"
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
    write_raw({channel.key: channel_to_sparse_dict(channel)}, path)
    video.with_name("countries_tricky_cover.jpg").write_bytes(b"jpg")
    gallery.save_queue_state(video, handoff={"tiktok": {"at": "x", "posted_at": None},
                                             "instagram": {"at": "x", "posted_at": None}})
    assert posting.plan(channel, video)["thumb"].endswith("countries_tricky_cover.jpg")
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        page = client.get("/to-post").get_data(as_text=True)
    assert page.count("Open Instagram") == 1 and page.count("Open TikTok") == 1
    assert page.index("Open Instagram") < page.index("Open TikTok")
    assert page.index('data-platform="instagram"') < page.index('data-platform="tiktok"')
    assert "Copy thumbnail" in page and "location again" not in page and "The video is" not in page
    assert 'placeholder="Instagram link (optional)"' in page and "Add the post" not in page
