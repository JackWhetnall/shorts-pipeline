"""
Finished videos: listing them, and tracking what happened to each one.

State lives in per-video sidecars next to the file, matching the
`{stem}_meta.txt` the pipeline already writes:

  {stem}_publish.json   platform links, published_at, discarded
  {stem}_cost.json      what this video cost to make
  {stem}_thumb.jpg      cached poster frame

A video counts as published when any platform link is set — derived, not
a separate boolean, so there's no flag that can drift out of sync with
the links themselves. `published_at` is stamped the first time it goes
from no links to some, which is genuinely different from the file's
mtime: one is when it went out, the other is when it was rendered.

`rglob` handles both the dated-folder layout and older flat files without
special-casing either.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.paths import DISCARD_HISTORY_PATH, OUTPUT_DIR, PROJECT_ROOT

PUBLISH_LINK_FIELDS = ("youtube_url", "tiktok_url", "instagram_url")

# Why a take was thrown away. This is the single richest quality signal
# the system has — your own judgement, exercised repeatedly — and it used
# to be recorded as a bare boolean and never read again. With it, "9 of
# the last 20 discarded, 7 for footage" is a number on a page instead of
# a feeling, which is how the footage problem stayed invisible for
# months. Ids are stable; labels are not.
DISCARD_REASONS = (
    ("footage", "Footage didn't fit"),
    ("script", "Script was weak"),
    ("audio", "Audio problem"),
    ("repeat", "Too similar to an earlier video"),
    ("other", "Just not good enough"),
)
DISCARD_REASON_IDS = tuple(r[0] for r in DISCARD_REASONS)
DISCARD_REASON_LABELS = dict(DISCARD_REASONS)


def resolve_output_dir(output_dir: str) -> Path:
    return (PROJECT_ROOT / output_dir).resolve()


def read_text_tolerantly(path: Path) -> str:
    """UTF-8 first, cp1252 as a fallback.

    Meta files written before the encoding was fixed are cp1252 on
    Windows, and one stray curly quote in one old file would otherwise
    500 the entire gallery page.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252", errors="replace")


def _sidecar(video_path: Path, suffix: str) -> Path:
    return Path(video_path).with_name(f"{Path(video_path).stem}_{suffix}")


# --- publish state ----------------------------------------------------

def load_publish_info(video_path: Path) -> dict:
    path = _sidecar(video_path, "publish.json")
    blank = {**{f: "" for f in PUBLISH_LINK_FIELDS}, "published_at": None,
             "discarded": False, "discard_reason": None, "discarded_at": None,
             "title": "", "description": ""}
    if not path.exists():
        return blank
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return blank
    return {
        **{f: data.get(f, "") for f in PUBLISH_LINK_FIELDS},
        "published_at": data.get("published_at"),
        "discarded": bool(data.get("discarded", False)),
        "discard_reason": data.get("discard_reason"),
        "discarded_at": data.get("discarded_at"),
        "title": data.get("title", ""),
        "description": data.get("description", ""),
    }


def is_published(info: dict) -> bool:
    return any(info.get(f) for f in PUBLISH_LINK_FIELDS)


