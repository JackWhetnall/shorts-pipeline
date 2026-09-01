"""
Lists a channel's finished videos for the web gallery/home page. Handles
both the current dated-folder layout (output/<channel>/<date>/<slug>.mp4)
and older flat files from before that convention existed
(output/<channel>/<hash>.mp4) uniformly — Path.rglob searches every
subdirectory AND the root itself, so no special-casing is needed for
either layout.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def list_videos(output_dir: str) -> list:
    """Newest first. Each entry: {relpath (for the /videos/ route), name,
    mtime, meta_text (contents of the paired _meta.txt, or None)}."""
    d = _resolve_output_dir(output_dir)
    if not d.exists():
        return []

    videos = []
    for path in d.rglob("*.mp4"):
        meta_path = path.with_name(f"{path.stem}_meta.txt")
        meta_text = _read_meta_text(meta_path) if meta_path.exists() else None
        videos.append({
            "relpath": str(path.relative_to(PROJECT_ROOT / "output")).replace("\\", "/"),
            "name": path.name,
            "mtime": path.stat().st_mtime,
            "meta_text": meta_text,
        })
    videos.sort(key=lambda v: v["mtime"], reverse=True)
    return videos
