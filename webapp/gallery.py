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
out of sync with the links themselves).
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PUBLISH_LINK_FIELDS = ("youtube_url", "tiktok_url", "instagram_url")


def _resolve_output_dir(output_dir: str) -> Path:
    return (PROJECT_ROOT / output_dir).resolve()


def _read_meta_text(path: Path) -> str:
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
    """{"youtube_url", "tiktok_url", "instagram_url"}, all "" if the
    video's never had publish links saved (no sidecar file yet)."""
    p = _publish_path(Path(video_path))
    if not p.exists():
        return {field: "" for field in PUBLISH_LINK_FIELDS}
    with open(p, "r", encoding="utf-8") as f:
        links = json.load(f)
    return {field: links.get(field, "") for field in PUBLISH_LINK_FIELDS}


def save_publish_info(video_path: Path, links: dict):
    p = _publish_path(Path(video_path))
    with open(p, "w", encoding="utf-8") as f:
        json.dump({field: links.get(field, "").strip() for field in PUBLISH_LINK_FIELDS}, f, indent=2)


def is_published(links: dict) -> bool:
    return any(links.get(field) for field in PUBLISH_LINK_FIELDS)


def list_videos(output_dir: str) -> list:
    """Newest first. Each entry: {relpath (for the /videos/ route), name,
    mtime, meta_text (contents of the paired _meta.txt, or None), links
    (the platform URLs from the paired _publish.json, if any), published
    (bool, derived from links)}."""
    d = _resolve_output_dir(output_dir)
    if not d.exists():
        return []

    videos = []
    for path in d.rglob("*.mp4"):
        meta_path = path.with_name(f"{path.stem}_meta.txt")
        meta_text = _read_meta_text(meta_path) if meta_path.exists() else None
        links = load_publish_info(path)
        videos.append({
            "relpath": str(path.relative_to(PROJECT_ROOT / "output")).replace("\\", "/"),
            "name": path.name,
            "mtime": path.stat().st_mtime,
            "meta_text": meta_text,
            "links": links,
            "published": is_published(links),
        })
    videos.sort(key=lambda v: v["mtime"], reverse=True)
    return videos
