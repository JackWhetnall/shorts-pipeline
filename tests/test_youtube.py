"""
YouTube upload: credentials, the OAuth handshake, and the upload protocol.

Every network call is stubbed. Nothing here touches Google, so the suite
costs nothing and works offline — which matters more than usual, because
the failure modes worth testing (a refused refresh token, a quota
ceiling, a video forced to private) are ones you cannot conveniently
produce on demand against the real service anyway.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from core import youtube
from core.errors import PipelineError


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point every credential path at a throwaway directory."""
    monkeypatch.setattr(youtube, "CLIENT_PATH", tmp_path / "youtube_client.json")
    monkeypatch.setattr(youtube, "TOKENS_DIR", tmp_path / "tokens")
    monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRET", raising=False)
    return tmp_path


def _session_start(*args, **kwargs):
    return FakeResponse(200, {}, {"Location": "https://upload.example/session"})


class TestCredentials:
    def test_absent_client_is_not_an_exception_for_callers_that_ask(self, isolated):
        assert youtube.is_configured() is False

    def test_absent_client_raises_something_actionable_when_used(self, isolated):
        with pytest.raises(youtube.NotConnected) as caught:
            youtube.client_config()
        assert "OAuth client" in caught.value.user_message

    def test_round_trips(self, isolated):
        youtube.save_client_config("id-1", "secret-1")
        assert youtube.client_config() == {"client_id": "id-1", "client_secret": "secret-1"}

    def test_environment_wins_over_the_file(self, isolated, monkeypatch):
        youtube.save_client_config("from-file", "secret")
        monkeypatch.setenv("YOUTUBE_CLIENT_ID", "from-env")
        monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "env-secret")
        assert youtube.client_config()["client_id"] == "from-env"

    def test_accepts_the_json_google_actually_downloads(self, isolated):
        """The console hands you {"web": {...}}, not a flat object. Making
        people unwrap it by hand is a step that goes wrong silently."""
        youtube.CLIENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        youtube.CLIENT_PATH.write_text(json.dumps(
            {"web": {"client_id": "wrapped", "client_secret": "s",
                     "auth_uri": "...", "token_uri": "..."}}))
        assert youtube.client_config()["client_id"] == "wrapped"

    def test_damaged_file_says_so_rather_than_crashing(self, isolated):
        youtube.CLIENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        youtube.CLIENT_PATH.write_text("{not json")
        with pytest.raises(youtube.NotConnected) as caught:
            youtube.client_config()
        assert "damaged" in caught.value.user_message


class TestTokens:
    def test_unknown_channel_is_simply_not_connected(self, isolated):
        assert youtube.connection("nobody") == {
            "connected": False, "account": "", "connected_at": ""}

    def test_damaged_token_file_reads_as_disconnected(self, isolated):
        youtube.TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        (youtube.TOKENS_DIR / "c.json").write_text("{broken")
        assert youtube.connection("c")["connected"] is False

    def test_a_channel_key_cannot_escape_the_token_directory(self, isolated):
        from core.paths import PathTraversalError

        with pytest.raises(PathTraversalError):
            youtube.load_tokens("../../secrets")

    def test_disconnect_removes_the_token(self, isolated):
        youtube.save_tokens("c", {"refresh_token": "r"})
        assert youtube.connection("c")["connected"]
        youtube.disconnect("c")
        assert not youtube.connection("c")["connected"]


class TestAuthorization:
    def test_asks_for_a_refresh_token_explicitly(self, isolated):
        """Without prompt=consent, Google returns a refresh token only on
        the very first authorization ever granted — so reconnecting a
        channel would yield an access token with nothing to renew it."""
        youtube.save_client_config("id", "secret")
        url = youtube.authorize_url("http://localhost:5000/youtube/callback", "st")
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "state=st" in url
        assert "youtube.upload" in url

    def test_a_grant_without_a_refresh_token_is_refused(self, isolated, monkeypatch):
        youtube.save_client_config("id", "secret")
        monkeypatch.setattr(youtube.requests, "post",
                            lambda *a, **k: FakeResponse(200, {"access_token": "a"}))
        with pytest.raises(youtube.YouTubeError) as caught:
            youtube.exchange_code("code", "uri")
        assert "long-term access" in caught.value.user_message

    def test_reads_the_account_address_from_the_id_token(self, isolated, monkeypatch):
        payload = base64.urlsafe_b64encode(
            json.dumps({"email": "channel@example.com"}).encode()).decode().rstrip("=")
        youtube.save_client_config("id", "secret")
        monkeypatch.setattr(youtube.requests, "post", lambda *a, **k: FakeResponse(
            200, {"refresh_token": "r", "access_token": "a", "expires_in": 3600,
                  "id_token": "header." + payload + ".signature"}))
        assert youtube.exchange_code("code", "uri")["account"] == "channel@example.com"

    def test_a_malformed_id_token_costs_the_label_not_the_connection(
            self, isolated, monkeypatch):
        youtube.save_client_config("id", "secret")
        monkeypatch.setattr(youtube.requests, "post", lambda *a, **k: FakeResponse(
            200, {"refresh_token": "r", "id_token": "garbage"}))
        tokens = youtube.exchange_code("code", "uri")
        assert tokens["refresh_token"] == "r"
        assert tokens["account"] == ""


