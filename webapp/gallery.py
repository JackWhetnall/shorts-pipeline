"""
Lists a channel's finished videos for the web gallery/home page. Handles
both the current dated-folder layout (output/<channel>/<date>/<slug>.mp4)
and older flat files from before that convention existed
(output/<channel>/<hash>.mp4) uniformly — Path.rglob searches every
subdirectory AND the root itself, so no special-casing is needed for
either layout.

Publish tracking uses a {stem}_publish.json sidecar per video, the same
naming shape and directory as the {stem}_meta.txt sidecar main.py already
writes — a video is "published" once at least one platform link is set,
derived rather than a separate stored flag (same idiom
config.channels.resolve_active_ctas already uses: a real URL's presence
IS the source of truth, so there's no separate boolean that could drift
out of sync with the links themselves). The sidecar also carries
published_at, an ISO timestamp set the moment a video FIRST becomes
published — distinct from the video file's own mtime (when it was
CREATED), needed anywhere "time since published" actually means since it
went out, not since it was rendered.

A thumbnail sidecar ({stem}_thumb.jpg) is generated lazily on first
request (see get_or_create_thumbnail) rather than eagerly for every video
every time the gallery loads.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from moviepy.editor import VideoFileClip

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PUBLISH_LINK_FIELDS = ("youtube_url", "tiktok_url", "instagram_url")


def _resolve_output_dir(output_dir: str) -> Path:
    return (PROJECT_ROOT / output_dir).resolve()


def read_meta_text(path: Path) -> str:
    """UTF-8 first (what main.py writes today); older _meta.txt files
    written before that encoding fix are cp1252 on Windows and would
    otherwise crash the gallery outright on a single stray curly quote or
    em dash — falls back rather than 500ing the whole page over one old
    file."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252", errors="replace")


def count_videos(output_dir: str) -> int:
    d = _resolve_output_dir(output_dir)
    if not d.exists():
        return 0
    return sum(1 for _ in d.rglob("*.mp4"))


def latest_video_mtime(output_dir: str):
    """Most recent video's mtime (epoch float), or None if there are no
    videos yet. Cheaper than list_videos()[0]["mtime"] for a dashboard that
    only needs this one value, not full metadata for every video."""
    d = _resolve_output_dir(output_dir)
    if not d.exists():
        return None
    mtimes = [p.stat().st_mtime for p in d.rglob("*.mp4")]
    return max(mtimes) if mtimes else None


def _publish_path(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}_publish.json")


def load_publish_info(video_path: Path) -> dict:
    """{"youtube_url", "tiktok_url", "instagram_url", "published_at",
    "discarded"} — all URLs "" and published_at None if the video's never
    had publish links saved (no sidecar file yet); discarded False."""
    p = _publish_path(Path(video_path))
    if not p.exists():
        return {**{field: "" for field in PUBLISH_LINK_FIELDS}, "published_at": None, "discarded": False}
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        **{field: data.get(field, "") for field in PUBLISH_LINK_FIELDS},
        "published_at": data.get("published_at"),
        "discarded": bool(data.get("discarded", False)),
    }


def is_published(info: dict) -> bool:
    return any(info.get(field) for field in PUBLISH_LINK_FIELDS)


def save_publish_info(video_path: Path, links: dict):
    """Writes the 3 platform links, and stamps published_at with now the
    moment this video FIRST becomes published (any link set where none
    was before) — later edits to an already-published video's links don't
    reset it, and clearing every link back out clears it too, so it
    always answers "when did this most recently go from unpublished to
    published"."""
    existing = load_publish_info(video_path)
    new_links = {field: links.get(field, "").strip() for field in PUBLISH_LINK_FIELDS}
    was_published = is_published(existing)
    now_published = any(new_links.values())
    if now_published and not was_published:
        published_at = datetime.now(timezone.utc).isoformat()
    elif not now_published:
        published_at = None
    else:
        published_at = existing.get("published_at")

    p = _publish_path(Path(video_path))
    with open(p, "w", encoding="utf-8") as f:
        json.dump({**new_links, "published_at": published_at, "discarded": existing["discarded"]}, f, indent=2)