def _write_publish(video_path: Path, data: dict) -> None:
    with open(_sidecar(video_path, "publish.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def save_publish_info(video_path: Path, links: dict) -> dict:
    """Save platform links, stamping published_at the first time this
    video becomes published.

    Later edits to an already-published video don't reset the stamp, and
    clearing every link clears it — so it always answers "when did this
    go from unpublished to published".
    """
    existing = load_publish_info(video_path)
    new_links = {f: (links.get(f) or "").strip() for f in PUBLISH_LINK_FIELDS}
    was, now = is_published(existing), any(new_links.values())

    if now and not was:
        published_at = datetime.now(timezone.utc).isoformat()
    elif not now:
        published_at = None
    else:
        published_at = existing.get("published_at")

    data = {
        **new_links,
        "published_at": published_at,
        "discarded": existing["discarded"],
        "discard_reason": existing["discard_reason"],
        "discarded_at": existing["discarded_at"],
        # Preserved unless this call carries them: the publish form and
        # the title editor are separate actions on the same sidecar.
        "title": links.get("title", existing["title"]),
        "description": links.get("description", existing["description"]),
    }
    _write_publish(video_path, data)
    return data


def set_discarded(video_path: Path, discarded: bool, reason: str = None) -> None:
    """Flip the discarded flag, recording why.

    Discarding doesn't touch publish state and restoring doesn't invent
    any — a discarded take is a reversible decision, not a deletion.
    Restoring clears the reason, so a restored video doesn't keep
    contributing to the discard statistics.
    """
    info = load_publish_info(video_path)
    was_footage_reject = info["discarded"] and info["discard_reason"] == "footage"
    info["discarded"] = bool(discarded)
    if discarded:
        info["discard_reason"] = reason if reason in DISCARD_REASON_IDS else "other"
        info["discarded_at"] = datetime.now(timezone.utc).isoformat()
    else:
        info["discard_reason"] = None
        info["discarded_at"] = None
    _write_publish(video_path, info)

    # Feed the judgement back. Only for footage rejections — discarding a
    # video for a weak script says nothing about the clips in it — and
    # only on the transition, so toggling discard twice doesn't count
    # twice.
    now_footage_reject = bool(discarded) and info["discard_reason"] == "footage"
    if now_footage_reject and not was_footage_reject:
        _record_footage_rejection(video_path)


def _record_footage_rejection(video_path: Path) -> None:
    report = load_report(video_path)
    clips = (report or {}).get("clips") or []
    if not clips:
        return
    try:
        from pipeline.footage import store
        store.record_rejections(clips)
    except Exception:  # noqa: BLE001 - a ranking nudge must never fail a discard
        pass


def save_title_and_description(video_path: Path, title: str, description: str) -> dict:
    """The two things you actually need to publish, editable and stored.

    Neither existed before: the title was retyped by hand for every video
    and lived only on YouTube, and the generated description was a single
    reference line."""
    info = load_publish_info(video_path)
    info["title"] = (title or "").strip()
    info["description"] = (description or "").rstrip()
    _write_publish(video_path, info)
    return info


# --- cost -------------------------------------------------------------

def save_cost_summary(video_path: Path, summary: dict) -> None:
    try:
        with open(_sidecar(video_path, "cost.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    except OSError:
        pass


def load_cost_summary(video_path: Path):
    path = _sidecar(video_path, "cost.json")
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_report(video_path: Path, report: dict) -> None:
    """Quality signals from the render: repeated footage, originality,
    match confidences. Written beside the video so they survive the job
    that produced them — a job record is pruned after a week, the video
    is not."""
    try:
        with open(_sidecar(video_path, "report.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except OSError:
        pass


def load_report(video_path: Path):
    path = _sidecar(video_path, "report.json")
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# --- thumbnails -------------------------------------------------------

def get_or_create_thumbnail(video_path: Path) -> Path:
    """Extract one frame on first request and cache it.

    A little way into the clip rather than frame 0 — the very start is
    often a fade or a black frame, which makes a poor preview.
    """
    video_path = Path(video_path)
    thumb = _sidecar(video_path, "thumb.jpg")
    if thumb.exists():
        return thumb

    from moviepy.editor import VideoFileClip
    clip = VideoFileClip(str(video_path))
    try:
        t = min(1.5, clip.duration * 0.1) if clip.duration else 0
        clip.save_frame(str(thumb), t=t)
    finally:
        clip.close()
    return thumb


# --- listing ----------------------------------------------------------

def video_state_counts(output_dir: str) -> dict:
    """One pass, each sidecar read once.

    `active` (total minus discarded) is what "video count" means
    everywhere in the UI — a discarded take was never a deliverable.
    """
    directory = resolve_output_dir(output_dir)
    empty = {"total": 0, "active": 0, "published": 0, "unpublished": 0, "discarded": 0}
    if not directory.exists():
        return empty

    total = discarded = published = 0
    for path in directory.rglob("*.mp4"):
        total += 1
        info = load_publish_info(path)
        if info["discarded"]:
            discarded += 1
        elif is_published(info):
            published += 1

    active = total - discarded
    return {"total": total, "active": active, "published": published,
            "unpublished": active - published, "discarded": discarded}


def latest_video_mtime(output_dir: str):
    directory = resolve_output_dir(output_dir)
    if not directory.exists():
        return None
    mtimes = [p.stat().st_mtime for p in directory.rglob("*.mp4")]
    return max(mtimes) if mtimes else None


def latest_published_at(output_dir: str):
    directory = resolve_output_dir(output_dir)
    if not directory.exists():
        return None
    stamps = []
    for path in directory.rglob("*.mp4"):
        info = load_publish_info(path)
        if info["published_at"]:
            stamps.append(datetime.fromisoformat(info["published_at"]).timestamp())
    return max(stamps) if stamps else None


def video_title(filename: str) -> str:
    """Filenames are already readable slugs, so a title is just the stem
    with separators swapped. No separate title field needed."""
    return Path(filename).stem.replace("_", " ").replace("-", " ")


def list_videos(output_dir: str) -> list:
    """Newest first, with everything a listing page needs."""
    directory = resolve_output_dir(output_dir)
    if not directory.exists():
        return []

    videos = []
    for path in directory.rglob("*.mp4"):
        meta_path = _sidecar(path, "meta.txt")
        links = load_publish_info(path)
        videos.append({
            "relpath": str(path.relative_to(OUTPUT_DIR)).replace("\\", "/"),
            "name": path.name,
            "title": video_title(path.name),
            "mtime": path.stat().st_mtime,
            "meta_text": read_text_tolerantly(meta_path) if meta_path.exists() else None,
            "links": links,
            "published": is_published(links),
            "discarded": links["discarded"],
            "cost": load_cost_summary(path),
            "report": load_report(path),
            "title": links["title"] or video_title(path.name),
            "description": links["description"],
        })
    videos.sort(key=lambda v: v["mtime"], reverse=True)
    return videos


# --- deleting a discarded take ----------------------------------------
#
# Discarding is reversible and cheap: the files stay, the flag flips. That
# is right for a decision made in the review queue, and wrong forever —
# this project's own output directory reached 416 MB of discarded takes
# before anything could remove one.
#
# The catch is that /insights is built entirely on `rglob("*.mp4")`, so
# deleting the video deletes the fact that it was ever discarded and why.
# A daily loop of "discard, then clean up" would quietly erase the only
# measurement of whether the output is getting better. So a purge leaves a
# tombstone behind: one line per video, enough for the statistics and
# nothing else.

# Everything written beside a video, by suffix. Explicit rather than
# `glob(stem + "_*")` because a stem is a prefix of other stems —
# `john_3_1` would sweep up `john_3_16`'s files.
SIDECAR_SUFFIXES = (
    "audio.mp3", "meta.txt", "description.txt", "publish.json",
    "thumb.jpg", "cost.json", "report.json",
)


def sidecars_of(video_path: Path) -> list:
    """Every file belonging to one video, the video itself included."""
    video_path = Path(video_path)
    found = [video_path] if video_path.exists() else []
    found += [p for p in (_sidecar(video_path, s) for s in SIDECAR_SUFFIXES) if p.exists()]
    # Per-segment audio: numbered, so it can't be listed by suffix.
    found += sorted(video_path.parent.glob(f"{video_path.stem}_audio_seg*.mp3"))
    return found


def purge(video_path: Path, channel_key: str = "") -> dict:
    """Delete a discarded video and everything beside it, keeping a
    tombstone so it still counts in the discard statistics.

    Refuses anything not marked discarded. A published or waiting video is
    never deletable by accident — the only route to deleting one is to
    discard it first, which is a decision made in the review queue with a
    reason attached.
    """
    video_path = Path(video_path)
    info = load_publish_info(video_path)
    if not info["discarded"]:
        raise ValueError(f"{video_path.name} is not discarded")

    files = sidecars_of(video_path)
    freed = sum(f.stat().st_size for f in files)
    _write_tombstone(video_path, info, channel_key, freed)
    for path in files:
        path.unlink()
    return {"files": len(files), "bytes": freed}


def _write_tombstone(video_path: Path, info: dict, channel_key: str, freed: int) -> None:
    record = {
        "channel": channel_key,
        "stem": Path(video_path).stem,
        "discard_reason": info.get("discard_reason"),
        "discarded_at": info.get("discarded_at"),
        "purged_at": datetime.now(timezone.utc).isoformat(),
        "bytes_freed": freed,
    }
    DISCARD_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DISCARD_HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def purged_records(channel_key: str = None) -> list:
    """Tombstones, optionally for one channel.

    Returns [] rather than raising if the file is missing or a line is
    corrupt: a damaged history should cost you a statistic, not a page.
    """
    if not DISCARD_HISTORY_PATH.exists():
        return []
    records = []
    for line in DISCARD_HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if channel_key is None or record.get("channel") == channel_key:
            records.append(record)
    return records


def orphaned_files(output_dir: str) -> list:
    """Sidecars whose video no longer exists.

    A crashed run leaves its per-segment audio behind — the voiceover
    stage writes those before the render that would have consumed them.
    Nothing else notices, because every listing enumerates mp4s.
    """
    directory = resolve_output_dir(output_dir)
    if not directory.exists():
        return []
    stems = {p.stem for p in directory.rglob("*.mp4")}
    orphans = []
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix == ".mp4":
            continue
        stem = path.stem
        for suffix in ("_audio", "_meta", "_description", "_publish",
                       "_thumb", "_cost", "_report"):
            if suffix in stem:
                stem = stem[:stem.rindex(suffix)]
                break
        if stem and stem not in stems:
            orphans.append(path)
    return sorted(orphans)
