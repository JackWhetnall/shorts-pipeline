"""
Uploading a finished video to YouTube.

## What this can and cannot do

It uploads the file, the title, the description and the tags, and sets the
privacy status. That removes the whole manual step: find the mp4 among its
sidecars, drag it into Studio, paste the title, paste the description.

It does **not** necessarily make the video public. Google's own
documentation on `videos.insert` states that "all videos uploaded via the
videos.insert endpoint from unverified API projects created after 28 July
2020 will be restricted to private viewing mode", regardless of the
`privacyStatus` sent. Lifting that requires a compliance audit of the API
project — a review Google runs, not a checkbox.

So this is honest about it: `upload()` reports back the privacy status
YouTube actually assigned, not the one that was requested, and the UI says
so. Until the project is audited, the workflow is "upload from here, then
flip to public in Studio" — still most of the work, and the part that
scales.

## Quotas

`videos.insert` costs 1 unit from the Video Uploads bucket, which allows
100 calls a day. Two videos a day across several channels is nowhere near
it.

## Why raw HTTP rather than google-api-python-client

The official client pulls in google-api-core, protobuf, googleapis-common
-protos and several more for what is, here, three HTTP requests: a token
refresh, a resumable-session start, and a PUT. This project's other
integrations (ElevenLabs, Pexels, Pixabay) are `requests` calls for the
same reason.

## Credentials

Per installation, not per channel: one Google Cloud project can hold the
OAuth client for every channel. Tokens ARE per channel, because each
channel is a different YouTube account.

Nothing here creates a Google account, a Cloud project or an OAuth client.
The setup page explains what to make and links to where.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from core.errors import ExternalServiceError, PipelineError
from core.logging_setup import get_logger
from core.paths import PROJECT_ROOT, safe_join

log = get_logger(__name__)

CLIENT_PATH = PROJECT_ROOT / "config" / "youtube_client.json"
TOKENS_DIR = PROJECT_ROOT / "config" / "youtube_tokens"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

# `youtube.upload` is all that videos.insert needs. `openid email` is added
# only so the settings page can say WHICH Google account a channel is
# connected to — with several channels, connecting the wrong account is an
# easy mistake and an expensive one to notice late. It is not a YouTube
# scope and grants no access to the account's data beyond the address.
#
# The two read-only scopes are for core.audience: views and likes from the
# Data API, retention and subscribers from the Analytics API. Without them
# nothing measures whether anyone watches what this pipeline makes. Neither
# can change anything on the channel.
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
SCOPES = ("openid", "email", UPLOAD_SCOPE, READ_SCOPE, ANALYTICS_SCOPE)

# 8 MB chunks. Big enough that the per-chunk overhead is irrelevant, small
# enough that a dropped connection loses seconds rather than the upload.
CHUNK_BYTES = 8 * 1024 * 1024

# YouTube's own limits, enforced here so a too-long description fails with
# a sentence rather than a 400 from Google.
MAX_TITLE = 100
MAX_DESCRIPTION = 5000

PRIVACY_CHOICES = ("public", "unlisted", "private")

# https://developers.google.com/youtube/v3/docs/videoCategories/list — 22
# is "People & Blogs", the least wrong default for a channel this pipeline
# would produce. Configurable per channel.
DEFAULT_CATEGORY_ID = "22"


class YouTubeError(ExternalServiceError):
    """YouTube refused or failed something."""

    def __init__(self, message: str, *, user_message: str = None, status: int = None):
        super().__init__("YouTube", message, user_message=user_message, status=status)


class NotConnected(PipelineError):
    """This installation or channel isn't set up to upload yet.

    Separate from YouTubeError because the fix is different in kind:
    nothing is wrong with YouTube, there is simply no credential yet, and
    the UI offers a "connect" button rather than a "try again".
    """


# --- credentials ------------------------------------------------------

def client_config() -> dict:
    """The OAuth client id and secret for this installation.

    Environment first so a deployment can inject them without writing a
    file, then `config/youtube_client.json`, which is what the setup page
    writes and what `.gitignore` excludes.
    """
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return {"client_id": client_id, "client_secret": client_secret}

    if CLIENT_PATH.exists():
        try:
            data = json.loads(CLIENT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise NotConnected(
                "config/youtube_client.json isn't valid JSON.",
                user_message="Your saved YouTube credentials are damaged. "
                             "Re-enter them on the YouTube setup page.",
            )
        # Google's console downloads these wrapped in {"web": {...}} or
        # {"installed": {...}}; accept the file as downloaded.
        data = data.get("web") or data.get("installed") or data
        if data.get("client_id") and data.get("client_secret"):
            return {"client_id": data["client_id"].strip(),
                    "client_secret": data["client_secret"].strip()}

    raise NotConnected(
        "No YouTube OAuth client configured.",
        user_message="This channel isn't set up to upload to YouTube yet. "
                     "Add your Google OAuth client on the YouTube setup page.",
    )


def is_configured() -> bool:
    """Whether an OAuth client exists, without raising if it doesn't."""
    try:
        client_config()
        return True
    except NotConnected:
        return False