def set_discarded(video_path: Path, discarded: bool):
    """Flips just the discarded flag, preserving whatever links/
    published_at are already there — discarding a video doesn't touch
    its publish state, restoring it doesn't invent any."""
    existing = load_publish_info(video_path)
    existing["discarded"] = bool(discarded)
    p = _publish_path(Path(video_path))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)


def video_state_counts(output_dir: str) -> dict:
    """One rglob pass (each video's sidecar read exactly once) instead of
    calling count_videos()/count_published_videos() separately - the home
    page now wants several of these numbers per channel, every load.
    {"total", "active" (= total - discarded), "published", "unpublished"
    (= active - published), "discarded"}."""
    d = _resolve_output_dir(output_dir)
    if not d.exists():
        return {"total": 0, "active": 0, "published": 0, "unpublished": 0, "discarded": 0}
    total = discarded = published = 0
    for p in d.rglob("*.mp4"):
        total += 1
        info = load_publish_info(p)
        if info["discarded"]:
            discarded += 1
        elif is_published(info):
            published += 1
    active = total - discarded
    return {
        "total": total, "active": active, "published": published,
        "unpublished": active - published, "discarded": discarded,
    }


def count_published_videos(output_dir: str) -> int:
    d = _resolve_output_dir(output_dir)
    if not d.exists():
        return 0
    return sum(1 for p in d.rglob("*.mp4") if is_published(load_publish_info(p)))


def latest_published_at(output_dir: str):
    """Most recent published_at across all of a channel's videos (epoch
    float), or None if nothing's published yet."""
    d = _resolve_output_dir(output_dir)
    if not d.exists():
        return None
    timestamps = []
    for p in d.rglob("*.mp4"):
        info = load_publish_info(p)
        if info["published_at"]:
            timestamps.append(datetime.fromisoformat(info["published_at"]).timestamp())
    return max(timestamps) if timestamps else None


def _thumbnail_path(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}_thumb.jpg")


def get_or_create_thumbnail(video_path: Path) -> Path:
    """Extracts one frame as a JPEG the first time this video's thumbnail
    is requested, caches it as a {stem}_thumb.jpg sidecar, and just
    returns the cached file on every request after that. A little into
    the clip (not frame 0) since the very start is often a fade-in or a
    plain black frame, which makes a poor preview."""
    video_path = Path(video_path)
    thumb_path = _thumbnail_path(video_path)
    if thumb_path.exists():
        return thumb_path
    clip = VideoFileClip(str(video_path))
    try:
        t = min(1.5, clip.duration * 0.1) if clip.duration else 0
        clip.save_frame(str(thumb_path), t=t)
    finally:
        clip.close()
    return thumb_path


def list_videos(output_dir: str) -> list:
    """Newest first. Each entry: {relpath (for the /videos/ route), name,
    mtime, meta_text (contents of the paired _meta.txt, or None), links
    (the platform URLs + published_at + discarded from the paired
    _publish.json, if any), published (bool, derived from links),
    discarded (bool, surfaced at the top level too for convenience)."""
    d = _resolve_output_dir(output_dir)
    if not d.exists():
        return []

    videos = []
    for path in d.rglob("*.mp4"):
        meta_path = path.with_name(f"{path.stem}_meta.txt")
        meta_text = read_meta_text(meta_path) if meta_path.exists() else None
        links = load_publish_info(path)
        videos.append({
            "relpath": str(path.relative_to(PROJECT_ROOT / "output")).replace("\\", "/"),
            "name": path.name,
            "mtime": path.stat().st_mtime,
            "meta_text": meta_text,
            "links": links,
            "published": is_published(links),
            "discarded": links["discarded"],
        })
    videos.sort(key=lambda v: v["mtime"], reverse=True)
    return videos
