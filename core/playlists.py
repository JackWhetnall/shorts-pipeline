"""
Films sorted into playlists, and the channel's keywords (decision 114).

A viewer who finishes one film on a playlist is offered the next, which
is the cheapest second view there is, and a playlist is found in search
on its own. Each published film of a documentary channel goes into one
themed playlist ("The Ocean, Explained"), chosen from the channel's
playlists by a small model call, or made when none fits. The channel's
keywords, empty on a new channel, are written once from its description
and its films' titles.

Both need the YouTube `youtube` scope (managing the channel), which a
channel connected only to upload doesn't have: until it's reconnected,
this does nothing and says why, once, in the log. Nothing here is fatal:
a film is out whether or not it's in a playlist.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from core import gallery, youtube
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR, write_atomically

log = get_logger(__name__)

# {channel key: {video id: playlist title}}: which films are in a playlist,
# and under KEYWORDS_DONE the channel's keywords once they're written.
PLACED_PATH = CACHE_DIR / "playlists.json"
KEYWORDS_DONE = "__keywords__"


def _placed() -> dict:
    try:
        return json.loads(PLACED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remember(key: str, video_id: str, title: str) -> None:
    placed = _placed()
    placed.setdefault(key, {})[video_id] = title
    write_atomically(PLACED_PATH, json.dumps(placed, indent=1))

API = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 30

CHOOSE = """
You keep a YouTube explainer channel's playlists tidy. A new film has gone out. Put it in the one
playlist where a viewer who liked the films already there would want it next: an existing
playlist if one fits its subject, else a new one. A new playlist's title is a plain theme of two
to five words a viewer would search for ("The Ocean, Explained", "Your Body's Strange Habits",
"Everyday Things, Explained"), broad enough for more films than this one, never the film's own
title. Answer with the playlist's exact title.
""".strip()

KEYWORDS = """
Write a YouTube channel's keywords: the words people would search to find it. From its
description and its films' titles, give ten to fifteen short keywords or phrases, most useful
first, lower case, no hashtags, nothing misleading.
""".strip()


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {youtube.access_token(key)}"}


def can_manage(key: str) -> bool:
    return bool(youtube.connection(key).get("manage"))


def _playlists(key: str) -> dict:
    """{title: id} of the channel's own playlists."""
    out, token = {}, None
    while True:
        params = {"part": "snippet", "mine": "true", "maxResults": 50}
        if token:
            params["pageToken"] = token
        page = youtube._json_or_raise(requests.get(f"{API}/playlists", headers=_headers(key), params=params,
                                                   timeout=TIMEOUT), "list the channel's playlists")
        for item in page.get("items") or []:
            out[item["snippet"]["title"]] = item["id"]
        token = page.get("nextPageToken")
        if not token:
            return out


def _choose(film_title: str, about: str, existing: list) -> str:
    from pipeline.llm import call_json
    schema = {"type": "object", "properties": {"playlist": {"type": "string"}},
              "required": ["playlist"], "additionalProperties": False}
    listed = "\n".join(f"- {t}" for t in existing) or "(none yet)"
    data = call_json(CHOOSE, f"The film: {film_title}\n{about}\n\nThe channel's playlists:\n{listed}", schema,
                     operation="playlist_choose", max_tokens=1500, effort="low")
    return " ".join(str(data.get("playlist") or "").split())[:100]


def add_film(channel, video_path, video_id: str) -> str:
    """Put a published film in its playlist. Returns the playlist's title,
    or "" when it can't (no permission yet, or YouTube refused: logged)."""
    key = channel.key
    if not can_manage(key):
        return ""
    info = gallery.load_publish_info(video_path)
    title = info.get("title") or Path(video_path).stem
    try:
        existing = _playlists(key)
        chosen = _choose(title, (info.get("description") or "")[:400], list(existing))
        if not chosen:
            return ""
        playlist = existing.get(chosen)
        if playlist is None:
            made = youtube._json_or_raise(requests.post(
                f"{API}/playlists", headers=_headers(key), params={"part": "snippet,status"}, timeout=TIMEOUT,
                json={"snippet": {"title": chosen}, "status": {"privacyStatus": "public"}}),
                "make a playlist")
            playlist = made["id"]
        youtube._json_or_raise(requests.post(
            f"{API}/playlistItems", headers=_headers(key), params={"part": "snippet"}, timeout=TIMEOUT,
            json={"snippet": {"playlistId": playlist, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}),
            "add the film to its playlist")
    except (PipelineError, requests.RequestException) as exc:
        log.warning(f"{key}: {Path(video_path).stem} not added to a playlist: {exc}")
        return ""
    _remember(key, video_id, chosen)
    log.info(f"{key}: {Path(video_path).stem} added to the playlist \"{chosen}\"")
    return chosen


def ensure_keywords(channel) -> bool:
    """Write the channel's keywords if it has none. True when written."""
    key = channel.key
    if not can_manage(key) or _placed().get(key, {}).get(KEYWORDS_DONE):
        return False
    try:
        page = youtube._json_or_raise(requests.get(
            f"{API}/channels", headers=_headers(key), params={"part": "brandingSettings,snippet", "mine": "true"},
            timeout=TIMEOUT), "read the channel's settings")
        item = (page.get("items") or [{}])[0]
        branding = item.get("brandingSettings") or {}
        if (branding.get("channel") or {}).get("keywords"):
            _remember(key, KEYWORDS_DONE, "already set")
            return False
        from pipeline.llm import call_json
        titles = [gallery.load_publish_info(v).get("title") or v.stem
                  for v in gallery.videos_in(gallery.resolve_output_dir(channel.output_dir), long=True)][:20]
        schema = {"type": "object", "properties": {"keywords": {"type": "array", "items": {"type": "string"}}},
                  "required": ["keywords"], "additionalProperties": False}
        data = call_json(KEYWORDS, f"The description: {(item.get('snippet') or {}).get('description', '')}\n\n"
                                   "The films:\n" + "\n".join(f"- {t}" for t in titles), schema,
                         operation="channel_keywords", max_tokens=1500, effort="low")
        words = [" ".join(str(w).split()) for w in data.get("keywords") or [] if str(w).strip()][:15]
        if not words:
            return False
        # YouTube takes them space separated, a phrase in quotes.
        joined = " ".join(f'"{w}"' if " " in w else w for w in words)[:500]
        branding.setdefault("channel", {})["keywords"] = joined
        youtube._json_or_raise(requests.put(
            f"{API}/channels", headers=_headers(key), params={"part": "brandingSettings"}, timeout=TIMEOUT,
            json={"id": item["id"], "brandingSettings": branding}), "set the channel's keywords")
    except (PipelineError, requests.RequestException, KeyError) as exc:
        log.warning(f"{key}: keywords not set: {exc}")
        return False
    _remember(key, KEYWORDS_DONE, joined)
    log.info(f"{key}: channel keywords set")
    return True


def catch_up(channels: dict) -> None:
    """Twice a day: every published film of a documentary channel that may
    manage its YouTube is in a playlist, and the channel has keywords."""
    from core import audience
    for key, channel in channels.items():
        if channel.format != "documentary" or channel.archived or not can_manage(key):
            continue
        ensure_keywords(channel)
        placed = _placed().get(key, {})
        for video in gallery.videos_in(gallery.resolve_output_dir(channel.output_dir), long=True):
            info = gallery.load_publish_info(video)
            vid = audience.video_id(info.get("youtube_url") or "")
            if vid and vid not in placed and not info.get("discarded"):
                add_film(channel, video, vid)
