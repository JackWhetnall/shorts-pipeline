"""
CLI for growing the shared footage library (footage/manifest.json +
footage/library/*.mp4). Descriptions are generated automatically from the
clip's own frames via Claude's vision API — you don't invent tags/keywords
by hand, and matching (footage_library.pick_clips_for_beats) works off
these natural-language descriptions instead of a controlled vocabulary.

Usage:
    python footage/manage_library.py add raw_clip.mp4
    python footage/manage_library.py add raw_clip.mp4 --notes "camera pans slowly left"
    python footage/manage_library.py list

For a batch of new downloads where naive center-cropping might cut off
the subject, use review_new_downloads.py instead — it lets you pick the
crop per clip, then calls add_normalized_clip() here to finish the job.

Requires no system ffmpeg install — reuses the same bundled ffmpeg binary
moviepy already depends on (imageio-ffmpeg). Requires ANTHROPIC_API_KEY
for the description step.
"""

import argparse
import base64
import io
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import imageio_ffmpeg
from moviepy.editor import VideoFileClip
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from llm_json import client  # noqa: E402

ROOT = Path(__file__).parent
LIBRARY_DIR = ROOT / "library"
MANIFEST_PATH = ROOT / "manifest.json"

W, H = 1080, 1920
DESCRIBE_MODEL = "claude-sonnet-4-6"
FRAME_COUNT = 3

# Perceptual-hash duplicate check: a cheap, local, pre-API-call filter for
# "this is the same stock clip already in the library, just downloaded
# again" — common when overlapping searches (or both Pexels and Pixabay)
# return the same underlying footage. Single mid-clip frame, average hash
# (8x8 grayscale, bit = pixel >= mean) — not foolproof (won't catch a
# duplicate whose middle frame differs, e.g. a very different camera
# position at that moment), but catches the common case for free before
# spending a vision API call on a clip that's already here.
HASH_SIZE = 8
DUPLICATE_HAMMING_THRESHOLD = 6  # out of 64 bits differing

VISION_PROMPT = (
    "These are frames from a short vertical stock video clip used as "
    "background footage in short-form videos about Bible verses and "
    "Shakespeare quotes. Write a concrete, 2-4 sentence natural-language "
    "description of what's visually in this clip: subject, setting, mood, "
    "lighting, and any motion. Be specific and literal (colors, objects, "
    "framing) rather than vague single-word labels — this description is "
    "used later to match the clip against short quotes/themes by meaning, "
    "not keyword lookup. Don't guess at symbolism. Respond with ONLY the "
    "description, no preamble."
)


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"clips": []}


