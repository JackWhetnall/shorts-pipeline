"""
Getting a raw clip into the library: normalize, check it isn't already
here, describe it, record it.

The describe step is a vision call and is the expensive part, so the
perceptual-duplicate check runs first — overlapping searches, and Pexels
and Pixabay both indexing the same underlying footage, make re-downloads
common.

That check requires EVERY sampled frame to match AND the durations to be
close. A single-frame version was tried first and caused a real incident:
two completely unrelated clips (a crowd shot and a wave shot) shared a
similar coarse bright/dark layout at one sampled moment by chance, and
were nearly deleted as duplicates. Agreement across every frame plus
duration makes that essentially impossible while still catching genuine
re-encodes.

The vision prompt used to open with "frames from a short vertical stock
video clip used as background footage in short-form videos about Bible
verses and Shakespeare quotes." The library is shared by every channel
and the pipeline's central design claim is that it's format-agnostic, so
that framing biased what the model bothered to mention — and therefore
what could ever be matched — toward one content type. It's now neutral.
"""

from __future__ import annotations

import base64
import io
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import FRAME_HEIGHT, FRAME_WIDTH, LIBRARY_DIR
from pipeline import llm
from pipeline.footage import store

log = get_logger(__name__)

FRAME_COUNT = 3

# Largest size a frame is sent at for description. See describe().
DESCRIBE_MAX_SIZE = (FRAME_WIDTH // 2, FRAME_HEIGHT // 2)

# 8x8 average hash: 64 bits per frame, comparing each pixel against the
# frame's mean brightness.
HASH_SIZE = 8
DUPLICATE_HAMMING_THRESHOLD = 6   # bits differing, out of 64
DURATION_TOLERANCE = 0.15         # fraction of the shorter clip

VISION_PROMPT = (
    "These are frames from a short vertical stock video clip, used as background "
    "footage in short-form videos on any subject. Write a concrete, 2-4 sentence "
    "description of what is visually in this clip: subject, setting, mood, lighting, "
    "and any motion. Be specific and literal about colors, objects and framing rather "
    "than using vague single-word labels — this description is later matched against "
    "short pieces of script by meaning, not keyword lookup. Describe only what is "
    "actually visible; do not infer symbolism or narrative. Respond with ONLY the "
    "description, no preamble."
)


def normalize(src: Path, dest: Path, x_expr: str = "(in_w-out_w)/2",
              y_expr: str = "(in_h-out_h)/2") -> None:
    """Scale to fill the output frame, crop, strip audio.

    x_expr/y_expr are ffmpeg crop expressions; the default is a dead
    centre crop. The interactive intake tool passes an off-centre offset,
    because centre-cropping is wrong whenever the subject isn't centred
    on the axis being cropped.

    Uses the ffmpeg binary imageio-ffmpeg already ships, so there's no
    system ffmpeg install to manage.
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    vf = (f"scale={FRAME_WIDTH}:{FRAME_HEIGHT}:force_original_aspect_ratio=increase,"
          f"crop={FRAME_WIDTH}:{FRAME_HEIGHT}:x={x_expr}:y={y_expr}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [ffmpeg, "-y", "-i", str(src), "-vf", vf, "-an",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(dest)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise PipelineError(
            f"ffmpeg failed to normalize {src.name}: "
            f"{result.stderr.decode(errors='replace')[-500:]}",
            user_message=f"Couldn't process the video file {src.name}. It may be corrupt.",
        )


def extract_frames(path: Path, count: int = FRAME_COUNT) -> list:
    """Frames spread across the clip, avoiding the very start and end
    (fades and black frames make poor samples for both hashing and
    description)."""
    from moviepy.editor import VideoFileClip

    clip = VideoFileClip(str(path))
    try:
        frames = []
        for i in range(count):
            frac = (i + 1) / (count + 1)
            t = min(clip.duration * frac, max(clip.duration - 0.05, 0))
            frames.append(Image.fromarray(clip.get_frame(t)))
        return frames
    finally:
        clip.close()


def clip_duration(path: Path) -> float:
    from moviepy.editor import VideoFileClip

    clip = VideoFileClip(str(path))
    try:
        return round(clip.duration, 2)
    finally:
        clip.close()


def frame_hash(image: Image.Image) -> int:
    small = image.convert("L").resize((HASH_SIZE, HASH_SIZE), Image.LANCZOS)
    pixels = list(small.getdata())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= average else "0" for p in pixels)
    return int(bits, 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def is_duplicate(hashes_a: list, duration_a: float,
                 hashes_b: list, duration_b: float) -> bool:
    """Same clip? Every sampled frame must match AND durations must be
    close.

    Both conditions are load-bearing. Frame agreement alone false-positives
    on unrelated footage that happens to share a coarse light/dark layout
    at one moment; duration alone obviously proves nothing. Together, two
    genuinely different videos matching at every sample point and running
    the same length essentially doesn't happen, while a re-encode or
    re-export of the same source still matches throughout.
    """
    if not hashes_a or not hashes_b or len(hashes_a) != len(hashes_b):
        return False
    if abs(duration_a - duration_b) > max(1.0, DURATION_TOLERANCE * min(duration_a, duration_b)):
        return False
    return all(hamming(a, b) <= DUPLICATE_HAMMING_THRESHOLD for a, b in zip(hashes_a, hashes_b))


def find_duplicate(hashes: list, duration: float, skip_filename: str = None,
                   db_path=None):
    """The first library clip this one duplicates, or None."""
    for clip in store.all_clips(db_path=db_path):
        if clip.filename == skip_filename or not clip.frame_hashes:
            continue
        if is_duplicate(hashes, duration, clip.frame_hashes, clip.duration):
            return clip
    return None


def describe(frames: list) -> str:
    """A prose description of a clip from its sampled frames.

    Frames are sent at half the output resolution. At full 1080x1920
    each one cost roughly 2,000 image tokens, which made describing a
    fetched clip the second-largest line on the Claude bill; at 540x960
    it's about a quarter of that. A description names the subject,
    setting, light and colour, none of which needs the full resolution.
    """
    images = []
    for frame in frames:
        small = frame.convert("RGB")
        small.thumbnail(DESCRIBE_MAX_SIZE, Image.LANCZOS)
        buffer = io.BytesIO()
        small.save(buffer, format="JPEG", quality=85)
        images.append(("image/jpeg", base64.b64encode(buffer.getvalue()).decode("ascii")))
    return llm.call_vision(VISION_PROMPT, images, operation="describe_clip")


def add_normalized_clip(normalized_path: Path, dest_name: str = None, source: str = None,
                        license_text: str = None, license_verified: bool = None,
                        notes: str = None, db_path=None) -> store.Clip:
    """Add an already-normalized clip to the library, describing it via
    the vision API unless it duplicates something already here.

    On a duplicate the new file is deleted and the EXISTING record is
    returned — which is also what stops the same physical clip being
    assigned to two shots in one video.
    """
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    normalized_path = Path(normalized_path)

    dest_name = dest_name or (normalized_path.stem.lower().replace(" ", "_") + ".mp4")
    if not dest_name.endswith(".mp4"):
        dest_name += ".mp4"
    dest = LIBRARY_DIR / dest_name

    if normalized_path.resolve() != dest.resolve():
        shutil.copy2(normalized_path, dest)

    duration = clip_duration(dest)
    frames = extract_frames(dest)
    hashes = [frame_hash(f) for f in frames]

    duplicate = find_duplicate(hashes, duration, skip_filename=dest_name, db_path=db_path)
    if duplicate:
        log.info(f"  [footage] {dest_name} duplicates {duplicate.filename} — "
                 f"skipped, no description call made.")
        dest.unlink(missing_ok=True)
        return duplicate

    log.info(f"  [footage] describing {dest_name} ...")
    description = describe(frames)
    if notes:
        description = f"{description} {notes.strip()}"

    if license_text is None:
        license_text, verified = store.license_for_source(source or "")
    else:
        verified = bool(license_verified)

    clip = store.Clip(
        filename=dest_name,
        description=description,
        duration=duration,
        source=source or str(normalized_path),
        license=license_text,
        license_verified=verified,
        added=datetime.now(timezone.utc).date().isoformat(),
        frame_hashes=hashes,
    )
    store.upsert(clip, db_path=db_path)
    log.info(f"  [footage] added {dest_name} ({duration}s)")
    return clip


# --- duplicate auditing ------------------------------------------------

def cluster_duplicates(clips: list) -> tuple:
    """Group mutually-duplicate clips.

    Returns (pairs, cliques, ambiguous). A group is only trusted — and
    only ever auto-deletable — when it's a full clique: every clip in it
    matches every other clip directly. A group that is merely connected
    (A matches B, B matches C, but A and C don't) is reported as
    ambiguous and left alone, because that chained shape is exactly what
    produced the original false positive.
    """
    n = len(clips)
    matched = [[False] * n for _ in range(n)]
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
            if is_duplicate(clips[i].frame_hashes, clips[i].duration,
                            clips[j].frame_hashes, clips[j].duration):
                pairs.append((i, j))
                matched[i][j] = matched[j][i] = True
                union(i, j)

    by_root = {}
    for i in range(n):
        by_root.setdefault(find(i), []).append(i)

    cliques, ambiguous = [], []
    for indices in by_root.values():
        if len(indices) < 2:
            continue
        is_clique = all(matched[a][b] for a in indices for b in indices if a != b)
        (cliques if is_clique else ambiguous).append(indices)
    return pairs, cliques, ambiguous


def keeper(group: list) -> store.Clip:
    """Which clip in a duplicate group survives: the most-used (so
    anything already referencing it stays valid), tie-broken by whichever
    was added first."""
    return sorted(group, key=lambda c: (-c.use_count, c.added))[0]
