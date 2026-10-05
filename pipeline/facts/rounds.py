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

When a level's own band hasn't enough questions, the round is made by
rank instead (decision 065): the category's questions in order of how
hard they were rated, cut into as many equal bands as the channel has
levels, Easy taking the easiest band. The rater calls few questions easy
(Ancient History was written for sixteen times near Easy and still had no
round), and without this a category's Easy round, and so its next set
and its easiest-to-hardest long quiz, never came. Such a round is marked
`relative`. A category too thin for even that, with writing no longer
adding to it, is "dead": flagged, and not written for again.
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
    # Added with ranked rounds (decision 065).
    if "relative" not in {r[1] for r in conn.execute("PRAGMA table_info(ready_rounds)")}:
        with conn:
            conn.execute("ALTER TABLE ready_rounds ADD COLUMN relative INTEGER NOT NULL DEFAULT 0")


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
        ranked = bank.levels_of(conn, name)
        ranked = ranked if rankable(ranked, levels) else []
        out[name] = {}
        for index, (label, level) in enumerate(levels):
            have = ready(conn, channel.key, name, label)
            while have < SETS_AHEAD:
                chosen, relative = _choose(pool, level, count, asked, rng), False
                if not chosen:
                    chosen, relative = _choose_ranked(pool, ranked, index, len(levels), count, asked, rng), True
                if not chosen:
                    break
                ids = [r["id"] for r in chosen]
                with conn:
                    conn.execute("INSERT INTO ready_rounds (channel, category, label, level, questions, made_at, "
                                 "relative) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 (channel.key, name, label, level, json.dumps(ids), store.now(), int(relative)))
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
    for easier, harder in WINDOWS:
        near = [r for r in pool if level - easier <= r["level"] <= level + harder]
        chosen = _from(near, count, asked, rng)
        if chosen:
            return chosen
    return []


def rankable(ranked: list, levels: list) -> bool:
    """Whether ranking a category's questions can stand in for their
    levels: the channel has more than one level, and the category's
    questions spread over at least half the channel's range (the middle
    80% of them, so one outlier doesn't count). Questions all rated alike
    have no easiest band."""
    if len(levels) < 2 or len(ranked) < 2:
        return False
    targets = [level for _, level in levels]
    low, high = ranked[int(0.1 * (len(ranked) - 1))], ranked[int(0.9 * (len(ranked) - 1))]
    return high - low >= 0.5 * (max(targets) - min(targets))


def _choose_ranked(pool: list, ranked: list, index: int, levels: int, count: int, asked: list, rng) -> list:
    """One round from the `index`-th of `levels` equal bands of the
    category's questions ranked by level (`ranked`, every checked question
    it has, so the bands don't drift as questions are used), widened to the
    neighbouring bands if that one is used up. Never for a category with
    fewer than a full set's questions: its bands would mean nothing."""
    if not ranked or len(ranked) < count * levels:
        return []
    size = len(ranked) / levels
    for reach in (0, 1):
        lo = ranked[int(max(0, index - reach) * size)]
        hi = ranked[min(len(ranked) - 1, int(min(levels, index + 1 + reach) * size) - 1)]
        chosen = _from([r for r in pool if lo <= r["level"] <= hi], count, asked, rng)
        if chosen:
            return chosen
    return []


def _from(near: list, count: int, asked: list, rng) -> list:
    """`count` of `near`, spread over shapes and themes and cleared of
    repeats and clashes, easiest first; [] if it can't be done."""
    from pipeline import quiz
    if len(near) < count:
        return []
    for _ in range(3):
        picked = bank._spread(near, count + 4, rng)
        rows = [{"question": r["question"], "answer": r["answer"], "row": r} for r in picked]
        bad = set(quiz.repeats(rows, "", among=asked)) | set(quiz.round_clashes(rows))
        good = [x["row"] for i, x in enumerate(rows) if i not in bad]
        if len(good) >= count:
            good = good[:count]       # the first picked are those that kept the tightest spread
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
    """{category: {"sets", "short": [labels with none ready], "ranked":
    [labels whose ready rounds are made by rank], "left": questions not
    yet in a round, "state"}}: "ready" with SETS_AHEAD sets, "low" with
    fewer, "dry" with none, "dead" when dry with too few questions left
    for a set and writing has stopped adding to it (`dead`)."""
    from pipeline import quiz
    from pipeline.facts import keep
    labels = [label for label, _ in quiz.levels(channel.quiz.difficulties)]
    taken = _reserved(conn, channel.key)
    out = {}
    for name in keep.quiz_categories(channel):
        counts = {label: ready(conn, channel.key, name, label) for label in labels}
        sets = min(counts.values(), default=0)
        left = sum(1 for r in bank.pool(conn, channel.key, name) if r["id"] not in taken)
        ranked = [r[0] for r in conn.execute(
            "SELECT DISTINCT label FROM ready_rounds WHERE channel = ? AND category = ? AND relative = 1 "
            "AND used_at IS NULL", (channel.key, name))]
        state = "ready" if sets >= SETS_AHEAD else "low" if sets else "dry"
        if state == "dry" and dead(conn, name, left, channel.quiz.questions * len(labels)):
            state = "dead"
        out[name] = {"sets": sets, "short": [label for label, n in counts.items() if n == 0],
                     "ranked": [label for label in labels if label in ranked], "left": left, "state": state}
    return out


DEAD_WRITES = 3          # the category's last writes ...
DEAD_YIELD = 5           # ... adding fewer usable questions than this between them


def dead(conn, category: str, left: int, a_set: int) -> bool:
    """A category that can't make a set and that writing has stopped
    feeding: fewer questions left than a full set takes, and its last
    DEAD_WRITES batches between them added fewer than DEAD_YIELD a round
    could use. A new category isn't dead: it hasn't been written for yet."""
    if left >= a_set:
        return False
    from pipeline.facts import keep
    conn.executescript(keep.WRITES_TABLE)
    last = conn.execute("SELECT near FROM bank_writes WHERE category = ? ORDER BY at DESC LIMIT ?",
                        (category, DEAD_WRITES)).fetchall()
    return len(last) >= DEAD_WRITES and sum(r["near"] for r in last) < DEAD_YIELD


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
