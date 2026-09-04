"""
Web-layer tests.

Mostly these are smoke tests, and that's deliberate: the single biggest
risk in splitting an 890-line module into blueprints is a mistyped
`url_for` endpoint or a template that references something the new route
no longer passes. Neither shows up until someone opens the page. Actually
rendering every page catches both.

The rest cover the security properties added in this pass — CSRF and path
traversal — because a protection nobody tests is a protection that
quietly stops working.
"""

from __future__ import annotations

import json

import pytest

from core.channels import ChannelConfig, channel_to_sparse_dict, write_raw
from web import create_app


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    """Point the config layer at a throwaway file so tests never touch
    the real channels."""
    path = tmp_path / "channels.json"
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
    channel = ChannelConfig(
        key="test_channel", channel_display_name="Test Channel",
        content_mode="topic", voice="voice-id", style_prompt="Write something.",
        topics=["coffee"],
    )
    channel.output_dir = str(tmp_path / "out")
    write_raw({"test_channel": channel_to_sparse_dict(channel)}, path)
    return path


@pytest.fixture
def client(config_path, tmp_path, monkeypatch):
    monkeypatch.setattr("core.paths.OUTPUT_DIR", tmp_path / "out")
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def csrf(client) -> str:
    """Pull a live token out of a rendered page, the same way the browser
    does."""
    html = client.get("/").get_data(as_text=True)
    marker = 'name="csrf-token" content="'
    start = html.index(marker) + len(marker)
    return html[start:html.index('"', start)]


class TestPagesRender:
    """Every GET route, rendered. A blueprint rename that misses one
    `url_for` fails here rather than in front of the user."""

    @pytest.mark.parametrize("path", [
        "/",
        "/channels/test_channel",
        "/channels/test_channel/settings",
        "/channels/new",
        "/channels/test_channel/create",
        "/channels/test_channel/gallery",
        "/channels/test_channel/logo",
        "/channels/test_channel/delete",
        "/voice-lab",
    ])
    def test_renders(self, client, path):
        response = client.get(path)
        assert response.status_code == 200, response.get_data(as_text=True)[:600]

    @pytest.mark.parametrize("step", [
        "logo", "email", "socials", "patreon", "merch_logo", "merch_store", "amazon",
    ])
    def test_every_wizard_step_renders(self, client, step):
        response = client.get(f"/channels/test_channel/setup/{step}")
        assert response.status_code == 200, response.get_data(as_text=True)[:600]

    def test_unknown_channel_is_a_friendly_404(self, client):
        response = client.get("/channels/does_not_exist")
        assert response.status_code == 404
        assert "no channel called" in response.get_data(as_text=True).lower()

    def test_unknown_wizard_step_is_404(self, client):
        assert client.get("/channels/test_channel/setup/nope").status_code == 404


class TestNewSurfaces:
    """The review queue, insights and footage browser — added because the
    daily loop and the improvement loop had no pages at all."""

    @pytest.mark.parametrize("path", ["/review", "/insights", "/footage"])
    def test_renders(self, client, path):
        response = client.get(path)
        assert response.status_code == 200, response.get_data(as_text=True)[:600]

    def test_review_and_insights_are_cross_channel(self, client):
        # Neither takes a channel key: the unit of work is a video.
        from web import create_app
        app = create_app()
        rules = {str(r) for r in app.url_map.iter_rules()}
        assert "/review" in rules
        assert "/insights" in rules

    def test_footage_search_accepts_a_query(self, client):
        assert client.get("/footage?q=candle&show=unused").status_code == 200

    def test_empty_review_queue_says_so(self, client):
        body = client.get("/review").get_data(as_text=True)
        assert "caught up" in body.lower() or "waiting" in body.lower()


class TestDiscardReasons:
    """Discarding used to record a boolean and nothing else — throwing
    away the richest quality signal in the system."""

    @pytest.fixture
    def video(self, tmp_path):
        directory = tmp_path / "out" / "2026-09-03"
        directory.mkdir(parents=True)
        path = directory / "john_3_16.mp4"
        path.write_bytes(b"x")
        return path

    def test_reason_and_time_are_recorded(self, video):
        from core import gallery
        gallery.set_discarded(video, True, reason="footage")
        info = gallery.load_publish_info(video)
        assert info["discard_reason"] == "footage"
        assert info["discarded_at"]

    def test_an_unknown_reason_becomes_other(self, video):
        from core import gallery
        gallery.set_discarded(video, True, reason="nonsense")
        assert gallery.load_publish_info(video)["discard_reason"] == "other"

    def test_restoring_clears_the_reason(self, video):
        # A restored video must stop contributing to discard statistics.
        from core import gallery
        gallery.set_discarded(video, True, reason="script")
        gallery.set_discarded(video, False)
        info = gallery.load_publish_info(video)
        assert info["discard_reason"] is None
        assert info["discarded_at"] is None

    def test_publishing_preserves_the_title_it_did_not_send(self, video):
        from core import gallery
        gallery.save_title_and_description(video, "God Already Knew", "A body.")
        gallery.save_publish_info(video, {"youtube_url": "https://yt.example/1"})
        info = gallery.load_publish_info(video)
        assert info["title"] == "God Already Knew"
        assert info["description"] == "A body."