def _save_manifest(manifest: dict):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def _normalize(src: Path, dest: Path, x_expr: str = "(in_w-out_w)/2", y_expr: str = "(in_h-out_h)/2"):
    """Scale to fill 1080x1920, crop at the given offset, strip audio.
    x_expr/y_expr are ffmpeg crop-filter expressions (in_w/in_h/out_w/out_h
    available) — default is a dead-center crop; review_new_downloads.py
    passes an off-center offset when that's a better fit."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:x={x_expr}:y={y_expr}"
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-vf", vf, "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        str(dest),
    ]
    subprocess.run(cmd, check=True)


def _extract_frames(path: Path, count: int = FRAME_COUNT) -> list:
    clip = VideoFileClip(str(path))
    frames = []
    for i in range(count):
        frac = (i + 1) / (count + 1)
        t = min(clip.duration * frac, max(clip.duration - 0.05, 0))
        frames.append(Image.fromarray(clip.get_frame(t)))
    clip.close()
    return frames


def _frame_hash(image: Image.Image) -> int:
    small = image.convert("L").resize((HASH_SIZE, HASH_SIZE), Image.LANCZOS)
    pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    return int(bits, 2)


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _clip_hashes(path: Path) -> list:
    """One average-hash per frame in _extract_frames' sample (spread across
    the clip, same timestamps used for the description step)."""
    return [_frame_hash(f) for f in _extract_frames(path, count=FRAME_COUNT)]


def _is_duplicate(hashes_a: list, duration_a: float, hashes_b: list, duration_b: float) -> bool:
    """A single frame's average hash is too coarse to trust alone — two
    unrelated clips that happen to share a similar bright/dark layout at one
    sampled moment (e.g. a crowd photo and a wave photo, both pale top /
    textured bottom) can land within a few bits of each other by pure
    chance. This nearly caused real, distinct footage to be deleted as a
    "duplicate" (see the incident this replaced). Requiring EVERY sampled
    frame to independently match, plus a similar duration, makes a false
    positive extremely unlikely — two different videos coincidentally
    matching at all sample points AND running the same length essentially
    doesn't happen, while true duplicates (the same source re-encoded,
    or re-exported at a different crop) still match closely throughout."""
    if len(hashes_a) != len(hashes_b):
        return False
    if abs(duration_a - duration_b) > max(1.0, 0.15 * min(duration_a, duration_b)):
        return False
    return all(_hamming(a, b) <= DUPLICATE_HAMMING_THRESHOLD for a, b in zip(hashes_a, hashes_b))


def _find_duplicate(new_hashes: list, new_duration: float, manifest: dict, skip_filename: str = None) -> dict:
    """Compares against every existing clip's stored hashes, backfilling
    any missing ones from file as encountered (so older entries added
    before this check existed get covered too). Returns the first
    sufficiently-close entry, or None."""
    changed = False
    match = None
    for clip in manifest["clips"]:
        if clip["filename"] == skip_filename:
            continue
        if "frame_hashes" not in clip:
            clip_path = LIBRARY_DIR / clip["filename"]
            if not clip_path.exists():
                continue
            try:
                clip["frame_hashes"] = _clip_hashes(clip_path)
                changed = True
            except Exception:
                continue
        if match is None and _is_duplicate(new_hashes, new_duration, clip["frame_hashes"], clip["duration"]):
            match = clip
    if changed:
        _save_manifest(manifest)
    return match


def _describe_clip(frames: list) -> str:
    content = []
    for frame in frames:
        buf = io.BytesIO()
        frame.convert("RGB").save(buf, format="JPEG", quality=85)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(buf.getvalue()).decode("ascii"),
            },
        })
    content.append({"type": "text", "text": VISION_PROMPT})

    response = client.messages.create(
        model=DESCRIBE_MODEL,
        max_tokens=250,
        messages=[{"role": "user", "content": content}],
    )
    return " ".join(response.content[0].text.strip().split())


def add_normalized_clip(normalized_path: Path, dest_name: str = None, source: str = None,
                         license_: str = None, notes: str = None) -> dict:
    """Describes an already-normalized (1080x1920, no audio) clip via
    Claude's vision API and adds/updates its entry in the manifest. Copies
    the file into footage/library/ if it isn't already there. Returns the
    manifest entry."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    normalized_path = Path(normalized_path)

    dest_name = dest_name or (normalized_path.stem.lower().replace(" ", "_") + ".mp4")
    if not dest_name.endswith(".mp4"):
        dest_name += ".mp4"
    dest = LIBRARY_DIR / dest_name

    if normalized_path.resolve() != dest.resolve():
        shutil.copy2(normalized_path, dest)

    clip = VideoFileClip(str(dest))
    duration = round(clip.duration, 2)
    clip.close()

    frames = _extract_frames(dest)
    new_hashes = [_frame_hash(f) for f in frames]

    manifest = _load_manifest()
    duplicate = _find_duplicate(new_hashes, duration, manifest, skip_filename=dest_name)
    if duplicate:
        print(f"  Skipping {dest_name} - looks like a duplicate of already-in-library "
              f"'{duplicate['filename']}' (perceptual match, no API call made).")
        dest.unlink(missing_ok=True)
        return duplicate

    print(f"  Describing {dest_name} ...")
    description = _describe_clip(frames)
    if notes:
        description = f"{description} {notes.strip()}"

    manifest["clips"] = [c for c in manifest["clips"] if c["filename"] != dest_name]
    entry = {
        "filename": dest_name,
        "description": description,
        "duration": duration,
        "frame_hashes": new_hashes,
        "source": source or str(normalized_path),
        "license": license_ or "unverified - confirm before scaling/monetizing",
        "added": datetime.now(timezone.utc).date().isoformat(),
        "use_count": 0,
        "last_used": None,
    }
    manifest["clips"].append(entry)
    _save_manifest(manifest)
    print(f"Added {dest_name} ({duration}s): {description}")
    return entry


def cmd_add(args):
    src = Path(args.file)
    if not src.exists():
        raise FileNotFoundError(src)

    dest_name = args.name or (src.stem.lower().replace(" ", "_") + ".mp4")
    if not dest_name.endswith(".mp4"):
        dest_name += ".mp4"
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    normalized = LIBRARY_DIR / dest_name

    print(f"Normalizing {src.name} -> footage/library/{dest_name} ...")
    _normalize(src, normalized)

    add_normalized_clip(normalized, dest_name=dest_name, source=args.source,
                         license_=args.license, notes=args.notes)


def cmd_list(args):
    manifest = _load_manifest()
    if not manifest["clips"]:
        print("No clips in the library yet.")
        return
    for clip in manifest["clips"]:
        print(f"{clip['filename']}  ({clip['duration']:.1f}s, used {clip['use_count']}x)")
        print(f"    {clip.get('description', '(no description)')}")


