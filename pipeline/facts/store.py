"""
The fact store: facts/facts.db, one SQLite file.

- `entities`: Wikidata items the store knows (label, description, how
  many Wikipedias cover it, its English Wikipedia article and that
  article's `views` over the last year, the measure of fame), and when
  their facts were last pulled.
- `facts`: one statement each, subject + property + value, with the
  value's label and fame, how many values the subject has for that
  property (a question needs exactly one). How hard it is is worked out
  when a round is picked (pipeline.facts.levels) from the latest views;
  the `hardness` column is left over from the first stores. Never
  deleted: a fact Wikidata no longer states is `retired`, so what was
  asked stays on record.
- `categories`: a quiz category's definition (`spec`, see
  pipeline.facts.categories) and when it was last harvested.
- `members`: which entities belong to which category. A fact is in every
  category its subject belongs to, so it's valid for all of them and
  stored once.
- `used`: which facts each channel has asked, whichever category they
  came through: a fact is asked once per channel, ever.
- `runs`: background harvests, for the Facts page.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.paths import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "facts" / "facts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    qid TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sitelinks INTEGER NOT NULL DEFAULT 0,
    harvested_at TEXT,
    enwiki TEXT,
    views INTEGER,
    views_at TEXT
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL,
    property TEXT NOT NULL,
    value TEXT NOT NULL,
    value_label TEXT NOT NULL,
    value_description TEXT NOT NULL DEFAULT '',
    value_sitelinks INTEGER,
    kind TEXT NOT NULL,
    values_for_subject INTEGER NOT NULL DEFAULT 1,
    hardness REAL NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    retired INTEGER NOT NULL DEFAULT 0,
    UNIQUE (subject, property, value)
);
CREATE INDEX IF NOT EXISTS facts_subject ON facts (subject);
CREATE INDEX IF NOT EXISTS facts_value ON facts (property, value);
CREATE TABLE IF NOT EXISTS categories (
    name TEXT PRIMARY KEY,
    spec TEXT NOT NULL,
    created_at TEXT NOT NULL,
    harvested_at TEXT,
    depth INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS members (
    category TEXT NOT NULL,
    qid TEXT NOT NULL,
    PRIMARY KEY (category, qid)
);
CREATE INDEX IF NOT EXISTS members_qid ON members (qid);
CREATE TABLE IF NOT EXISTS used (
    fact_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    round TEXT NOT NULL DEFAULT '',
    used_at TEXT NOT NULL,
    PRIMARY KEY (fact_id, channel)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT
);
"""

_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # Columns added since the first stores were made.
    have = {r[1] for r in conn.execute("PRAGMA table_info(entities)")}
    for column, kind in (("enwiki", "TEXT"), ("views", "INTEGER"), ("views_at", "TEXT")):
        if column not in have:
            conn.execute(f"ALTER TABLE entities ADD COLUMN {column} {kind}")
    return conn


# --- entities and facts ---------------------------------------------------------------

def upsert_entities(conn, rows: list) -> None:
    """rows: [(qid, label, description, sitelinks)]."""
    with _lock, conn:
        conn.executemany(
            "INSERT INTO entities (qid, label, description, sitelinks) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (qid) DO UPDATE SET label = excluded.label, "
            "description = excluded.description, sitelinks = excluded.sitelinks", rows)


def unmeasured(conn, qids: list) -> list:
    """Which of these entities have no views measured yet."""
    out = []
    for start in range(0, len(qids), 500):
        chunk = qids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        out += [r[0] for r in conn.execute(
            f"SELECT qid FROM entities WHERE qid IN ({marks}) AND views IS NULL", chunk)]
    return out


def save_views(conn, titles: dict, views: dict, qids: list) -> None:
    """Record views for these entities: 0 for one with no English article."""
    stamp = now()
    with _lock, conn:
        conn.executemany("UPDATE entities SET enwiki = ?, views = ?, views_at = ? WHERE qid = ?",
                         [(titles.get(q), views.get(q, 0 if q not in titles else None), stamp, q)
                          for q in qids if q not in titles or q in views])


def unharvested(conn, qids: list, older_than: str = None) -> list:
    """Which of these entities have no facts pulled yet (or not since
    `older_than`)."""
    out = []
    for start in range(0, len(qids), 500):
        chunk = qids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        done = {r["qid"] for r in conn.execute(
            f"SELECT qid FROM entities WHERE qid IN ({marks}) AND harvested_at IS NOT NULL"
            + (" AND harvested_at >= ?" if older_than else ""),
            chunk + ([older_than] if older_than else []))}
        out += [q for q in chunk if q not in done]
    return out


def replace_facts(conn, subjects: list, facts: list) -> int:
    """Store what Wikidata states now about these subjects. `facts`:
    dicts with subject, property, value, value_label, value_description,
    value_sitelinks, kind, values_for_subject, hardness. A stored fact
    about one of them that's no longer stated is retired, not deleted.
    Returns how many facts are new."""
    stamp = now()
    with _lock, conn:
        before = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        for start in range(0, len(subjects), 500):
            chunk = subjects[start:start + 500]
            conn.execute(f"UPDATE facts SET retired = 1 WHERE subject IN ({','.join('?' * len(chunk))})",
                         chunk)
        conn.executemany(
            "INSERT INTO facts (subject, property, value, value_label, value_description, "
            "value_sitelinks, kind, values_for_subject, hardness, fetched_at, retired) "
            "VALUES (:subject, :property, :value, :value_label, :value_description, "
            ":value_sitelinks, :kind, :values_for_subject, :hardness, :fetched_at, 0) "
            "ON CONFLICT (subject, property, value) DO UPDATE SET "
            "value_label = excluded.value_label, value_description = excluded.value_description, "
            "value_sitelinks = excluded.value_sitelinks, values_for_subject = excluded.values_for_subject, "
            "hardness = excluded.hardness, fetched_at = excluded.fetched_at, retired = 0",
            [{**f, "fetched_at": stamp} for f in facts])
        conn.executemany("UPDATE entities SET harvested_at = ? WHERE qid = ?",
                         [(stamp, q) for q in subjects])
        after = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    return after - before


