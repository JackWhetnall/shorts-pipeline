"""
Merch product photo uploads — collected during the monetization wizard's
"merch" step, shown on the video end screen when the merch CTA is picked
(video_assemble._render_end_screen_image) and in the settings/wizard UI.

Stored under channels/<key>/merch/, parallel to channels/<key>/logo/ —
see webapp/logo_gen.py's module docstring for why this lives outside
output/ (brand assets, not finished videos or stock footage). Lives at
the project root, not under webapp/, because video_assemble.py (a plain
pipeline module the CLI uses with no Flask involved) needs it too.
"""

from pathlib import Path

from werkzeug.utils import secure_filename

PROJECT_ROOT = Path(__file__).resolve().parent
CHANNELS_DIR = PROJECT_ROOT / "channels"

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def merch_dir(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "merch"


def list_merch_photos(channel_key: str) -> list:
    d = merch_dir(channel_key)
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.suffix.lower() in ALLOWED_EXTENSIONS)


def save_merch_upload(channel_key: str, file_storage) -> Path:
    """file_storage: a werkzeug FileStorage from request.files. Raises
    ValueError for an unrecognized extension rather than silently saving
    something that won't composite cleanly onto the end screen."""
    filename = secure_filename(file_storage.filename or "")
    ext = Path(filename).suffix.lower()
    if not filename or ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {file_storage.filename!r}")

    d = merch_dir(channel_key)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / filename
    # Avoid clobbering an existing upload with the same filename.
    i = 2
    while dest.exists():
        dest = d / f"{Path(filename).stem}_{i}{ext}"
        i += 1
    file_storage.save(dest)
    return dest


def delete_merch_photo(channel_key: str, filename: str):
    target = (merch_dir(channel_key) / secure_filename(filename)).resolve()
    if merch_dir(channel_key).resolve() not in target.parents:
        raise ValueError("Invalid filename")
    target.unlink(missing_ok=True)