def _cluster_duplicates(clips: list) -> list:
    """Groups clips into connected components under the multi-frame+duration
    match (not just pairwise) — three-plus mutually-close clips (e.g. the
    same source clip added under three different names) need to collapse
    into one group with one keeper, not be resolved pair-by-pair, which
    could otherwise delete the "keeper" chosen for one pair to satisfy
    another.

    A connected component is only trusted as a real duplicate group if
    it's a full clique — every pair inside it independently matches, not
    just chained through a middle clip. A group that connects but isn't a
    clique (e.g. A matches B, B matches C, but A and C don't match each
    other) is ambiguous — a weak match on one edge dragged in something
    that isn't really the same as everything else in the group — and gets
    reported separately instead of auto-resolved. This is a direct fix for
    a real incident: an early version of this check chained a "large crowd
    gathering" clip to an "ocean waves" clip through a third clip, and
    would have deleted genuinely distinct footage as a false positive."""
    n = len(clips)
    match = [[False] * n for _ in range(n)]
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if _is_duplicate(clips[i]["frame_hashes"], clips[i]["duration"],
                              clips[j]["frame_hashes"], clips[j]["duration"]):
                pairs.append((i, j))
                match[i][j] = match[j][i] = True
                union(i, j)

    by_root = {}
    for i in range(n):
        by_root.setdefault(find(i), []).append(i)

    cliques, ambiguous = [], []
    for idxs in by_root.values():
        if len(idxs) < 2:
            continue
        is_clique = all(match[a][b] for a in idxs for b in idxs if a != b)
        (cliques if is_clique else ambiguous).append(idxs)
    return pairs, cliques, ambiguous


def _keeper(group: list) -> dict:
    """Picks which clip in a duplicate group to keep: the one already used
    more (so in-flight/past videos referencing it stay valid), tie-broken
    by whichever was added first (the more established entry)."""
    return sorted(group, key=lambda c: (-c.get("use_count", 0), c.get("added", "")))[0]


def cmd_find_duplicates(args):
    """Audits the CURRENT library for likely duplicates: every sampled
    frame's average hash must match AND durations must be close (see
    _is_duplicate) — a single-frame check turned out to false-positive on
    unrelated clips that just happen to share a similar bright/dark
    layout. By default just reports what it found so you can review and
    clean up manually. With --delete, actually removes the unambiguous
    ones: within each full-clique group of mutually-matching clips, keeps
    the most-used (tie: earliest added) and deletes the rest (file +
    manifest entry). A group that isn't a full clique — some pairs match,
    others don't — is never auto-deleted, only reported, since that's
    exactly the shape of match that produced a false positive before.
    Backfills any missing frame_hashes on the way, same as
    add_normalized_clip does for new clips."""
    manifest = _load_manifest()
    clips = manifest["clips"]
    changed = False
    for clip in clips:
        if "frame_hashes" not in clip:
            clip_path = LIBRARY_DIR / clip["filename"]
            if not clip_path.exists():
                continue
            try:
                clip["frame_hashes"] = _clip_hashes(clip_path)
                changed = True
            except Exception as e:
                print(f"  Could not hash {clip['filename']}: {e}")
    if changed:
        _save_manifest(manifest)

    hashed = [c for c in clips if "frame_hashes" in c]
    pairs, cliques, ambiguous = _cluster_duplicates(hashed)

    if not pairs:
        print("No likely duplicates found.")
        return

    for idxs in cliques:
        names = ", ".join(hashed[i]["filename"] for i in idxs)
        print(f"  Duplicate group (all clips match each other): {names}")
    for idxs in ambiguous:
        names = ", ".join(hashed[i]["filename"] for i in idxs)
        print(f"  Ambiguous group (some but not all pairs match — review manually, "
              f"not auto-removable): {names}")

    if not args.delete:
        n_dupes = sum(len(g) - 1 for g in cliques)
        print(f"\n{len(cliques)} confident duplicate group(s), {n_dupes} clip(s) removable, "
              f"plus {len(ambiguous)} ambiguous group(s) needing manual review. "
              f"Re-run with --delete to keep the most-used clip in each confident "
              f"group and remove the rest (ambiguous groups are left alone).")
        return

    removed_names = set()
    for group_idxs in cliques:
        group = [hashed[i] for i in group_idxs]
        keep = _keeper(group)
        for clip in group:
            if clip["filename"] == keep["filename"]:
                continue
            clip_path = LIBRARY_DIR / clip["filename"]
            clip_path.unlink(missing_ok=True)
            removed_names.add(clip["filename"])
            print(f"  Removed {clip['filename']} (duplicate of kept '{keep['filename']}')")

    manifest["clips"] = [c for c in manifest["clips"] if c["filename"] not in removed_names]
    _save_manifest(manifest)
    print(f"\nRemoved {len(removed_names)} duplicate clip(s), "
          f"library now has {len(manifest['clips'])} clips.")
    if ambiguous:
        print(f"{len(ambiguous)} ambiguous group(s) left untouched — review those manually.")


def main():
    parser = argparse.ArgumentParser(description="Manage the shared footage library.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Normalize a clip, describe it, and add it to the library")
    p_add.add_argument("file", help="Path to the raw video file")
    p_add.add_argument("--name", help="Filename to save as (default: derived from the source filename)")
    p_add.add_argument("--notes", help="Extra context Claude can't infer from static frames (e.g. camera motion)")
    p_add.add_argument("--source", help="Where this clip came from (URL, etc.)")
    p_add.add_argument("--license", default="unverified - confirm before scaling/monetizing")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List clips currently in the library")
    p_list.set_defaults(func=cmd_list)

    p_dupes = sub.add_parser("find-duplicates", help="Scan the current library for likely duplicate clips")
    p_dupes.add_argument("--delete", action="store_true",
                          help="Actually remove duplicates (keep the most-used clip per group)")
    p_dupes.set_defaults(func=cmd_find_duplicates)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
