"""
Quiz rounds made ahead from the bank, ready to use (decision 062).

A round used to be put together while its video was being made: pick ten
from the bank near the level, and if the bank was short, write more on
the spot, and failing that write the whole round unrated (that's how a
Medium Ancient History round asked about Babylon's code of laws).

Now each quiz channel keeps SETS_AHEAD rounds ready for every category at
every difficulty: ten questions within a tight band of the level (never
wider than the bank's second window), spread over shapes and areas, not
clashing with each other or repeating anything the channel has asked.
They're assembled locally, no model calls, whenever the bank changes and
hourly. Planning another set of a category uses ready rounds at no cost;
making a video takes its round and only writes the host's lines.

A category with no complete set ready (a ready round at every
difficulty) can't start another set: the topic plan says it's running
dry, and the bank's stocking and imports are what refill it. Picture
rounds (flags, countries) don't come from the bank; they're counted by
the pictures left that the channel hasn't asked.
"""

from __future__ import annotations

import json
import random

from core.logging_setup import get_logger
from pipeline.facts import bank, store

log = get_logger(__name__)

SETS_AHEAD = 3
WINDOWS = bank.WINDOWS[:2]            # (easier, harder) bands: never the widest

TABLE = """
CREATE TABLE IF NOT EXISTS ready_rounds (
    id INTEGER PRIMARY KEY,
    channel TEXT NOT NULL,
    category TEXT NOT NULL COLLATE NOCASE,
    label TEXT NOT NULL COLLATE NOCASE,
    level REAL NOT NULL,
    questions TEXT NOT NULL,
    made_at TEXT NOT NULL,
    subtopic TEXT,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS ready_rounds_slot ON ready_rounds (channel, category, label);
"""


def _table(conn) -> None:
    conn.executescript(TABLE)


def _reserved(conn, channel_key: str) -> set:
    """Questions in this channel's rounds not yet made into videos."""
    _table(conn)
    out = set()
    for (ids,) in conn.execute("SELECT questions FROM ready_rounds WHERE channel = ? AND used_at IS NULL",
                               (channel_key,)):
        out |= set(json.loads(ids))
    return out


def ready(conn, channel_key: str, category: str, label: str) -> int:
    """Ready rounds for one category at one difficulty, not yet claimed."""
    _table(conn)
    return conn.execute("SELECT COUNT(*) FROM ready_rounds WHERE channel = ? AND category = ? AND label = ? "
                        "AND used_at IS NULL AND subtopic IS NULL", (channel_key, category, label)).fetchone()[0]


def assemble(conn, channel, say=None) -> dict:
    """Top every text category up to SETS_AHEAD ready rounds at each of the
    channel's difficulties. Returns {category: {label: ready count}}."""
    from pipeline import quiz
    from pipeline.facts import keep
    _table(conn)
    count = channel.quiz.questions
    levels = quiz.levels(channel.quiz.difficulties)
    names = keep.quiz_categories(channel)
    if not names:
        return {}
    taken = _reserved(conn, channel.key)
    asked = [q for _, q in quiz._all_questions(channel.key)]
    out = {}
    rng = random.Random()
    # Named categories first: general knowledge can ask anything, so it
    # takes what they leave rather than the questions they need.
    from pipeline.facts import scope
    for name in sorted(names, key=lambda n: n.lower() in scope.GENERAL):
        pool = [r for r in bank.pool(conn, channel.key, name) if r["id"] not in taken]
        out[name] = {}
        for label, level in levels:
            have = ready(conn, channel.key, name, label)
            while have < SETS_AHEAD:
                chosen = _choose(pool, level, count, asked, rng)
                if not chosen:
                    break
                ids = [r["id"] for r in chosen]
                with conn:
                    conn.execute("INSERT INTO ready_rounds (channel, category, label, level, questions, made_at) "
                                 "VALUES (?, ?, ?, ?, ?, ?)",
                                 (channel.key, name, label, level, json.dumps(ids), store.now()))
                taken |= set(ids)
                asked += [{"question": r["question"], "answer": r["answer"]} for r in chosen]
                pool = [r for r in pool if r["id"] not in taken]
                have += 1
            out[name][label] = have
    if say:
        say("Rounds ready: " + "; ".join(f"{n} {min(v.values()) if v else 0}" for n, v in out.items()))
    return out