class TestAccessToken:
    def test_a_live_token_is_reused(self, isolated):
        youtube.save_client_config("id", "secret")
        youtube.save_tokens("c", {"refresh_token": "r", "access_token": "live",
                                  "expires_at": time.time() + 3600})
        assert youtube.access_token("c") == "live"

    def test_an_expired_token_is_refreshed_and_stored(self, isolated, monkeypatch):
        youtube.save_client_config("id", "secret")
        youtube.save_tokens("c", {"refresh_token": "r", "access_token": "stale",
                                  "expires_at": time.time() - 1})
        monkeypatch.setattr(youtube.requests, "post", lambda *a, **k: FakeResponse(
            200, {"access_token": "fresh", "expires_in": 3600}))
        assert youtube.access_token("c") == "fresh"
        assert youtube.load_tokens("c")["access_token"] == "fresh"

    def test_a_token_about_to_expire_is_refreshed_early(self, isolated, monkeypatch):
        """A token with 30 seconds left must not be handed to an upload
        that will take longer than that."""
        youtube.save_client_config("id", "secret")
        youtube.save_tokens("c", {"refresh_token": "r", "access_token": "nearly",
                                  "expires_at": time.time() + 30})
        monkeypatch.setattr(youtube.requests, "post", lambda *a, **k: FakeResponse(
            200, {"access_token": "fresh", "expires_in": 3600}))
        assert youtube.access_token("c") == "fresh"

    @pytest.mark.parametrize("status", [400, 401])
    def test_a_rejected_refresh_token_explains_the_weekly_expiry(
            self, isolated, monkeypatch, status):
        youtube.save_client_config("id", "secret")
        youtube.save_tokens("c", {"refresh_token": "dead", "expires_at": 0})
        monkeypatch.setattr(youtube.requests, "post",
                            lambda *a, **k: FakeResponse(status, {"error": "invalid_grant"}))
        with pytest.raises(youtube.NotConnected) as caught:
            youtube.access_token("c")
        assert "7 days" in caught.value.user_message

    def test_an_unconnected_channel_says_to_connect_it(self, isolated):
        youtube.save_client_config("id", "secret")
        with pytest.raises(youtube.NotConnected) as caught:
            youtube.access_token("nobody")
        assert "connected" in caught.value.user_message