class TestInsights:
    def test_empty_library_produces_a_usable_shape(self, config_path, monkeypatch):
        from core import insights
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", config_path)
        data = insights.collect()
        assert data["totals"]["total"] == 0
        assert insights.headline(data) == "Nothing generated yet."

    def test_headline_leads_with_the_discard_problem(self):
        from core import insights
        data = {
            "totals": {"total": 10, "discard_rate": 0.6, "published": 2,
                       "keep_rate": 0.4, "awaiting_review": 2},
            "discard_reasons": {"rows": [{"label": "Footage didn't fit", "count": 5}]},
            "quality": {"footage_repeat_rate": 0.0},
        }
        headline = insights.headline(data)
        assert "60%" in headline and "footage" in headline.lower()


class TestCsrf:
    """There was no CSRF protection on any POST, including the one that
    permanently deletes a channel's entire output tree."""

    def test_post_without_a_token_is_rejected(self, client):
        response = client.post("/channels/test_channel/archive")
        assert response.status_code == 400

    def test_post_with_a_wrong_token_is_rejected(self, client):
        csrf(client)   # establish a session
        response = client.post("/channels/test_channel/archive",
                               data={"csrf_token": "not-the-token"})
        assert response.status_code == 400

    def test_post_with_the_right_token_succeeds(self, client):
        token = csrf(client)
        response = client.post("/channels/test_channel/archive",
                               data={"csrf_token": token})
        assert response.status_code == 302

    def test_json_api_accepts_the_header(self, client):
        token = csrf(client)
        response = client.post("/api/channels/reorder",
                               json={"keys": ["test_channel"]},
                               headers={"X-CSRF-Token": token})
        assert response.status_code == 200

    def test_json_api_without_the_header_is_rejected(self, client):
        response = client.post("/api/channels/reorder", json={"keys": ["test_channel"]})
        assert response.status_code == 400

    def test_get_needs_no_token(self, client):
        assert client.get("/").status_code == 200


class TestPathTraversal:
    @pytest.mark.parametrize("relpath", [
        "../../../etc/passwd",
        "..%2f..%2fsecrets",
        "test_channel/../../config/channels.json",
    ])
    def test_video_route_refuses_to_escape_output(self, client, relpath):
        assert client.get(f"/videos/{relpath}").status_code in (400, 403, 404)

    def test_logo_asset_route_refuses_to_escape(self, client):
        response = client.get("/channels/test_channel/logo-assets/../../../config/channels.json")
        assert response.status_code in (400, 403, 404)


class TestErrorHandling:
    def test_api_errors_come_back_as_json_not_html(self, client):
        response = client.get("/api/jobs/nonexistent-job-id")
        assert response.status_code == 404
        assert response.is_json
        assert "error" in response.get_json()

    def test_error_messages_carry_no_traceback(self, client):
        body = client.get("/channels/nope").get_data(as_text=True)
        assert "Traceback" not in body
        assert ".py" not in body.split("<style")[0]


class TestSettingsSave:
    def test_saving_settings_preserves_fields_the_form_omits(self, client, config_path):
        """The wipe-on-save bug, end to end: the settings form has no
        input for socials, so a save used to blank them."""
        from core.channels import load_channels, save_channel

        channel = load_channels(config_path)["test_channel"]
        channel.socials.youtube_url = "https://youtube.example/mine"
        save_channel(channel, config_path)

        token = csrf(client)
        response = client.post("/channels/test_channel/settings", data={
            "csrf_token": token, "content_mode": "topic", "voice": "voice-id",
            "style_prompt": "Write something.", "topics": "coffee",
            "channel_display_name": "Test Channel",
        })
        assert response.status_code == 302

        reloaded = load_channels(config_path)["test_channel"]
        assert reloaded.socials.youtube_url == "https://youtube.example/mine"

    def test_invalid_settings_are_rejected_with_a_reason(self, client):
        token = csrf(client)
        response = client.post("/channels/test_channel/settings", data={
            "csrf_token": token, "content_mode": "topic", "voice": "",
            "style_prompt": "x", "topics": "coffee",
        })
        assert response.status_code == 400
        assert "voice" in response.get_data(as_text=True).lower()


