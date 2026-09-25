"""
Draft channels: a pitch turned into a whole channel, waiting for review.

`create` runs the pitch through pipeline.channel_draft (and, for a
channel that writes its own topics, designs the topic plan's outline) and
saves the result. Nothing is a channel yet: a draft lives in
cache/channel_drafts/ until it's accepted or thrown away, so an idea can
be pitched, looked at and dropped without leaving anything in the
channel list.

`accept` turns the reviewed draft, with whatever the owner changed on the
review page, into a real channel: config, voice, palette, pacing, avoid
list, the topic plan with its first topic's videos written (or the quote
list for a quote channel). It lands on its launch pipeline at "make and
approve a first video". Both calls cost well under ten cents.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from core import channel_admin, corpus, curriculum, palettes, voice_lab
from core.channels import ChannelConfig, read_raw
from core.errors import ConfigError, PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR, safe_join, slugify
from pipeline.scenes import art

log = get_logger(__name__)

DRAFTS_DIR = CACHE_DIR / "channel_drafts"


def _path(draft_id: str) -> Path:
    return safe_join(DRAFTS_DIR, f"{draft_id}.json")


def create(pitch: str, note: str = "", previous: dict = None) -> dict:
    """Draft a channel from a pitch and save it. Returns the saved draft."""
    from pipeline import channel_draft

    voices = voice_lab.get_cached_voices()
    body = channel_draft.draft(pitch, voices, note=note,
                               previous=(previous or {}).get("channel"))
    topics = []
    if body["content_mode"] == "topic":
        topics = channel_draft.outline(body["style_prompt"], body["subject"],
                                       body["name_options"][0])
    record = {
        "id": (previous or {}).get("id") or uuid.uuid4().hex[:12],
        "pitch": pitch.strip(),
        "notes": [*(previous or {}).get("notes", []), *([note.strip()] if note.strip() else [])],
        "created_at": time.time(),
        "channel": body,
        "outline": topics,
        "voices": [v for v in voices if v["voice_id"] in body["voice_ids"]],
    }
    record["voices"].sort(key=lambda v: body["voice_ids"].index(v["voice_id"]))
    save(record)
    return record


def save(record: dict) -> None:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    _path(record["id"]).write_text(json.dumps(record, indent=2), encoding="utf-8")


def load(draft_id: str) -> dict:
    try:
        return json.loads(_path(draft_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def all_drafts() -> list:
    """Unaccepted drafts, newest first."""
    if not DRAFTS_DIR.exists():
        return []
    records = []
    for path in DRAFTS_DIR.glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda r: r.get("created_at", 0), reverse=True)


def discard(draft_id: str) -> None:
    _path(draft_id).unlink(missing_ok=True)


def accept(draft_id: str, choices: dict) -> ChannelConfig:
    """Create the channel from a reviewed draft.

    `choices` is what the review page sent: name, style_prompt, voice,
    palette, target_seconds, segment_count, speed, avoid_imagery (a list),
    quotes (text, for a custom quote channel), art (the scenes' art
    direction fields) and scene_share. Anything missing falls back
    to the draft's own value.
    """
    record = load(draft_id)
    if record is None:
        raise ConfigError(f"no draft {draft_id}",
                          user_message="That draft no longer exists. Pitch it again.")
    body = record["channel"]

    name = (choices.get("name") or body["name_options"][0]).strip()
    key = slugify(name)
    if not key:
        raise ConfigError("unusable name", user_message="The name needs at least one letter or number.")
    if key in read_raw():
        raise ConfigError(f"key {key} exists", user_message=(
            f'A channel called "{key}" already exists. Pick a different name.'))

    channel = ChannelConfig(
        key=key, channel_display_name=name, content_mode=body["content_mode"],
        voice=choices.get("voice") or body["voice_ids"][0],
        style_prompt=(choices.get("style_prompt") or body["style_prompt"]).strip(),
        hook_style=(choices.get("hook_style") or body.get("hook_style") or "").strip(),
        avoid_imagery=list(choices.get("avoid_imagery", body["avoid_imagery"])),
        speed=_number(choices.get("speed"), body["speed"], 0.7, 1.2),
    )
    if body["content_mode"] == "static_corpus":
        channel.source = body["corpus_source"]
    channel.pacing.target_seconds = _number(choices.get("target_seconds"),
                                            body["target_seconds"], 15, 180)
    channel.pacing.segment_count = int(_number(choices.get("segment_count"),
                                               body["segment_count"], 1, 8))
    palettes.apply_to_style(channel.style, palettes.get(choices.get("palette") or body["palette_key"]))
    # The animated scenes' look and amount, as reviewed (drafts made
    # before scenes existed have none, and start with stock only).
    drafted_art = body.get("art") or {}
    channel.scenes.art = art.clean(choices.get("art") or drafted_art)
    channel.scenes.share = int(_number(choices.get("scene_share"),
                                       drafted_art.get("scene_share", 0), 0, 100))

    # Written before the channel exists, because validation looks for them:
    # a quote channel needs its list, a topic channel its plan.
    if channel.source == "custom":
        quotes = choices.get("quotes")
        text = quotes if quotes is not None else "\n".join(body["custom_quotes"])
        corpus.save(key, text)
    if channel.content_mode == "topic":
        _start_topic_plan(channel, body["subject"], record["outline"])

    channel.sound.music_moods = list(body.get("music_moods") or [])
    channel_admin.create_channel(channel, complete=False)
    _add_music(channel.key, choices.get("music") or [])
    discard(draft_id)
    log.info(f"Created channel {key} from a pitch ({record['pitch']!r}).")
    return channel


def _add_music(channel_key: str, track_ids: list) -> None:
    """The tracks ticked on the draft page. A failed download is logged,
    not fatal: the channel exists, and fetches music itself if it has
    none."""
    from core import music_library
    for track_id in track_ids[:8]:
        try:
            music_library.add(channel_key, music_library.candidate(track_id))
        except PipelineError as exc:
            log.warning(f"{channel_key}: couldn't add track {track_id}: {exc}")


def _start_topic_plan(channel, subject: str, outline: list) -> None:
    """The syllabus from the draft's outline, and the first topic's videos
    written now, so the channel can make its first video straight away."""
    from pipeline import curriculum_gen

    if not outline:
        return
    data = curriculum.start(channel.key, subject, outline)
    first = data["topics"][0]
    try:
        subtopics = curriculum_gen.write_subtopics(channel, data, first)
        curriculum.add_subtopics(channel.key, first["id"], subtopics)
    except PipelineError as exc:
        # The plan exists; its first topic can be filled from the Topic
        # plan page. Not worth losing the whole channel over.
        log.warning(f"{channel.key}: couldn't write the first topic's videos yet: {exc}")


def _number(raw, default, low, high):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(default)
    return max(low, min(high, value))
