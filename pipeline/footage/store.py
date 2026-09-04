"""
The footage library's clip store: SQLite, replacing a 320 KB JSON file
that was rewritten in full on every change.

The old manifest had three problems that all trace back to being one flat
file. Recording usage after a render loaded, parsed, mutated, serialised
and wrote all 320 KB once per clip — eight full round-trips for a typical
video. Nothing locked it, so a usage write racing an auto-fetch write
silently lost an entry. And every consumer that wanted a subset had to
load the whole thing and filter in Python, which is why the matcher ended
up sending all 264 descriptions to the model on every call.

SQLite fixes all three as a side effect of being a database, and its FTS5
extension provides the BM25 index that lets the matcher shortlist
candidates instead of sending the entire library (see retrieval.py). It's
in the standard library, so this adds no dependency.

Connections are opened per operation rather than shared. Writes here are
rare and small; the pipeline's concurrency is in downloads and API calls,
not in database access. WAL mode keeps readers from blocking on the
occasional write.

Licence data is first-class. Every clip in the imported library carried
"unverified - confirm before scaling/monetizing" — all 264 of them — with
no way to see that short of reading the JSON. `license_verified` is now a
real column the dashboard can count, and the stock-footage fetcher
records the actual licence its source publishes instead of the same
placeholder.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.errors import FootageLibraryError
from core.paths import LIBRARY_DB_PATH, LIBRARY_DIR, MANIFEST_PATH

UNVERIFIED_LICENSE = "unverified - confirm before scaling/monetizing"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    filename          TEXT PRIMARY KEY,
    description       TEXT NOT NULL DEFAULT '',
    duration          REAL NOT NULL DEFAULT 0,
    source            TEXT NOT NULL DEFAULT '',
    license           TEXT NOT NULL DEFAULT '',
    license_verified  INTEGER NOT NULL DEFAULT 0,
    added             TEXT NOT NULL DEFAULT '',
    use_count         INTEGER NOT NULL DEFAULT 0,
    last_used         TEXT,
    frame_hashes      TEXT NOT NULL DEFAULT '[]',

    -- Structured attributes, distilled from the prose description.
    -- `subject` is what the clip is ABOUT; the description also mentions
    -- everything incidentally visible, which is why matching against
    -- prose alone surfaces clips where the searched-for thing is a prop
    -- at the edge of frame rather than the point of the shot.
    subject           TEXT NOT NULL DEFAULT '',
    setting           TEXT NOT NULL DEFAULT '',
    motion            TEXT NOT NULL DEFAULT '',
    palette           TEXT NOT NULL DEFAULT '',
    time_of_day       TEXT NOT NULL DEFAULT '',
    has_people        INTEGER NOT NULL DEFAULT 0,

    -- Times a video using this clip was thrown away specifically for its
    -- footage. Your own judgement, fed back as a ranking signal.
    reject_count      INTEGER NOT NULL DEFAULT 0
);

-- Subject and setting are separate columns so bm25() can weight them
-- above the full description. A brief asking for "prayer beads" should
-- rank a clip that IS prayer beads over one that merely has some on the
-- table.
CREATE VIRTUAL TABLE IF NOT EXISTS clips_fts USING fts5(
    filename UNINDEXED,
    subject,
    setting,
    description,
    tokenize = 'porter unicode61'
);
"""