def save_client_config(client_id: str, client_secret: str) -> None:
    CLIENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLIENT_PATH.write_text(json.dumps(
        {"client_id": client_id.strip(), "client_secret": client_secret.strip()},
        indent=2), encoding="utf-8")


def forget_client_config() -> None:
    CLIENT_PATH.unlink(missing_ok=True)


# --- per-channel tokens -----------------------------------------------

def _token_path(channel_key: str) -> Path:
    # safe_join because the key reaches here from a URL.
    return safe_join(TOKENS_DIR, f"{channel_key}.json")


def load_tokens(channel_key: str) -> dict:
    path = _token_path(channel_key)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning(f"{channel_key}: YouTube token file is damaged; treating as disconnected")
        return {}


def save_tokens(channel_key: str, tokens: dict) -> None:
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    _token_path(channel_key).write_text(json.dumps(tokens, indent=2), encoding="utf-8")


def disconnect(channel_key: str) -> None:
    _token_path(channel_key).unlink(missing_ok=True)


def connection(channel_key: str) -> dict:
    """What the UI needs to say about this channel's YouTube link."""
    tokens = load_tokens(channel_key)
    granted = set((tokens.get("scope") or "").split())
    return {
        "connected": bool(tokens.get("refresh_token")),
        "account": tokens.get("account", ""),
        "connected_at": tokens.get("connected_at", ""),
        # A channel connected before the statistics scopes existed can
        # still upload, but needs one reconnect before its numbers can be
        # read. Tokens saved then didn't record their scopes at all.
        "stats": {READ_SCOPE, ANALYTICS_SCOPE} <= granted,
    }


# --- the OAuth dance --------------------------------------------------