# --- categories ----------------------------------------------------------------------

def save_category(conn, name: str, spec: dict) -> None:
    with _lock, conn:
        conn.execute("INSERT INTO categories (name, spec, created_at) VALUES (?, ?, ?) "
                     "ON CONFLICT (name) DO UPDATE SET spec = excluded.spec",
                     (name, json.dumps(spec), now()))


def category(conn, name: str):
    """{"name", "spec", "harvested_at", "depth"} or None. Names match
    whatever their case."""
    row = conn.execute("SELECT * FROM categories WHERE lower(name) = lower(?)", (name,)).fetchone()
    if row is None:
        return None
    return {"name": row["name"], "spec": json.loads(row["spec"]), "harvested_at": row["harvested_at"],
            "depth": row["depth"]}


def categories(conn) -> list:
    return [category(conn, r["name"]) for r in conn.execute("SELECT name FROM categories ORDER BY name")]


def mark_harvested(conn, name: str, depth: int) -> None:
    with _lock, conn:
        conn.execute("UPDATE categories SET harvested_at = ?, depth = ? WHERE name = ?",
                     (now(), depth, name))


def add_members(conn, name: str, qids: list) -> None:
    with _lock, conn:
        conn.executemany("INSERT OR IGNORE INTO members (category, qid) VALUES (?, ?)",
                         [(name, q) for q in qids])


# --- asking --------------------------------------------------------------------------

def category_facts(conn, name: str = None) -> list:
    """Every live fact in a category (every fact at all, for None), with
    its subject's label, description and fame."""
    base = ("SELECT f.*, e.label AS subject_label, e.description AS subject_description, "
            "e.sitelinks AS subject_sitelinks, e.views AS subject_views "
            "FROM facts f JOIN entities e ON e.qid = f.subject ")
    if name is None:
        return list(conn.execute(base + "WHERE f.retired = 0"))
    return list(conn.execute(base + "JOIN members m ON m.qid = f.subject AND m.category = ? "
                             "WHERE f.retired = 0", (name,)))


def value_counts(conn, properties: list) -> dict:
    """{(property, value): how many live facts state it}, for these
    properties: a value held by one subject only can be asked backwards."""
    marks = ",".join("?" * len(properties))
    return {(r[0], r[1]): r[2] for r in conn.execute(
        f"SELECT property, value, COUNT(*) FROM facts WHERE retired = 0 AND property IN ({marks}) "
        f"GROUP BY property, value", list(properties))}


def used_ids(conn, channel: str) -> set:
    return {r[0] for r in conn.execute("SELECT fact_id FROM used WHERE channel = ?", (channel,))}


MIRRORS = {"P155": "P156", "P156": "P155"}


def mark_used(conn, channel: str, fact_ids: list, round_name: str = "") -> None:
    """These facts are asked on this channel. A fact stated both ways
    ("A was followed by B", "B follows A") is one fact: both are marked."""
    ids = set(fact_ids)
    for fid in fact_ids:
        row = conn.execute("SELECT subject, property, value FROM facts WHERE id = ?", (fid,)).fetchone()
        if row and row["property"] in MIRRORS:
            ids |= {r[0] for r in conn.execute(
                "SELECT id FROM facts WHERE subject = ? AND property = ? AND value = ?",
                (row["value"], MIRRORS[row["property"]], row["subject"]))}
    stamp = now()
    with _lock, conn:
        conn.executemany("INSERT OR IGNORE INTO used (fact_id, channel, round, used_at) VALUES (?, ?, ?, ?)",
                         [(fid, channel, round_name, stamp) for fid in ids])


# --- runs ----------------------------------------------------------------------------

def start_run(conn, action: str) -> int:
    with _lock, conn:
        return conn.execute("INSERT INTO runs (action, status, started_at) VALUES (?, 'running', ?)",
                            (action, now())).lastrowid


def update_run(conn, run_id: int, message: str, status: str = None) -> None:
    with _lock, conn:
        if status:
            conn.execute("UPDATE runs SET message = ?, status = ?, finished_at = ? WHERE id = ?",
                         (message, status, now(), run_id))
        else:
            conn.execute("UPDATE runs SET message = ? WHERE id = ?", (message, run_id))


def recent_runs(conn, limit: int = 10) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]


def running(conn) -> bool:
    return conn.execute("SELECT COUNT(*) FROM runs WHERE status = 'running'").fetchone()[0] > 0


# --- figures -------------------------------------------------------------------------

def totals(conn) -> dict:
    one = lambda sql: conn.execute(sql).fetchone()[0]
    return {"facts": one("SELECT COUNT(*) FROM facts WHERE retired = 0"),
            "entities": one("SELECT COUNT(*) FROM entities WHERE harvested_at IS NOT NULL"),
            "categories": one("SELECT COUNT(*) FROM categories")}
