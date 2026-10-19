"""
Posting Shorts to Instagram by themselves (core.instagram, decision 116).
The owner: "The TikTok/instagram posting is still annoyingly manual. Why
didn't we implement the private upload features to save us clicks?"

- one token from the Graph API Explorer brings every channel's account,
  kept with its Page's lasting token, never in a URL or the log;
- a Short that goes out is posted as a Reel within a pass or two and
  marked posted with its link, exactly as if posted by hand;
- a restart part-way never posts it twice, and a stalled container is
  given up rather than published;
- connecting doesn't post the backlog: only Shorts from the last two
  days go by themselves, older ones on "Post it for me";
- three failures leave it to the owner with the reason, a lapsed
  connection says so, and a busy Instagram isn't counted as a failure;
- a teaser's caption says where its film is.
"""

from __future__ import annotations

import json
import struct
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import gallery, instagram, posting, publish_queue
from core.channels import ChannelConfig

IG = "17841400000000001"


class Reply:
    def __init__(self, data, status=200):
        self.status_code, self._data = status, data
        self.ok = status < 400
        self.text = json.dumps(data)

    def json(self):
        return self._data


class Meta:
    """Graph API and rupload, as far as these tests need them."""

    def __init__(self):
        self.calls = []
        self.statuses = ["FINISHED"]
        self.fail = {}             # what -> error dict, for the next call to it
        self.containers = 0
        self.published = 0

    def __call__(self, method, url, timeout=None, params=None, data=None, headers=None):
        what = url.split("?")[0]
        self.calls.append({"method": method, "url": url, "params": params or {}, "data": data,
                           "headers": headers or {}})
        for key, error in list(self.fail.items()):
            if key in what:
                if not error.get("_keep"):
                    self.fail.pop(key)
                body = {k: v for k, v in error.items() if not k.startswith("_")}
                return Reply({"error": body}, status=error.get("_status", 400))
        if what.endswith("/oauth/access_token"):
            return Reply({"access_token": "LONG", "token_type": "bearer", "expires_in": 5183944})
        if what.endswith("/me/accounts"):
            if params:          # the first page
                return Reply({"data": [{"id": "P1", "name": "Why, Though?", "access_token": "PAGE1",
                                        "instagram_business_account": {"id": IG, "username": "whythough"}}],
                              "paging": {"next": "https://graph.facebook.com/v25.0/me/accounts?after=x&access_token=LONG"}})
            return Reply({"data": [{"id": "P2", "name": "A page without Instagram", "access_token": "PAGE2"}]})
        if what.endswith(f"/{IG}/media") and method == "POST":
            self.containers += 1
            cid = f"C{self.containers}"
            return Reply({"id": cid, "uri": f"https://rupload.facebook.com/ig-api-upload/v25.0/{cid}"})
        if "rupload.facebook.com" in what:
            data.read()
            return Reply({"success": True, "message": "Upload successful."})
        if what.endswith("/media_publish"):
            self.published += 1
            return Reply({"id": "M1"})
        if what.endswith("/M1"):
            return Reply({"permalink": "https://www.instagram.com/reel/abc/"})
        if what.endswith(f"/{IG}/media"):
            return Reply({"data": [{"permalink": "https://www.instagram.com/reel/found/",
                                    "caption": self.last_caption()}]})
        if "/C" in what:
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return Reply({"status_code": status, "status": "Finished: Media has been uploaded"})
        return Reply({"error": {"message": f"unexpected {method} {what}"}}, status=404)

    def last_caption(self):
        made = [c for c in self.calls if c["url"].endswith(f"/{IG}/media") and c["method"] == "POST"]
        return made[-1]["data"]["caption"] if made else ""


@pytest.fixture
def meta(monkeypatch):
    fake = Meta()
    monkeypatch.setattr(instagram.requests, "request", fake)
    return fake


@pytest.fixture
def world(tmp_path, monkeypatch, meta):
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    monkeypatch.setattr(instagram, "WAIT_NOW", 0)
    monkeypatch.setattr(instagram, "POLL_EVERY", 0)

    def ready(video):
        out = instagram.READY_DIR / f"{Path(video).parent.name}_{Path(video).stem}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"ready video")
        return out
    monkeypatch.setattr(instagram, "ready_copy", ready)
    channel = ChannelConfig(key="why_though", channel_display_name="Why, Though?", format="documentary",
                            output_dir=str(tmp_path / "out" / "why_though"))
    channel.publishing.post_instagram = True
    channel.publishing.post_tiktok = True
    video = tmp_path / "out" / "why_though" / "2026-10-19" / "airline_food_teaser_1.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    gallery.save_title_and_description(video, "Why airline food tastes of nothing", "Thirty thousand feet up.")
    instagram.save_app("1234567890", "0123456789abcdef0123456789abcdef")
    instagram.connect("SHORT")
    channel.publishing.instagram_account = IG
    meta.calls.clear()
    return channel, video