def authorize_url(redirect_uri: str, state: str) -> str:
    """Where to send the browser to grant access.

    `access_type=offline` with `prompt=consent` is what produces a refresh
    token. Without the explicit prompt Google returns one only on the very
    first authorization ever granted to the client — so reconnecting a
    channel after a token was revoked would silently yield an access token
    that expires in an hour and nothing to renew it with.
    """
    config = client_config()
    params = {
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return AUTH_URL + "?" + urlencode(params)


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Turn the callback's one-time code into stored tokens."""
    config = client_config()
    response = requests.post(TOKEN_URL, data={
        "code": code,
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=30)
    payload = _json_or_raise(response, "exchange the sign-in code")

    if not payload.get("refresh_token"):
        raise YouTubeError(
            "Google returned no refresh token.",
            user_message="Google didn't grant long-term access. Disconnect "
                         "this channel in your Google account's security "
                         "settings, then connect it here again.",
        )
    return {
        "refresh_token": payload["refresh_token"],
        "access_token": payload.get("access_token", ""),
        "expires_at": time.time() + float(payload.get("expires_in", 0)),
        "account": _email_from_id_token(payload.get("id_token", "")),
        "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # What was actually granted: the consent screen lets a person
        # untick a scope, so what was asked for isn't proof.
        "scope": payload.get("scope", ""),
    }


def _email_from_id_token(id_token: str) -> str:
    """The signed-in address, for showing which account is connected.

    Read without verifying the signature, which is safe *here* and would
    not be elsewhere: this token came back in the body of a direct HTTPS
    POST to Google's own token endpoint, not through a browser redirect,
    so there is no untrusted party in the path. It is also used only as a
    label — nothing is authorized on the strength of it.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        return ""
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded)).get("email", "")
    except (ValueError, json.JSONDecodeError):
        return ""


def access_token(channel_key: str) -> str:
    """A usable access token, refreshing if the stored one has expired.

    Refreshed 60 seconds early so a token cannot expire midway through an
    upload that started with it.
    """
    tokens = load_tokens(channel_key)
    if not tokens.get("refresh_token"):
        raise NotConnected(
            f"{channel_key} has no YouTube refresh token.",
            user_message="This channel isn't connected to YouTube. Connect it "
                         "from the channel's settings, then try again.",
        )
    if tokens.get("access_token") and time.time() < tokens.get("expires_at", 0) - 60:
        return tokens["access_token"]

    config = client_config()
    response = requests.post(TOKEN_URL, data={
        "refresh_token": tokens["refresh_token"],
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "grant_type": "refresh_token",
    }, timeout=30)

    if response.status_code in (400, 401):
        # The refresh token is dead: revoked, or expired because the OAuth
        # consent screen is still in "Testing", where Google expires them
        # after seven days. Say which, because the fix differs.
        raise NotConnected(
            f"{channel_key}: YouTube refresh token rejected ({response.status_code}).",
            user_message="YouTube access for this channel has expired. Reconnect "
                         "it from the channel's settings. If this keeps happening "
                         "every week, publish your Google OAuth consent screen — "
                         "apps left in Testing have access expire after 7 days.",
        )
    payload = _json_or_raise(response, "refresh YouTube access")

    tokens["access_token"] = payload.get("access_token", "")
    tokens["expires_at"] = time.time() + float(payload.get("expires_in", 0))
    save_tokens(channel_key, tokens)
    return tokens["access_token"]


# --- uploading --------------------------------------------------------

def upload(channel_key: str, video_path: Path, title: str, description: str,
           tags=(), privacy: str = "public", category_id: str = DEFAULT_CATEGORY_ID,
           on_progress=None) -> dict:
    """Upload one video. Returns its id, URL, and the privacy YouTube gave it.

    Resumable rather than a single POST: a multipart upload that fails at
    90% has to start over, and these are 20-40 MB files.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise YouTubeError(f"{video_path} does not exist.",
                           user_message="That video file is missing.")

    title = (title or video_path.stem).strip()[:MAX_TITLE]
    if not title:
        raise YouTubeError("Empty title.",
                           user_message="Give the video a title before uploading it.")
    if privacy not in PRIVACY_CHOICES:
        privacy = "private"

    metadata = {
        "snippet": {
            "title": title,
            "description": (description or "")[:MAX_DESCRIPTION],
            "tags": [t for t in tags if t][:50],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    token = access_token(channel_key)
    size = video_path.stat().st_size
    session_url = _start_session(token, metadata, size)
    payload = _send_chunks(session_url, video_path, size, on_progress)

    granted = payload.get("status", {}).get("privacyStatus", "")
    video_id = payload.get("id", "")
    if granted and granted != privacy:
        # Not an error — this is the documented behaviour of an unaudited
        # API project, and the caller needs to be able to say so.
        log.warning(f"{channel_key}: asked YouTube for {privacy}, got {granted}")

    return {
        "id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        "privacy_requested": privacy,
        "privacy_granted": granted or privacy,
        "locked_private": bool(granted == "private" and privacy != "private"),
    }


def _start_session(token: str, metadata: dict, size: int) -> str:
    response = requests.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
        data=json.dumps(metadata).encode("utf-8"),
        timeout=60,
    )
    if response.status_code >= 400:
        raise _api_error(response, "start the upload")
    location = response.headers.get("Location")
    if not location:
        raise YouTubeError("No resumable session URL returned.",
                           user_message="YouTube didn't accept the upload. Try again.")
    return location


def _send_chunks(session_url: str, video_path: Path, size: int, on_progress) -> dict:
    """PUT the file a chunk at a time, reporting progress.

    308 means "keep going": YouTube replies with the byte range it has, and
    the next chunk starts from there rather than from where we think we
    are, so a partially accepted chunk resynchronises instead of corrupting
    the upload.
    """
    sent = 0
    with video_path.open("rb") as handle:
        while sent < size:
            handle.seek(sent)
            chunk = handle.read(CHUNK_BYTES)
            end = sent + len(chunk) - 1
            response = requests.put(
                session_url,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {sent}-{end}/{size}",
                },
                data=chunk,
                timeout=300,
            )

            if response.status_code in (200, 201):
                if on_progress:
                    on_progress(100.0)
                return response.json()

            if response.status_code == 308:
                received = response.headers.get("Range", "")
                sent = int(received.split("-")[-1]) + 1 if "-" in received else sent + len(chunk)
                if on_progress:
                    on_progress(min(99.0, sent / size * 100))
                continue

            raise _api_error(response, "upload the video")

    raise YouTubeError("Upload ended without a response from YouTube.",
                       user_message="The upload finished but YouTube didn't confirm "
                                    "it. Check your channel before uploading again.")


def _api_error(response, doing: str) -> YouTubeError:
    """Turn a Google error body into something worth reading.

    Two of these are common enough and confusing enough to name: the quota
    ceiling, and the upload limit that a new or unverified account has,
    which reports as `uploadLimitExceeded` and has nothing to do with
    quota.
    """
    detail = response.text[:400]
    reason = ""
    try:
        errors = response.json().get("error", {}).get("errors", [])
        reason = errors[0].get("reason", "") if errors else ""
    except (ValueError, AttributeError, IndexError):
        pass

    messages = {
        "quotaExceeded": "This project has used its YouTube quota for today. "
                         "It resets at midnight Pacific time.",
        "uploadLimitExceeded": "This YouTube account has hit its upload limit for "
                               "now. New and unverified accounts are capped; "
                               "verifying the account with a phone number lifts it.",
        "forbidden": "YouTube refused the upload. Check the connected account is "
                     "the right one and still has upload permission.",
        "youtubeSignupRequired": "That Google account has no YouTube channel yet. "
                                 "Create one, then reconnect.",
        "accessNotConfigured": "This Google Cloud project hasn't enabled the API this "
                               "needs. Enable it in the Cloud console's API Library "
                               "(YouTube Data API v3, and YouTube Analytics API for "
                               "retention), then try again.",
        "insufficientPermissions": "This channel was connected before it was asked for "
                                   "permission to read statistics. Reconnect it from "
                                   "its settings.",
    }
    message = messages.get(reason) or f"YouTube wouldn't {doing} (HTTP {response.status_code})."
    log.error(f"YouTube API error while trying to {doing}: {response.status_code} {detail}")
    return YouTubeError(f"{response.status_code} {detail}", user_message=message)


def _json_or_raise(response, doing: str) -> dict:
    if response.status_code >= 400:
        raise _api_error(response, doing)
    try:
        return response.json()
    except ValueError:
        raise YouTubeError(f"Non-JSON response while trying to {doing}.",
                           user_message=f"YouTube sent back something unreadable "
                                        f"when asked to {doing}. Try again.")