class TestPublishTracking:
    @pytest.fixture
    def video(self, tmp_path):
        directory = tmp_path / "out" / "2026-09-03"
        directory.mkdir(parents=True)
        path = directory / "john_3_16.mp4"
        path.write_bytes(b"not a real video")
        return path

    def test_publishing_stamps_a_date_once(self, video):
        from core import gallery

        first = gallery.save_publish_info(video, {"youtube_url": "https://yt.example/1"})
        assert first["published_at"]

        # Editing an already-published video must not reset the stamp:
        # it answers "when did this go out", not "when was it last edited".
        second = gallery.save_publish_info(video, {"youtube_url": "https://yt.example/2",
                                                   "tiktok_url": "https://tt.example/1"})
        assert second["published_at"] == first["published_at"]

    def test_clearing_every_link_unpublishes(self, video):
        from core import gallery

        gallery.save_publish_info(video, {"youtube_url": "https://yt.example/1"})
        cleared = gallery.save_publish_info(video, {})
        assert cleared["published_at"] is None
        assert not gallery.is_published(cleared)

    def test_discarding_preserves_publish_state(self, video):
        from core import gallery

        gallery.save_publish_info(video, {"youtube_url": "https://yt.example/1"})
        gallery.set_discarded(video, True)
        info = gallery.load_publish_info(video)
        assert info["discarded"]
        assert info["youtube_url"] == "https://yt.example/1"

        gallery.set_discarded(video, False)
        assert not gallery.load_publish_info(video)["discarded"]

    def test_counts_treat_discarded_as_not_a_deliverable(self, video, tmp_path):
        from core import gallery

        second = video.with_name("job_1_8.mp4")
        second.write_bytes(b"x")
        gallery.set_discarded(second, True)

        counts = gallery.video_state_counts(str(tmp_path / "out"))
        assert counts["total"] == 2
        assert counts["active"] == 1
        assert counts["discarded"] == 1

    def test_corrupt_sidecar_does_not_break_the_listing(self, video):
        from core import gallery

        video.with_name("john_3_16_publish.json").write_text("{broken", encoding="utf-8")
        info = gallery.load_publish_info(video)
        assert info["published_at"] is None


class TestCaptionPreview:
    """The Look tab's preview.

    Worth testing rather than eyeballing because it renders from *unsaved*
    form values, which means it is fed half-typed input on every keystroke
    — a partially entered hex colour, a cleared number field. Every one of
    those must produce a frame, not a 500 in the middle of typing.
    """

    def test_renders_a_png(self, client):
        response = client.post("/api/caption-preview", data={
            "font_face": "impact", "font_size": "84", "stroke_width": "6",
            "base_color": "#FFFFFF", "highlight_color": "#FF3B30",
            "stroke_color": "#000000",
        }, headers={"X-CSRF-Token": csrf(client)})
        assert response.status_code == 200
        assert response.mimetype == "image/png"
        assert response.get_data()[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.parametrize("payload", [
        {},                                                  # nothing typed yet
        {"base_color": "#FF"},                               # mid-type
        {"font_size": "", "stroke_width": ""},               # cleared
        {"font_size": "1e999"},                              # overflows int()
        {"font_face": "no_such_face", "stroke_color": "red"},
        {"font_size": "-40", "stroke_width": "9999"},        # out of range
    ])
    def test_bad_input_still_renders(self, client, payload):
        response = client.post("/api/caption-preview", data=payload,
                               headers={"X-CSRF-Token": csrf(client)})
        assert response.status_code == 200
        assert response.mimetype == "image/png"

    def test_requires_csrf(self, client):
        assert client.post("/api/caption-preview", data={}).status_code == 400


class TestLookSettings:
    def test_form_offers_every_installed_face(self, client):
        from core import fonts

        html = client.get("/channels/test_channel/settings").get_data(as_text=True)
        assert 'name="style_font_face"' in html
        for face in fonts.available():
            assert f'value="{face.key}"' in html

    def test_font_face_saves(self, client):
        from core.channels import load_channels

        client.post("/channels/test_channel/settings", data={
            "channel_display_name": "Test Channel", "content_mode": "topic",
            "voice": "voice-id", "style_prompt": "Write something.",
            "topics": "coffee", "style_font_face": "impact",
            "csrf_token": csrf(client),
        })
        assert load_channels(validate=False)["test_channel"].style.font_face == "impact"

    def test_unknown_font_face_is_rejected_not_stored(self, client):
        """An unresolvable face would fall back silently at render time,
        months after the setting was made."""
        from core.channels import load_channels

        client.post("/channels/test_channel/settings", data={
            "channel_display_name": "Test Channel", "content_mode": "topic",
            "voice": "voice-id", "style_prompt": "Write something.",
            "topics": "coffee", "style_font_face": "../../etc/passwd",
            "csrf_token": csrf(client),
        })
        assert load_channels(validate=False)["test_channel"].style.font_face == "arial_bold"