def _choose(pool: list, level: float, count: int, asked: list, rng) -> list:
    """One round's questions from `pool`: in the tightest band of `level`
    that has enough, spread over shapes and areas, then cleared of
    repeats and clashes."""
    from pipeline import quiz
    for easier, harder in WINDOWS:
        near = [r for r in pool if level - easier <= r["level"] <= level + harder]
        if len(near) < count:
            continue
        for _ in range(3):
            picked = bank._spread(near, count + 4, rng)
            rows = [{"question": r["question"], "answer": r["answer"], "row": r} for r in picked]
            bad = set(quiz.repeats(rows, "", among=asked)) | set(quiz.round_clashes(rows))
            good = [x["row"] for i, x in enumerate(rows) if i not in bad]
            if len(good) >= count:
                good = good[:count]
                good.sort(key=lambda r: r["level"])           # a round warms up
                return good
    return []


def sets_ready(conn, channel, category: str) -> int:
    """Complete sets of this category ready to plan: the fewest ready
    rounds at any one of the channel's difficulties."""
    from pipeline import quiz
    labels = [label for label, _ in quiz.levels(channel.quiz.difficulties)]
    return min((ready(conn, channel.key, category, label) for label in labels), default=0)


def status(conn, channel) -> dict:
    """{category: {"sets", "short": [labels with none ready], "state"}}:
    "ready" with SETS_AHEAD sets, "low" with fewer, "dry" with none."""
    from pipeline import quiz
    from pipeline.facts import keep
    labels = [label for label, _ in quiz.levels(channel.quiz.difficulties)]
    out = {}
    for name in keep.quiz_categories(channel):
        counts = {label: ready(conn, channel.key, name, label) for label in labels}
        sets = min(counts.values(), default=0)
        out[name] = {"sets": sets, "short": [label for label, n in counts.items() if n == 0],
                     "state": "ready" if sets >= SETS_AHEAD else "low" if sets else "dry"}
    return out


def claim(conn, channel_key: str, category: str, label: str, subtopic_id: str):
    """The ready round for a plan entry: the one it already has, or the
    oldest unclaimed one, now its own. None if there isn't one."""
    _table(conn)
    row = conn.execute("SELECT * FROM ready_rounds WHERE channel = ? AND subtopic = ? AND used_at IS NULL",
                       (channel_key, subtopic_id)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM ready_rounds WHERE channel = ? AND category = ? AND label = ? "
                           "AND used_at IS NULL AND subtopic IS NULL ORDER BY id LIMIT 1",
                           (channel_key, category, label)).fetchone()
        if row is None:
            return None
        with conn:
            conn.execute("UPDATE ready_rounds SET subtopic = ? WHERE id = ?", (subtopic_id, row["id"]))
    return dict(row)


def questions_of(conn, round_row: dict) -> list:
    """The round's questions as the round writer takes them, in order;
    any gone from the bank since (rejected on review) left out."""
    ids = json.loads(round_row["questions"])
    marks = ",".join("?" * len(ids))
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT * FROM questions WHERE status = 'ok' AND id IN ({marks})", ids)}
    return [{"question": rows[i]["question"], "answer": rows[i]["answer"], "note": rows[i]["note"],
             "bank_id": i, "source": rows[i]["source"]} for i in ids if i in rows]


def used(conn, round_id: int) -> None:
    with conn:
        conn.execute("UPDATE ready_rounds SET used_at = ? WHERE id = ?", (store.now(), round_id))


def available(conn, channel_key: str, category: str, label: str, subtopic_id: str) -> bool:
    """Whether a plan entry has a round to be made from: its own, or a
    ready one it can take. Asking doesn't take it."""
    _table(conn)
    return bool(conn.execute("SELECT 1 FROM ready_rounds WHERE channel = ? AND subtopic = ? AND used_at IS NULL",
                             (channel_key, subtopic_id)).fetchone()) or ready(conn, channel_key, category, label) > 0


def release(conn, channel_key: str, subtopic_id: str) -> None:
    """A plan entry removed before its video: its round is free again."""
    _table(conn)
    with conn:
        conn.execute("UPDATE ready_rounds SET subtopic = NULL WHERE channel = ? AND subtopic = ? "
                     "AND used_at IS NULL", (channel_key, subtopic_id))
