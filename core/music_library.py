"""
Music for each channel, found and fetched by the app: openly licensed
tracks that suit the channel, never shared between channels.

Source: Openverse (WordPress's open search of openly licensed media: no
key), which indexes Jamendo, Freesound and others. Only licences that
allow a track under a monetised video without conditions beyond a
credit: CC0, public domain, and CC BY (credited in the description). No
NC (non-commercial), ND or SA (a synced video is an adaptation, and SA
would bind the video to the same licence).

Suitability, two cheap Haiku calls: the channel's description becomes
three mood searches (kept on the channel), and the candidates' titles
and tags are judged against the channel: vocals, seasonal songs, dance
tracks and anything off-tone are dropped. What's left is offered with a
player on the draft page and the channel's dashboard, and a channel with
no music gets the best few automatically at its next render.

A registry (music/registry.json) records which channel owns each track,
and suggestions for one channel never include another's. See decision 039.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import requests

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR, PROJECT_ROOT

log = get_logger(__name__)

API = "https://api.openverse.org/v1/audio/"
HEADERS = {"User-Agent": "ShortsPipeline/1.0 (personal video project)"}
TIMEOUT = 30
LICENCES = ("cc0", "pdm", "by")
MIN_SECONDS, MAX_SECONDS = 40, 600
AUTO_TRACKS = 3
ENOUGH = 5
BROADER = ["ambient instrumental", "cinematic ambient", "calm background music",
           "soft piano", "atmospheric pad"]
REGISTRY = PROJECT_ROOT / "music" / "registry.json"
CANDIDATES = PROJECT_ROOT / "cache" / "music_candidates"
JUDGE_MODEL = "claude-haiku-4-5"
_registry_lock = threading.Lock()


def music_dir(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "music"


# --- the registry: one channel per track ---------------------------------------

def _registry() -> dict:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_registry(data: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(data, indent=1), encoding="utf-8")


def owner(track_id: str) -> str:
    return (_registry().get(track_id) or {}).get("channel", "")


# --- finding ---------------------------------------------------------------------

def _search(query: str) -> list:
    try:
        response = requests.get(API, headers=HEADERS, timeout=TIMEOUT, params={
            "q": query, "license": ",".join(LICENCES), "page_size": 20})
        results = response.json().get("results", []) if response.status_code == 200 else []
    except (requests.RequestException, ValueError) as exc:
        log.info(f"  [music] search failed ({exc})")
        return []
    out = []
    for r in results:
        seconds = (r.get("duration") or 0) / 1000
        if r.get("license") not in LICENCES or not (MIN_SECONDS <= seconds <= MAX_SECONDS):
            continue
        if not r.get("url"):
            continue
        out.append({"id": r["id"], "title": (r.get("title") or "Untitled").strip(),
                    "creator": (r.get("creator") or "").strip(), "licence": r["license"],
                    "licence_version": r.get("license_version") or "",
                    "licence_url": r.get("license_url") or "", "url": r["url"],
                    "page": r.get("foreign_landing_url") or "", "source": r.get("source") or "",
                    "seconds": round(seconds), "genres": r.get("genres") or [],
                    "tags": [t.get("name") for t in (r.get("tags") or []) if t.get("name")][:12]})
    return out


def _moods(description: str) -> list:
    from pipeline import llm
    schema = {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
              "required": ["queries"], "additionalProperties": False}
    data = llm.call_json(
        "You choose background music for a short-video channel. Give three different short "
        "search phrases (2-4 words each: mood, instrument, style) for instrumental tracks "
        "that would sit well under narration on this channel. No vocals, no genres that "
        "would clash with its tone.",
        f"The channel: {description}", schema, operation="music_moods", model=JUDGE_MODEL,
        max_tokens=400, effort=None)
    return [q.strip() for q in data.get("queries") or [] if q and q.strip()][:3]


def _judge(candidates: list, description: str) -> list:
    """The candidates that suit the channel, best first, with a reason."""
    from pipeline import llm
    if not candidates:
        return []
    listed = "\n".join(
        f"{i + 1}. {c['title']} by {c['creator'] or 'unknown'} ({c['seconds']}s; "
        f"genres: {', '.join(c['genres']) or '-'}; tags: {', '.join(c['tags']) or '-'})"
        for i, c in enumerate(candidates))
    schema = {"type": "object", "properties": {"picks": {"type": "array", "items": {
        "type": "object", "properties": {"number": {"type": "integer"}, "why": {"type": "string"}},
        "required": ["number", "why"], "additionalProperties": False}}},
        "required": ["picks"], "additionalProperties": False}
    data = llm.call_json(
        "You pick background music for a short-video channel from a list of openly licensed "
        "tracks, judging by title and tags. Keep only instrumental tracks whose mood fits "
        "under narration on this channel. Drop anything with vocals or lyrics, seasonal or "
        "novelty songs, dance or party tracks, sound effects and field recordings, and "
        "anything that would feel wrong for the channel's audience. Best first; at most 8.",
        f"The channel: {description}\n\nTracks:\n{listed}", schema, operation="music_pick",
        model=JUDGE_MODEL, max_tokens=1500, effort=None)
    out = []
    for pick in data.get("picks") or []:
        n = pick.get("number")
        if isinstance(n, int) and 1 <= n <= len(candidates) and candidates[n - 1] not in out:
            out.append({**candidates[n - 1], "why": (pick.get("why") or "").strip()})
    return out


def describe(channel) -> str:
    return (f"{channel.channel_display_name}. {channel.style_prompt[:600]} "
            f"{getattr(channel, 'hook_style', '')[:200]}").strip()


def suggest(channel_key: str, description: str, moods: list = None) -> dict:
    """{"moods": [...], "tracks": [...]}: tracks that suit the channel,
    not owned by any other channel, not already in this one."""
    moods = moods or _moods(description)
    have = {p.stem for p in music_dir(channel_key).glob("*.json")} if channel_key else set()
    seen, pool = set(), []

    def gather(queries):
        for query in queries:
            for c in _search(query):
                taken = owner(c["id"])
                if c["id"] in seen or (taken and taken != channel_key) or _slug(c) in have:
                    continue
                seen.add(c["id"])
                pool.append(c)

    gather(moods)
    picks = _judge(pool[:40], description)
    if len(picks) < ENOUGH:
        # Niche moods ("ethereal lo-fi magic") find little: widen to the
        # broad terms the libraries are tagged with, and judge again.
        gather(BROADER)
        picks = _judge(pool[:60], description)
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    for c in picks:              # remembered, so "add" can fetch exactly what was offered
        (CANDIDATES / f"{c['id']}.json").write_text(json.dumps(c), encoding="utf-8")
    return {"moods": moods, "tracks": picks}


# --- keeping ---------------------------------------------------------------------

def _slug(track: dict) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", f"{track['title']}_{track['creator']}".lower()).strip("_")
    return (base[:60] or "track") + "_" + track["id"][:8]


def candidate(track_id: str) -> dict:
    try:
        return json.loads((CANDIDATES / f"{track_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PipelineError(f"unknown track {track_id}", user_message=(
            "That track isn't among the suggestions any more. Find tracks again."))


def add(channel_key: str, track: dict) -> Path:
    """Download `track` into the channel's music folder, with a note of
    its licence and credit, and register it to this channel."""
    with _registry_lock:
        taken = owner(track["id"])
        if taken and taken != channel_key:
            raise PipelineError(f"track owned by {taken}", user_message=(
                "Another channel already uses that track."))
        folder = music_dir(channel_key)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_slug(track)}.mp3"
        try:
            response = requests.get(track["url"], headers=HEADERS, timeout=120)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise PipelineError(f"download failed: {exc}", user_message=(
                "That track couldn't be downloaded. Try another.")) from exc
        path.write_bytes(response.content)
        path.with_suffix(".json").write_text(json.dumps({**track, "credit": credit(track)},
                                                        indent=1), encoding="utf-8")
        registry = _registry()
        registry[track["id"]] = {"channel": channel_key, "file": path.name, "title": track["title"]}
        _save_registry(registry)
    log.info(f"  [music] {channel_key}: added {track['title']} ({track['licence']})")
    return path


def remove(channel_key: str, filename: str) -> None:
    from core.paths import safe_join
    path = safe_join(music_dir(channel_key), filename)
    note = path.with_suffix(".json")
    track_id = ""
    if note.exists():
        track_id = json.loads(note.read_text(encoding="utf-8")).get("id", "")
        note.unlink()
    path.unlink(missing_ok=True)
    with _registry_lock:
        registry = _registry()
        if track_id in registry:
            del registry[track_id]
            _save_registry(registry)


def tracks(channel_key: str) -> list:
    """The channel's own tracks, with their notes (hand-added files too)."""
    out = []
    folder = music_dir(channel_key)
    for path in sorted(folder.glob("*")) if folder.exists() else []:
        if path.suffix.lower() not in (".mp3", ".wav", ".m4a", ".ogg", ".flac"):
            continue
        note = path.with_suffix(".json")
        info = json.loads(note.read_text(encoding="utf-8")) if note.exists() else {}
        out.append({"file": path.name, "title": info.get("title") or path.stem,
                    "creator": info.get("creator", ""), "licence": info.get("licence", ""),
                    "credit": info.get("credit", "")})
    return out


def credit(track: dict) -> str:
    """A description credit line; "" when the licence doesn't need one."""
    if track.get("licence") != "by":
        return ""
    version = f" {track['licence_version']}" if track.get("licence_version") else ""
    who = f" by {track['creator']}" if track.get("creator") else ""
    return f"Music: {track['title']}{who} (CC BY{version})."


def credit_for(path: Path) -> str:
    note = Path(path).with_suffix(".json")
    try:
        return json.loads(note.read_text(encoding="utf-8")).get("credit", "")
    except (OSError, ValueError):
        return ""


def auto_fill(channel) -> list:
    """For a channel with no music: the best few suggestions, downloaded.
    Never raises; no music is better than a failed render."""
    try:
        moods = list(getattr(channel.sound, "music_moods", []) or [])
        found = suggest(channel.key, describe(channel), moods or None)
        added = []
        for track in found["tracks"][:AUTO_TRACKS]:
            try:
                added.append(add(channel.key, track))
            except PipelineError as exc:
                log.info(f"  [music] skipped {track['title']}: {exc}")
        return added
    except Exception as exc:  # noqa: BLE001 - music is a nicety; the video goes on without
        log.warning(f"  [music] couldn't fetch music automatically ({exc})")
        return []