# Applied after _migrate, because an index cannot reference a column the
# migration has not added yet.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_clips_last_used ON clips(last_used);
CREATE INDEX IF NOT EXISTS idx_clips_subject ON clips(subject);
"""

# Column weights for bm25(): subject counts far more than the prose,
# setting somewhat more. Passed positionally in table column order,
# skipping the UNINDEXED filename.
FTS_WEIGHTS = (8.0, 3.0, 1.0)


@dataclass
class Clip:
    filename: str
    description: str = ""
    duration: float = 0.0
    source: str = ""
    license: str = UNVERIFIED_LICENSE
    license_verified: bool = False
    added: str = ""
    use_count: int = 0
    last_used: str = None
    frame_hashes: list = field(default_factory=list)
    # Structured attributes — see SCHEMA. Empty until enriched.
    subject: str = ""
    setting: str = ""
    motion: str = ""
    palette: str = ""
    time_of_day: str = ""
    has_people: bool = False
    reject_count: int = 0

    @property
    def enriched(self) -> bool:
        return bool(self.subject)

    @property
    def path(self) -> Path:
        return LIBRARY_DIR / self.filename

    def exists(self) -> bool:
        return self.path.exists()


def _get(row, key, default=None):
    """Tolerant column read.

    Rows come from several different SELECTs, and a database written
    before a column existed still has to load — the migration below adds
    columns in place, but a partial SELECT shouldn't crash either.
    """
    try:
        value = row[key]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _row_to_clip(row: sqlite3.Row) -> Clip:
    return Clip(
        filename=row["filename"],
        description=_get(row, "description", ""),
        duration=_get(row, "duration", 0.0),
        source=_get(row, "source", ""),
        license=_get(row, "license", UNVERIFIED_LICENSE),
        license_verified=bool(_get(row, "license_verified", 0)),
        added=_get(row, "added", ""),
        use_count=_get(row, "use_count", 0),
        last_used=_get(row, "last_used"),
        frame_hashes=json.loads(_get(row, "frame_hashes", "[]") or "[]"),
        subject=_get(row, "subject", ""),
        setting=_get(row, "setting", ""),
        motion=_get(row, "motion", ""),
        palette=_get(row, "palette", ""),
        time_of_day=_get(row, "time_of_day", ""),
        has_people=bool(_get(row, "has_people", 0)),
        reject_count=_get(row, "reject_count", 0),
    )


@contextmanager
def connect(db_path: Path = None):
    """One connection per operation, committed or rolled back as a unit.

    WAL mode is set on every open (it's a persistent property, so this is
    a no-op after the first time) and lets a read proceed while a write
    is in flight — which matters because footage downloads run
    concurrently and each finishes with a write."""
    db_path = Path(db_path or LIBRARY_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(INDEXES)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS does
# nothing to a table that already exists, so an existing database needs
# them added explicitly.
_ADDED_COLUMNS = (
    ("subject", "TEXT NOT NULL DEFAULT ''"),
    ("setting", "TEXT NOT NULL DEFAULT ''"),
    ("motion", "TEXT NOT NULL DEFAULT ''"),
    ("palette", "TEXT NOT NULL DEFAULT ''"),
    ("time_of_day", "TEXT NOT NULL DEFAULT ''"),
    ("has_people", "INTEGER NOT NULL DEFAULT 0"),
    ("reject_count", "INTEGER NOT NULL DEFAULT 0"),
)


def _migrate(conn) -> None:
    """Bring an existing database up to the current shape, in place.

    Runs on every connect and is a no-op once applied — cheap enough
    (two PRAGMA reads) that having no separate migration step to remember
    is worth more than the microseconds.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(clips)")}
    added = False
    for name, decl in _ADDED_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE clips ADD COLUMN {name} {decl}")
            added = True

    # The FTS table gained subject and setting columns. A virtual table
    # cannot be altered, so an old-shaped one is dropped and rebuilt from
    # the clips table — which is the source of truth anyway.
    fts_columns = {row["name"] for row in conn.execute("PRAGMA table_info(clips_fts)")}
    if "subject" not in fts_columns:
        conn.execute("DROP TABLE IF EXISTS clips_fts")
        conn.executescript(SCHEMA)
        added = True

    if added:
        conn.execute("DELETE FROM clips_fts")
        conn.execute(
            "INSERT INTO clips_fts (filename, subject, setting, description) "
            "SELECT filename, subject, setting, description FROM clips")


def _reindex(conn, clip: Clip) -> None:
    conn.execute("DELETE FROM clips_fts WHERE filename = ?", (clip.filename,))
    conn.execute(
        "INSERT INTO clips_fts (filename, subject, setting, description) "
        "VALUES (?, ?, ?, ?)",
        (clip.filename, clip.subject, clip.setting, clip.description))