class TestUpload:
    @pytest.fixture
    def ready(self, isolated, tmp_path):
        youtube.save_client_config("id", "secret")
        youtube.save_tokens("c", {"refresh_token": "r", "access_token": "live",
                                  "expires_at": time.time() + 3600})
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"x" * 1000)
        return video

    def _stub(self, monkeypatch, put_responses):
        monkeypatch.setattr(youtube.requests, "post", _session_start)
        calls = iter(put_responses)
        monkeypatch.setattr(youtube.requests, "put", lambda *a, **k: next(calls))

    def _capture_metadata(self, monkeypatch, sent):
        def fake_post(url, params=None, headers=None, data=None, timeout=None):
            sent.update(json.loads(data))
            return _session_start()

        monkeypatch.setattr(youtube.requests, "post", fake_post)
        monkeypatch.setattr(youtube.requests, "put",
                            lambda *a, **k: FakeResponse(200, {"id": "x", "status": {}}))

    def test_uploads_and_returns_a_watch_url(self, ready, monkeypatch):
        self._stub(monkeypatch, [FakeResponse(
            200, {"id": "abc123", "status": {"privacyStatus": "public"}})])
        result = youtube.upload("c", ready, "A title", "A description")
        assert result["url"] == "https://www.youtube.com/watch?v=abc123"
        assert result["locked_private"] is False

    def test_reports_when_youtube_forces_a_video_private(self, ready, monkeypatch):
        """The documented behaviour of an unaudited API project. The caller
        has to be able to say so — a silently private video is discovered
        days later."""
        self._stub(monkeypatch, [FakeResponse(
            200, {"id": "abc", "status": {"privacyStatus": "private"}})])
        result = youtube.upload("c", ready, "T", "D", privacy="public")
        assert result["locked_private"] is True
        assert result["privacy_granted"] == "private"

    def test_resumes_from_the_byte_range_youtube_reports(self, ready, monkeypatch):
        """A partially accepted chunk must resynchronise on YouTube's count,
        not on ours, or the upload silently corrupts."""
        seen = []
        monkeypatch.setattr(youtube.requests, "post", _session_start)
        responses = iter([FakeResponse(308, headers={"Range": "bytes=0-499"}),
                          FakeResponse(200, {"id": "x", "status": {}})])

        def fake_put(url, headers=None, data=None, timeout=None):
            seen.append(headers["Content-Range"])
            return next(responses)

        monkeypatch.setattr(youtube.requests, "put", fake_put)
        youtube.upload("c", ready, "T", "D")
        assert seen == ["bytes 0-999/1000", "bytes 500-999/1000"]

    def test_quota_exhaustion_is_named(self, ready, monkeypatch):
        self._stub(monkeypatch, [FakeResponse(
            403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})])
        with pytest.raises(youtube.YouTubeError) as caught:
            youtube.upload("c", ready, "T", "D")
        assert "quota" in caught.value.user_message.lower()

    def test_the_upload_limit_is_distinguished_from_quota(self, ready, monkeypatch):
        """Different cause, different fix — one waits for midnight Pacific,
        the other needs the account verified."""
        self._stub(monkeypatch, [FakeResponse(
            400, {"error": {"errors": [{"reason": "uploadLimitExceeded"}]}})])
        with pytest.raises(youtube.YouTubeError) as caught:
            youtube.upload("c", ready, "T", "D")
        assert "verifying the account" in caught.value.user_message

    def test_a_missing_file_fails_before_any_network_call(self, ready, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("should not have called YouTube")

        monkeypatch.setattr(youtube.requests, "post", explode)
        with pytest.raises(youtube.YouTubeError):
            youtube.upload("c", ready.parent / "gone.mp4", "T", "D")

    def test_an_empty_title_is_refused_locally(self, ready, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("should not have called YouTube")

        monkeypatch.setattr(youtube.requests, "post", explode)
        with pytest.raises(youtube.YouTubeError) as caught:
            youtube.upload("c", ready, "   ", "D")
        assert "title" in caught.value.user_message

    def test_over_long_text_is_trimmed_rather_than_rejected_by_google(
            self, ready, monkeypatch):
        sent = {}
        self._capture_metadata(monkeypatch, sent)
        youtube.upload("c", ready, "T" * 300, "D" * 9000)
        assert len(sent["snippet"]["title"]) == youtube.MAX_TITLE
        assert len(sent["snippet"]["description"]) == youtube.MAX_DESCRIPTION

    def test_an_unknown_privacy_value_falls_back_to_private(self, ready, monkeypatch):
        """Failing safe: an unrecognised setting must not publish something
        publicly by accident."""
        sent = {}
        self._capture_metadata(monkeypatch, sent)
        youtube.upload("c", ready, "T", "D", privacy="everyone")
        assert sent["status"]["privacyStatus"] == "private"

    def test_every_failure_carries_a_readable_message(self, ready, monkeypatch):
        self._stub(monkeypatch, [FakeResponse(500, text="<html>Server Error</html>")])
        with pytest.raises(PipelineError) as caught:
            youtube.upload("c", ready, "T", "D")
        assert "<html>" not in caught.value.user_message


class TestWebRoutes:
    """The OAuth callback is the one route here that acts on data supplied
    by a third party through the user's browser, so its refusals are the
    security boundary."""

    @pytest.fixture
    def client(self, isolated, tmp_path, monkeypatch):
        from core.channels import ChannelConfig, channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        channel = ChannelConfig(
            key="test_channel", channel_display_name="Test Channel",
            content_mode="topic", voice="v", style_prompt="Write something.",
            topics=["coffee"])
        channel.output_dir = str(tmp_path / "out")
        write_raw({"test_channel": channel_to_sparse_dict(channel)}, path)

        app = create_app()
        app.config.update(TESTING=True)
        with app.test_client() as test_client:
            yield test_client

    def _csrf(self, client):
        html = client.get("/").get_data(as_text=True)
        marker = 'name="csrf-token" content="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_setup_page_renders_without_credentials(self, client):
        response = client.get("/youtube/setup")
        assert response.status_code == 200
        assert "redirect" in response.get_data(as_text=True).lower()

    def test_setup_page_shows_the_redirect_uri_to_register(self, client):
        """It has to match what Google has character for character, and it
        depends on the port the app is running on."""
        html = client.get("/youtube/setup").get_data(as_text=True)
        assert "/youtube/callback" in html

    def test_saving_credentials_makes_the_connect_links_appear(self, client):
        client.post("/youtube/setup", data={
            "client_id": "id.apps.googleusercontent.com",
            "client_secret": "shh", "csrf_token": self._csrf(client)})
        html = client.get("/youtube/setup").get_data(as_text=True)
        assert "/channels/test_channel/youtube/connect" in html

    def test_callback_refuses_a_state_this_browser_did_not_start(self, client):
        """Without this, anyone able to make the browser follow a link
        could finish an authorization against a channel of their choosing."""
        assert client.get("/youtube/callback?code=x&state=forged").status_code == 400

    def test_callback_refuses_a_replayed_state(self, client, monkeypatch):
        youtube.save_client_config("id", "secret")
        monkeypatch.setattr(youtube.requests, "post", lambda *a, **k: FakeResponse(
            200, {"refresh_token": "r", "access_token": "a", "expires_in": 3600}))

        client.get("/channels/test_channel/youtube/connect")
        with client.session_transaction() as session:
            state = session["_youtube_oauth"]["state"]

        assert client.get(f"/youtube/callback?code=x&state={state}").status_code == 302
        # The state is consumed on use, so the same link cannot be replayed.
        assert client.get(f"/youtube/callback?code=x&state={state}").status_code == 400

    def test_a_declined_consent_screen_is_not_an_error_page(self, client):
        youtube.save_client_config("id", "secret")
        client.get("/channels/test_channel/youtube/connect")
        with client.session_transaction() as session:
            state = session["_youtube_oauth"]["state"]

        response = client.get(f"/youtube/callback?error=access_denied&state={state}")
        assert response.status_code == 302
        assert "/settings" in response.headers["Location"]

    def test_connecting_without_credentials_goes_to_setup(self, client):
        response = client.get("/channels/test_channel/youtube/connect")
        assert response.status_code == 302
        assert "/youtube/setup" in response.headers["Location"]

    def test_disconnect_requires_csrf(self, client):
        youtube.save_tokens("test_channel", {"refresh_token": "r"})
        assert client.post(
            "/channels/test_channel/youtube/disconnect").status_code == 400
        assert youtube.connection("test_channel")["connected"]

    def test_upload_route_requires_the_channel(self, client, tmp_path, monkeypatch):
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        (out / "clip.mp4").write_bytes(b"v")
        monkeypatch.setattr("web.helpers.OUTPUT_DIR", out)

        response = client.post("/api/videos/clip.mp4/upload-youtube",
                               json={}, headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 400

    def test_upload_route_refuses_a_video_that_already_has_a_link(
            self, client, tmp_path, monkeypatch):
        """Uploading twice would put a duplicate on the channel, which is
        exactly the mass-production signature this project avoids."""
        from core import gallery

        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        video = out / "clip.mp4"
        video.write_bytes(b"v")
        monkeypatch.setattr("web.helpers.OUTPUT_DIR", out)
        gallery.save_publish_info(video, {"youtube_url": "https://youtu.be/x"})

        response = client.post(
            "/api/videos/clip.mp4/upload-youtube",
            json={"channel_key": "test_channel"},
            headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 400
        assert "already" in response.get_json()["error"]

    def test_upload_failure_returns_a_sentence_not_a_traceback(
            self, client, tmp_path, monkeypatch):
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        (out / "clip.mp4").write_bytes(b"v")
        monkeypatch.setattr("web.helpers.OUTPUT_DIR", out)

        response = client.post(
            "/api/videos/clip.mp4/upload-youtube",
            json={"channel_key": "test_channel", "title": "T"},
            headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 502
        assert "connected" in response.get_json()["error"]
