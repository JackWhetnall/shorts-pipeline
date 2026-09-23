"""
A dated zip of everything on this machine that can't be regenerated.

Nothing was backed up. The code had no remote, and `config/` holds state
that nothing else can rebuild: the script history the originality check
compares against, the topic plans, the cost and discard logs. One disk
failure would lose all of it.

What goes in, and what deliberately doesn't:

- **config/** — all of it, except credentials (the YouTube OAuth client
  and per-channel refresh tokens). Those are re-created by reconnecting,
  and a zip of live tokens sitting in a sync folder is a worse risk than
  a reconnect. `include_secrets=True` overrides this.
- **channels/** — logos (paid image generations), merch photos and card
  backgrounds. Small.
- **output/ sidecars** — publish state, titles, reports, costs. The
  videos themselves are left out: they're large, and a published video
  already lives on the platform.
- **footage/library.db** — copied through SQLite's backup API, which
  gives a consistent snapshot even while the app has it open. The clip
  files are left out: every clip's source URL is recorded, so they can
  be fetched again, and they're gigabytes.
"""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from core.errors import ConfigError
from core.logging_setup import get_logger
from core.paths import PROJECT_ROOT

log = get_logger(__name__)

ARCHIVE_PREFIX = "shorts-backup-"
DEFAULT_KEEP = 14

# Relative to config/. Re-created by reconnecting on /youtube/setup.
SECRET_PATHS = ("youtube_client.json", "youtube_tokens")

# Output sidecars worth keeping; the media files beside them are not.
SIDECAR_SUFFIXES = (".json", ".txt")


def _is_secret(relative: Path) -> bool:
    return relative.parts[0] in SECRET_PATHS


def _add_tree(archive: zipfile.ZipFile, base: Path, prefix: str, keep=lambda p: True) -> int:
    if not base.exists():
        return 0
    count = 0
    for path in sorted(base.rglob("*")):
        if path.is_file() and keep(path.relative_to(base)):
            archive.write(path, arcname=f"{prefix}/{path.relative_to(base).as_posix()}")
            count += 1
    return count


def _snapshot_db(db_path: Path, into: Path) -> None:
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(into)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def create_backup(dest_dir, *, keep: int = DEFAULT_KEEP, include_secrets: bool = False,
                  root: Path = None) -> Path:
    """Write one dated zip into `dest_dir`, prune older ones down to
    `keep`, and return the new zip's path."""
    root = Path(root or PROJECT_ROOT)
    dest_dir = Path(dest_dir)
    if keep < 1:
        raise ConfigError(f"keep={keep}", user_message="Keep at least one backup.")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(
            f"cannot create {dest_dir}: {exc}",
            user_message=f"Couldn't create the backup folder {dest_dir}.") from exc
    if dest_dir.resolve().is_relative_to(root.resolve()):
        raise ConfigError(
            f"{dest_dir} is inside the project",
            user_message=("The backup folder is inside the project itself. Pick "
                          "somewhere else, ideally a synced folder like OneDrive."))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = dest_dir / f"{ARCHIVE_PREFIX}{stamp}.zip"
    partial = zip_path.with_suffix(".partial")

    counts = {}
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        counts["config"] = _add_tree(
            archive, root / "config", "config",
            keep=lambda rel: include_secrets or not _is_secret(rel))
        counts["channels"] = _add_tree(archive, root / "channels", "channels")
        counts["output"] = _add_tree(
            archive, root / "output", "output",
            keep=lambda rel: rel.suffix.lower() in SIDECAR_SUFFIXES)

        db_path = root / "footage" / "library.db"
        if db_path.exists():
            with tempfile.TemporaryDirectory() as tmp:
                snapshot = Path(tmp) / "library.db"
                _snapshot_db(db_path, snapshot)
                archive.write(snapshot, arcname="footage/library.db")
            counts["footage"] = 1

    # Renamed only once complete, so a crash mid-write never leaves
    # something that looks like a good backup.
    partial.replace(zip_path)

    size_mb = zip_path.stat().st_size / 1e6
    summary = ", ".join(f"{n} {k}" for k, n in counts.items())
    log.info(f"Backup written: {zip_path} ({size_mb:.1f} MB; {summary} file(s)).")

    for old in sorted(dest_dir.glob(f"{ARCHIVE_PREFIX}*.zip"))[:-keep]:
        old.unlink()
        log.info(f"Removed old backup {old.name}.")
    return zip_path