def _hand_off(video, ago=timedelta(minutes=1)):
    at = (datetime.now(timezone.utc) - ago).isoformat()
    gallery.save_queue_state(video, handoff={"tiktok": {"at": at, "posted_at": None},
                                             "instagram": {"at": at, "posted_at": None}})


def _instagram_entry(video):
    return gallery.load_publish_info(video)["handoff"]["instagram"]


# --- connecting ---------------------------------------------------------------------

def test_one_token_brings_every_account_with_its_pages_lasting_token(world, meta):
    saved = json.loads(instagram.PATH.read_text(encoding="utf-8"))
    assert saved["accounts"][IG]["token"] == "PAGE1"            # the Page's own, which doesn't expire
    assert saved["accounts"][IG]["username"] == "whythough"
    assert list(saved["accounts"]) == [IG]                       # a Page with no Instagram brings nothing
    assert instagram.choices() == [{"value": IG, "label": "@whythough"}]
    channel, _ = world
    assert instagram.account_for(channel)["id"] == IG and instagram.posts_by_itself(channel)


def test_tokens_never_go_in_a_url_and_secrets_never_reach_the_log(meta, tmp_path):
    instagram.save_app("1234567890", "0123456789abcdef0123456789abcdef")
    instagram.connect("SHORT")
    pages = [c for c in meta.calls if c["url"].endswith("/me/accounts")]
    assert pages[0]["headers"]["Authorization"] == "Bearer LONG" and "access_token" not in pages[0]["params"]
    line = instagram._redacted("Connection refused: https://graph.facebook.com/x?client_secret=abc&"
                               "fb_exchange_token=def&access_token=ghi&limit=10")
    assert "abc" not in line and "def" not in line and "ghi" not in line and "limit=10" in line


def test_connecting_says_what_is_wrong(meta):
    with pytest.raises(instagram.InstagramError) as caught:
        instagram.connect("SHORT")
    assert "Save the Meta app" in caught.value.user_message
    with pytest.raises(instagram.InstagramError) as caught:
        instagram.save_app("my app", "0123456789abcdef0123456789abcdef")
    assert "isn't an app ID" in caught.value.user_message
    instagram.save_app("1234567890", "0123456789abcdef0123456789abcdef")
    meta.fail["/oauth/access_token"] = {"code": 190, "message": "Invalid OAuth access token"}
    with pytest.raises(instagram.InstagramError) as caught:
        instagram.connect("SHORT")
    assert "generate a new one" in caught.value.user_message
    meta.fail["/oauth/access_token"] = {"code": 1, "message": "Error validating client secret"}
    with pytest.raises(instagram.InstagramError) as caught:
        instagram.connect("SHORT")
    assert "ID and secret" in caught.value.user_message


def test_a_token_without_any_instagram_account_says_how_to_fix_it(meta, monkeypatch):
    instagram.save_app("1234567890", "0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(instagram, "_pages", lambda token: [{"id": "P2", "name": "No Instagram",
                                                             "access_token": "PAGE2"}])
    with pytest.raises(instagram.InstagramError) as caught:
        instagram.connect("SHORT")
    assert "professional account linked to a Facebook Page" in caught.value.user_message


def test_a_channel_only_takes_an_account_that_is_connected(world):
    from web.forms import _apply_publishing_plan
    channel, _ = world
    channel.publishing.instagram_account = ""
    _apply_publishing_plan(channel.publishing, _Form(instagram_account="someone_else"))
    assert channel.publishing.instagram_account == ""
    _apply_publishing_plan(channel.publishing, _Form(instagram_account=IG))
    assert channel.publishing.instagram_account == IG
    _apply_publishing_plan(channel.publishing, _Form())     # a page without the choice leaves it alone
    assert channel.publishing.instagram_account == IG


class _Form(dict):
    def getlist(self, key):
        return []


# --- posting ------------------------------------------------------------------------

def test_a_short_that_goes_out_is_posted_as_a_reel_and_marked_with_its_link(world, meta):
    channel, video = world
    _hand_off(video)
    lines = instagram.post_due({channel.key: channel})
    entry = _instagram_entry(video)
    assert entry["posted_at"] and gallery.load_publish_info(video)["instagram_url"] == "https://www.instagram.com/reel/abc/"
    assert lines == ["Why, Though?: Why airline food tastes of nothing posted on Instagram"]
    made = next(c for c in meta.calls if c["url"].endswith(f"/{IG}/media"))
    assert made["data"]["media_type"] == "REELS" and made["data"]["upload_type"] == "resumable"
    assert made["data"]["caption"] == posting.caption(video, "instagram", channel)
    upload = next(c for c in meta.calls if "rupload" in c["url"])
    assert upload["headers"]["Authorization"] == "OAuth PAGE1"
    assert upload["headers"]["file_size"] == str(len(b"ready video")) and upload["headers"]["offset"] == "0"
    assert not entry["auto"].get("container")
    assert not list(instagram.READY_DIR.glob("*.mp4"))          # its prepared copy is cleared away
    assert not _instagram_entry(video).get("auto", {}).get("failed")
    assert gallery.load_publish_info(video)["handoff"]["tiktok"]["posted_at"] is None   # TikTok is still yours


