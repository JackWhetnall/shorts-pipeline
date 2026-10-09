"""
A channel's descriptions and banner (core.channel_profile, core.banner;
decision 058). The model is faked: what's tested is what is done with its
words and the channel's links.

- each platform's limits hold, cutting at a word;
- the links come from the channel's settings, never from the model, and
  the affiliate disclosure comes with affiliate links;
- the banner is the right size and keeps its text inside the area a phone
  shows;
- the dashboard's checklist knows when it's done.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image

from core import banner, channel_profile, launch
from core.channels import ChannelConfig


@pytest.fixture
def channel(tmp_path, monkeypatch):
    monkeypatch.setattr(channel_profile, "CHANNELS_DIR", tmp_path)
    monkeypatch.setattr(banner, "CHANNELS_DIR", tmp_path)
    monkeypatch.setattr(banner, "channel_logo_dir", lambda key: tmp_path / key / "logo")
    monkeypatch.setattr("core.curriculum.exists", lambda key: False)
    channel = ChannelConfig(key="quiz", channel_display_name="Pub Quiz Buzz", format="quiz",
                            style_prompt="A warm host.", topics=["Science", "Sport"])
    return channel


def _words(**over):
    return {"tagline": "Pub quiz questions at your level", "about": "A quiz for the pub.\n\nSubscribe.",
            "tiktok_bio": "Quiz rounds. Follow for more.", "instagram_bio": "Pub quiz questions, daily.",
            "keywords": ["pub quiz", "trivia", "#quiz", "Pub Quiz"], **over}


def test_each_platforms_limit_holds_and_a_cut_is_at_a_word():
    cleaned = channel_profile.clean(_words(
        tagline="word " * 40, about="sentence. " * 200, tiktok_bio="a " * 100, instagram_bio="b " * 200))
    assert len(cleaned["tagline"]) <= 60 and len(cleaned["about"]) <= 1000
    assert len(cleaned["tiktok_bio"]) <= 80 and len(cleaned["instagram_bio"]) <= 150
    assert not cleaned["tagline"].endswith("wor")           # not mid-word
    assert cleaned["keywords"] == ["pub quiz", "trivia", "quiz"]          # no hashtags, no duplicates


def test_the_words_come_from_the_model_and_are_kept(channel, monkeypatch):
    import pipeline.llm as llm
    seen = {}

    def fake(system, user, schema, **kw):
        seen["user"] = user
        return _words()
    monkeypatch.setattr(llm, "call_json", fake)
    words = channel_profile.generate(channel)
    assert "Pub Quiz Buzz" in seen["user"] and "Science, Sport" in seen["user"]
    # Not the host brief: it's how the videos are written, and was echoed back as production talk.
    assert "A warm host." not in seen["user"]
    assert channel_profile.load("quiz")["about"] == words["about"] and words["generated_at"]


def test_an_empty_answer_isnt_kept(channel, monkeypatch):
    import pipeline.llm as llm
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: _words(about=""))
    with pytest.raises(Exception) as caught:
        channel_profile.generate(channel)
    assert "came back empty" in caught.value.user_message
    assert channel_profile.load("quiz") == {}


def test_the_links_come_from_settings_not_the_model(channel):
    channel.socials.youtube_url = "https://youtube.com/@buzz"
    channel.socials.tiktok_url = "https://tiktok.com/@buzz"
    channel.monetization.patreon_url = "https://patreon.com/buzz"
    channel.monetization.merch_url = "https://shop.example/buzz"
    channel.monetization.affiliate_links = [{"label": "Quiz books", "url": "https://amzn.example/1"}]
    found = channel_profile.links(channel)
    assert found["missing"] == ["Instagram link"]
    text = channel_profile.about_with_links(channel, _words(about="A quiz for the pub."))
    assert text.startswith("A quiz for the pub.")
    assert "Find us:\nTikTok: https://tiktok.com/@buzz" in text and "youtube.com/@buzz" not in text
    assert "Patreon: https://patreon.com/buzz" in text and "Quiz books: https://amzn.example/1" in text
    assert text.endswith("As an Amazon Associate I earn from qualifying purchases.")
    assert channel_profile.bio_link(channel) == "https://youtube.com/@buzz"


def test_without_links_the_text_is_just_the_words(channel):
    assert channel_profile.about_with_links(channel, _words(about="Just words.")) == "Just words."
    assert set(channel_profile.links(channel)["missing"]) == {"YouTube channel link", "TikTok link",
                                                              "Instagram link"}


def test_edits_are_kept_within_limits(channel):
    channel_profile.save("quiz", _words())
    channel_profile.update("quiz", {"tiktok_bio": "x " * 100})
    saved = channel_profile.load("quiz")
    assert len(saved["tiktok_bio"]) <= 80 and saved["about"] == _words()["about"]


@pytest.mark.parametrize("variant", banner.VARIANTS)
def test_the_banner_is_the_right_size_with_its_text_inside_the_phone_area(channel, variant):
    plain = banner.render(channel, "", variant)
    named = banner.render(channel, "Pub quiz questions at your level", variant)
    assert named.size == (2560, 1440)
    # Everything the tagline and name drew is within the area a phone shows.
    from PIL import ImageChops
    changed = ImageChops.difference(plain, named).getbbox()
    x0, y0, x1, y1 = banner.SAFE
    assert changed and changed[0] >= x0 and changed[2] <= x1 and changed[1] >= y0 and changed[3] <= y1


def test_a_very_long_name_still_fits(channel):
    channel.channel_display_name = "The Extraordinarily Long Named Weekly Pub Quiz Round For Everyone"
    from PIL import ImageChops
    empty = ChannelConfig(key="quiz", channel_display_name=" ", format="quiz")
    image = banner.render(channel, "A tagline", "split")
    box = ImageChops.difference(image, banner.render(empty, "", "split")).getbbox()
    assert box[0] >= banner.SAFE[0] and box[2] <= banner.SAFE[2]


def test_a_logo_is_used_when_there_is_one(channel, tmp_path):
    (tmp_path / "quiz" / "logo").mkdir(parents=True)
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(tmp_path / "quiz" / "logo" / "logo.png")
    with_logo = banner.render(channel, "", "split")
    assert with_logo.getpixel((banner.SAFE[0] + 20 + 170, 720)) == (255, 0, 0)


def test_banners_are_saved_and_found(channel):
    assert not banner.exists("quiz")
    made = banner.make(channel, "Tagline")
    assert set(made) == set(banner.VARIANTS) and banner.exists("quiz")
    assert Image.open(made["brand"]).size == (2560, 1440)


def test_the_checklist_step_is_done_once_words_and_banner_exist(channel, monkeypatch):
    stages = lambda: {s.id: s for s in launch.stages(channel, {
        "published": 0, "queued": 0, "waiting": 0, "discarded": 0})[1]}
    monkeypatch.setattr(launch.youtube, "connection", lambda key: {"connected": False, "stats": False, "account": ""})
    monkeypatch.setattr(launch, "gate_agreement", lambda c: (0, 0))
    assert not stages()["profile"].done
    channel_profile.save("quiz", _words())
    assert not stages()["profile"].done                       # words but no banner
    banner.make(channel, "Tagline")
    assert stages()["profile"].done


def test_the_page_and_routes(channel, monkeypatch, tmp_path):
    from web import create_app
    import web.blueprints.profile as page
    import pipeline.llm as llm
    monkeypatch.setattr(page, "channel_or_404", lambda key: channel)
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: _words())
    client = create_app().test_client()
    assert client.get("/channels/quiz/profile").status_code == 200
    client.get("/m/sign-in")
    with client.session_transaction() as s:
        token = s["_csrf_token"]
    head = {"X-CSRF-Token": token}
    made = client.post("/api/channels/quiz/profile/generate", headers=head, json={})
    assert made.status_code == 200 and made.get_json()["words"]["tagline"] == _words()["tagline"]
    assert client.get("/channels/quiz/profile/banner/brand.png").status_code == 200
    assert "attachment" in client.get("/channels/quiz/profile/banner/brand.png?download=1").headers["Content-Disposition"]
    assert client.get("/channels/quiz/profile/banner/nonsense.png").status_code == 404
    saved = client.post("/api/channels/quiz/profile/save", headers=head,
                        json={"tagline": "A new line", "instagram_bio": "New bio"})
    assert saved.get_json()["words"]["tagline"] == "A new line"
    assert "A new line" in client.get("/channels/quiz/profile").get_data(as_text=True)