def upsert(clip: Clip, db_path: Path = None) -> Clip:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO clips (filename, description, duration, source, license,
                               license_verified, added, use_count, last_used, frame_hashes,
                               subject, setting, motion, palette, time_of_day,
                               has_people, reject_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                description      = excluded.description,
                duration         = excluded.duration,
                source           = excluded.source,
                license          = excluded.license,
                license_verified = excluded.license_verified,
                frame_hashes     = excluded.frame_hashes,
                subject          = excluded.subject,
                setting          = excluded.setting,
                motion           = excluded.motion,
                palette          = excluded.palette,
                time_of_day      = excluded.time_of_day,
                has_people       = excluded.has_people
            """,
            (clip.filename, clip.description, clip.duration, clip.source, clip.license,
             int(clip.license_verified), clip.added or _today(), clip.use_count,
             clip.last_used, json.dumps(clip.frame_hashes),
             clip.subject, clip.setting, clip.motion, clip.palette,
             clip.time_of_day, int(clip.has_people), clip.reject_count),
        )
        _reindex(conn, clip)
    return clip


def get(filename: str, db_path: Path = None) -> Clip:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM clips WHERE filename = ?", (filename,)).fetchone()
    return _row_to_clip(row) if row else None


def all_clips(db_path: Path = None) -> list:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM clips ORDER BY filename").fetchall()
    return [_row_to_clip(r) for r in rows]


def count(db_path: Path = None) -> int:
    with connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]


def unverified_license_count(db_path: Path = None) -> int:
    """How many clips have no confirmed licence. Surfaced in the UI —
    this is the largest business risk in the project and it used to be
    visible only by reading a JSON file by hand."""
    with connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM clips WHERE license_verified = 0").fetchone()[0]


def delete(filenames, db_path: Path = None) -> int:
    filenames = list(filenames)
    if not filenames:
        return 0
    marks = ",".join("?" * len(filenames))
    with connect(db_path) as conn:
        cur = conn.execute(f"DELETE FROM clips WHERE filename IN ({marks})", filenames)
        conn.execute(f"DELETE FROM clips_fts WHERE filename IN ({marks})", filenames)
    return cur.rowcount


def mark_used(filenames, db_path: Path = None) -> None:
    """Record usage for every clip in a finished video in ONE statement.

    The previous implementation rewrote the entire 320 KB manifest once
    per clip. Recency data is what keeps the same footage from reappearing
    across consecutive videos, so it has to be written — it just doesn't
    have to be written like that.
    """
    filenames = [Path(f).name for f in filenames]
    if not filenames:
        return
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        conn.executemany(
            "UPDATE clips SET use_count = use_count + 1, last_used = ? WHERE filename = ?",
            [(now, name) for name in filenames],
        )


def record_rejections(filenames, db_path: Path = None) -> None:
    """Note that a video using these clips was discarded for its footage.

    This is the loop the discard reasons were added to close: your own
    repeated judgement, fed back as a ranking signal so clips you keep
    rejecting stop being offered first. It is a nudge, not a ban — one
    bad pairing doesn't make a clip bad.
    """
    filenames = [Path(f).name for f in filenames]
    if not filenames:
        return
    with connect(db_path) as conn:
        conn.executemany(
            "UPDATE clips SET reject_count = reject_count + 1 WHERE filename = ?",
            [(name,) for name in filenames])


def least_recently_used(limit: int, exclude: set = None, db_path: Path = None) -> list:
    """Clips least likely to look repetitive right now: never-used first,
    then oldest use. Used to top up a shortlist and to pick fallbacks."""
    exclude = exclude or set()
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM clips ORDER BY (last_used IS NOT NULL), last_used ASC LIMIT ?",
            (limit + len(exclude),),
        ).fetchall()
    clips = [_row_to_clip(r) for r in rows if r["filename"] not in exclude]
    return clips[:limit]


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --- import from the legacy JSON manifest -----------------------------

# Sources whose licence terms are published and unambiguous. A clip
# fetched from one of these is recorded as verified with the actual
# licence name, instead of everything sharing one placeholder string.
KNOWN_LICENSES = {
    "pexels": "Pexels License - free for commercial use, no attribution required",
    "pixabay": "Pixabay Content License - free for commercial use, no attribution required",
}


def license_for_source(source: str) -> tuple:
    """(license_text, verified). Falls back to unverified for anything
    whose provenance isn't recognised — a guess recorded as fact is worse
    than an honest unknown."""
    lowered = (source or "").lower()
    for marker, text in KNOWN_LICENSES.items():
        if marker in lowered:
            return text, True
    return UNVERIFIED_LICENSE, False


def import_manifest(manifest_path: Path = None, db_path: Path = None) -> dict:
    """One-time import of footage/manifest.json into the database.

    Idempotent: re-running updates existing rows rather than duplicating
    them. The JSON file is left in place as a backup — it's the only copy
    of this metadata and it took hundreds of vision calls to produce.

    The legacy `frame_hash` field (a single perceptual hash, superseded by
    the multi-frame `frame_hashes` and still present on 69 entries) is
    dropped. Nothing reads it.
    """
    manifest_path = Path(manifest_path or MANIFEST_PATH)
    if not manifest_path.exists():
        raise FootageLibraryError(
            f"No manifest at {manifest_path}",
            user_message="There's no footage manifest to import.",
        )
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    imported = 0
    for raw in manifest.get("clips", []):
        source = raw.get("source", "")
        license_text = raw.get("license") or ""
        verified = bool(license_text) and license_text != UNVERIFIED_LICENSE
        if not verified:
            license_text, verified = license_for_source(source)
        upsert(Clip(
            filename=raw["filename"],
            description=raw.get("description", ""),
            duration=float(raw.get("duration") or 0),
            source=source,
            license=license_text,
            license_verified=verified,
            added=raw.get("added") or _today(),
            use_count=int(raw.get("use_count") or 0),
            last_used=raw.get("last_used"),
            frame_hashes=raw.get("frame_hashes") or [],
        ), db_path=db_path)
        imported += 1

    return {"imported": imported, "total": count(db_path)}