def test_one_still_processing_is_published_on_a_later_pass_from_the_same_container(world, meta):
    channel, video = world
    _hand_off(video)
    meta.statuses = ["IN_PROGRESS", "FINISHED"]
    instagram.post_due({channel.key: channel})
    assert _instagram_entry(video)["auto"]["container"] == "C1" and not _instagram_entry(video)["posted_at"]
    assert instagram.state(channel, video)["status"] == "processing"
    instagram.post_due({channel.key: channel})
    assert _instagram_entry(video)["posted_at"]
    assert meta.containers == 1 and meta.published == 1


def test_a_restart_after_publishing_never_publishes_it_again(world, meta):
    channel, video = world
    _hand_off(video)
    meta.statuses = ["IN_PROGRESS"]
    instagram.post_due({channel.key: channel})
    meta.statuses = ["PUBLISHED"]                  # a pass published it and didn't live to record it
    instagram.post_due({channel.key: channel})
    assert _instagram_entry(video)["posted_at"] and meta.published == 0
    assert gallery.load_publish_info(video)["instagram_url"] == "https://www.instagram.com/reel/found/"


def test_a_stalled_container_is_given_up_never_published(world, meta, monkeypatch):
    channel, video = world
    _hand_off(video)
    meta.statuses = ["IN_PROGRESS"]
    instagram.post_due({channel.key: channel})
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    instagram._set_auto(video, started_at=long_ago)
    instagram.post_due({channel.key: channel})
    auto = _instagram_entry(video)["auto"]
    assert auto["tries"] == 1 and not auto.get("container") and meta.published == 0
    meta.statuses = ["FINISHED"]
    instagram.post_due({channel.key: channel})
    assert _instagram_entry(video)["posted_at"] and meta.containers == 2 and meta.published == 1


def test_three_failures_leave_it_to_the_owner_with_the_reason(world, meta):
    channel, video = world
    _hand_off(video)
    for _ in range(3):
        meta.fail[f"/{IG}/media"] = {"code": 100, "error_subcode": 2207026,
                                     "error_user_msg": "The video format is not supported."}
        instagram.post_due({channel.key: channel})
    state = instagram.state(channel, video)
    assert state["status"] == "failed" and "The video format is not supported." in state["error"]
    instagram.post_due({channel.key: channel})                   # given up: not tried again by itself
    assert meta.containers == 0
    plan = posting.plan(channel, video)
    insta = next(p for p in plan["platforms"] if p["key"] == "instagram")
    assert insta["auto"]["status"] == "failed" and insta["steps"]       # the steps by hand are there too


def test_a_busy_instagram_is_tried_again_without_counting_against_it(world, meta):
    channel, video = world
    _hand_off(video)
    meta.fail[f"/{IG}/media"] = {"code": 4, "message": "Application request limit reached", "_status": 400}
    instagram.post_due({channel.key: channel})
    auto = _instagram_entry(video)["auto"]
    assert not auto.get("tries") and not auto.get("failed") and "busy" in auto["error"]
    instagram.post_due({channel.key: channel})
    assert _instagram_entry(video)["posted_at"]


def test_a_lapsed_connection_says_so_and_waits(world, meta):
    channel, video = world
    _hand_off(video)
    meta.fail[f"/{IG}/media"] = {"code": 190, "message": "Error validating access token", "_keep": True}
    instagram.post_due({channel.key: channel})
    assert "connect again" in instagram.problem()
    assert not _instagram_entry(video)["auto"].get("tries")
    meta.fail.clear()
    instagram.connect("SHORT")                                   # connecting again clears it
    assert instagram.problem() == ""


def test_connecting_does_not_post_the_backlog(world, meta):
    channel, video = world
    _hand_off(video, ago=timedelta(days=3))
    assert instagram.post_due({channel.key: channel}) == [] and meta.containers == 0
    assert instagram.state(channel, video)["status"] == "older"
    rows = publish_queue.awaiting_posts({channel.key: channel})
    assert rows[0]["by_itself"] == []                           # it's the owner's: "Post it for me"


def test_post_it_for_me_takes_an_older_one_up(world, meta, monkeypatch):
    channel, video = world
    _hand_off(video, ago=timedelta(days=3))
    started = []
    monkeypatch.setattr(instagram, "_in_background", started.append)
    instagram.post_now(channel, video)
    assert instagram.state(channel, video)["status"] == "queued"
    started[0]()
    assert _instagram_entry(video)["posted_at"]


def test_what_needs_the_owner_leaves_out_what_instagram_is_doing(world, meta):
    channel, video = world
    _hand_off(video)
    rows = publish_queue.awaiting_posts({channel.key: channel})
    assert rows[0]["platforms"] == ["tiktok", "instagram"] and rows[0]["by_itself"] == ["instagram"]
    channel.publishing.instagram_account = ""
    assert publish_queue.awaiting_posts({channel.key: channel})[0]["by_itself"] == []
    assert instagram.state(channel, video) == {"auto": False}


def test_a_channel_without_an_account_is_left_to_post_by_hand(world, meta):
    channel, video = world
    channel.publishing.instagram_account = ""
    _hand_off(video)
    assert instagram.post_due({channel.key: channel}) == [] and meta.calls == []


# --- the video and its caption ------------------------------------------------------

def test_a_teasers_caption_says_where_its_film_is(world):
    channel, video = world
    assert "Full video on YouTube" not in posting.caption(video, "instagram", channel)
    gallery.save_report(video, {"teaser": True, "teaser_of": "Why airline food tastes of nothing"})
    for platform in ("instagram", "tiktok"):
        assert "Full video on YouTube: Why, Though?" in posting.caption(video, platform, channel)


def test_the_copy_instagram_gets_has_its_index_first(tmp_path):
    import imageio_ffmpeg
    source = tmp_path / "2026-10-19" / "teaser.mp4"
    source.parent.mkdir()
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=108x192:d=1:r=30", "-f", "lavfi", "-i", "sine=f=440:d=1",
                    "-c:v", "libx264", "-c:a", "aac", "-b:a", "160k", "-shortest", str(source)], check=True)
    ready = instagram.ready_copy(source)
    atoms, data, at = [], ready.read_bytes(), 0
    while at + 8 <= len(data):
        size, kind = struct.unpack(">I4s", data[at:at + 8])
        atoms.append(kind.decode("latin1"))
        if size < 8:
            break
        at += size
    assert atoms.index("moov") < atoms.index("mdat")
    assert ready.parent == instagram.READY_DIR and ready.name == "2026-10-19_teaser.mp4"


# --- the pages ----------------------------------------------------------------------

def test_the_setup_page_saves_the_app_and_connects(world, meta, tmp_path, monkeypatch):
    from core.channels import channel_to_sparse_dict, write_raw
    from web import create_app
    channel, _ = world
    path = tmp_path / "channels.json"
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
    write_raw({channel.key: channel_to_sparse_dict(channel)}, path)
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        page = client.get("/instagram/setup").get_data(as_text=True)
        assert "@whythough" in page and "Graph API Explorer" in page and "Why, Though?" in page
        marker = 'name="csrf-token" content="'
        token = page[page.index(marker) + len(marker):]
        token = token[:token.index('"')]
        page = client.post("/instagram/setup", data={"action": "connect", "token": "SHORT",
                                                     "csrf_token": token}).get_data(as_text=True)
        assert "Connected: @whythough" in page
        page = client.post("/instagram/setup", data={"action": "app", "app_id": "not a number",
                                                     "app_secret": "x", "csrf_token": token}).get_data(as_text=True)
        assert "an app ID" in page
        settings = client.get(f"/channels/{channel.key}/settings").get_data(as_text=True)
        assert "Instagram posts by itself as" in settings and "@whythough" in settings


def test_to_post_shows_what_instagram_is_doing(world, meta, tmp_path, monkeypatch):
    from core.channels import channel_to_sparse_dict, write_raw
    from web import create_app
    channel, video = world
    path = tmp_path / "channels.json"
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
    write_raw({channel.key: channel_to_sparse_dict(channel)}, path)
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        _hand_off(video)
        page = client.get("/to-post").get_data(as_text=True)
        assert "Posting by itself" in page and "Open TikTok" in page
        _hand_off(video, ago=timedelta(days=3))
        page = client.get("/to-post").get_data(as_text=True)
        assert "Post it for me" in page and "Posting by itself" not in page


def test_not_ready_to_publish_yet_waits_for_the_same_container(world, meta):
    channel, video = world
    _hand_off(video)
    meta.fail["/media_publish"] = {"code": 9007, "error_subcode": 2207027,
                                   "message": "The media is not ready for publishing, please wait for a moment"}
    instagram.post_due({channel.key: channel})
    auto = _instagram_entry(video)["auto"]
    assert auto["container"] == "C1" and not auto.get("tries")
    instagram.post_due({channel.key: channel})
    assert _instagram_entry(video)["posted_at"] and meta.containers == 1 and meta.published == 1
