"""
Keeping every quiz category stocked, in the background.

The store is eaten through as rounds are written, so it's kept ahead of
them, never filled while a round waits:

- a category a quiz channel has that the store doesn't know is defined
  (pipeline.facts.categories) and harvested;
- a category running short of unused facts near any of the channel's
  levels is harvested a page deeper;
- facts not pulled for half a year are pulled again.

One run at a time, on a thread of its own, recorded in the store's `runs`
for the Facts page. The scheduler calls `keep_up` every tick; it acts at
most once an hour.
"""

from __future__ import annotations

import threading
import time

from core.errors import ExternalServiceError
from core.logging_setup import get_logger
from pipeline.facts import categories, harvest, pick, store

log = get_logger(__name__)

LOW = 40                    # unused facts near a level: four rounds' worth
EVERY = 3600                # seconds between automatic runs

_thread = None
_last_auto = 0.0


def busy() -> bool:
    return _thread is not None and _thread.is_alive()


def start(action: str, work) -> bool:
    """Run `work(conn, say)` on a thread of its own. False if a run is
    already going."""
    global _thread
    if busy():
        return False
    conn = store.connect()
    # A run left "running" by a process that stopped isn't running.
    with conn:
        conn.execute("UPDATE runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
                     (store.now(),))
    run_id = store.start_run(conn, action)

    def body():
        say = lambda message: (log.info(f"  [facts] {message}"), store.update_run(conn, run_id, message))
        try:
            result = work(conn, say)
            store.update_run(conn, run_id, result or "Done.", status="done")
        except Exception as exc:  # noqa: BLE001 - a background run reports, never raises
            log.exception(f"Fact run {action!r} failed")
            store.update_run(conn, run_id, getattr(exc, "user_message", "") or "Failed; see the log.",
                             status="failed")

    _thread = threading.Thread(target=body, name=f"facts-{action}", daemon=True)
    _thread.start()
    return True


def quiz_categories(channel) -> list:
    """The channel's named, non-picture categories, from its topic plan."""
    from core import curriculum
    from pipeline import quiz
    if channel.format != "quiz" or not curriculum.exists(channel.key):
        return []
    return [quiz.base_category(t["title"]) for t in curriculum.load(channel.key)["topics"]
            if quiz._named(t) and not t.get("picture")]


def short_levels(conn, channel, name: str) -> list:
    """The channel's levels at which this category has fewer than LOW
    unused facts nearby."""
    from pipeline import quiz
    record = store.category(conn, name)
    if record is None:
        return []
    facts = pick.pool(conn, record["name"], bool(record["spec"].get("general")))
    used = store.used_ids(conn, channel.key)
    free = [f for f in facts if f["id"] not in used]
    return [label for label, level in quiz.levels(channel.quiz.difficulties)
            if sum(1 for f in free if abs(f["level"] - level) <= 1.0) < LOW]


def stock(conn, channel, say=None, names: list = None) -> str:
    """Define, harvest and deepen this channel's categories as needed."""
    say = say or (lambda message: log.info(f"  [facts] {message}"))
    done, failed = [], []
    for name in names or quiz_categories(channel):
        # One category Wikidata won't answer for today doesn't stop the rest.
        try:
            if _stock_one(conn, channel, name, say):
                done.append(name)
        except ExternalServiceError as exc:
            say(f"{name}: {exc.user_message} Moving on.")
            failed.append(name)
    parts = [f"Stocked {', '.join(dict.fromkeys(done))}." if done else "Every category is stocked."]
    if failed:
        parts.append(f"Couldn't reach Wikidata for {', '.join(failed)}; the next run tries again.")
    return " ".join(parts)


def _stock_one(conn, channel, name: str, say) -> bool:
    """Define, harvest or deepen one category as it needs. True if anything
    was fetched."""
    fetched = False
    record = store.category(conn, name)
    if record is None:
        say(f"{name}: mapping it onto Wikidata")
        try:
            categories.define(conn, name)
        except categories.CategoryError as exc:
            say(exc.user_message)
            return False
        record = store.category(conn, name)
    if record["spec"].get("general"):
        return False
    # Never harvested, or a set added or fixed since that hasn't been.
    unfetched = any(not s.get("fetched") and s.get("method") != "skipped"
                    for s in record["spec"].get("sets", []))
    if not record["harvested_at"] or unfetched:
        harvest.harvest(conn, name, progress=say)
        fetched = True
    short = short_levels(conn, channel, name)
    if short:
        say(f"{name}: running short at {', '.join(short)}; going deeper")
        harvest.harvest(conn, name, grow=True, progress=say)
        fetched = True
    return fetched


BANK_LOW = 20                  # unused checked questions near a level before writing more
BANK_BATCHES = 6               # batches per run, at most (a run is hourly)
# What all of this may cost is a total, not a daily cap (pipeline.facts.budget,
# decision 064).


# A slot whose writing isn't filling it is rested, so the day's budget
# goes where it does some good. The writer kept being sent back to the
# emptiest slot: Ancient History near Easy, 16 batches in a few days, each
# yielding a question or two easy enough and the rest rated harder.
REST_AFTER = 3                 # writes in a row ...
REST_YIELD = 2                 # ... each giving fewer than this many usable for the slot
REST_DAYS = 3                  # rest it this long

WRITES_TABLE = """
CREATE TABLE IF NOT EXISTS bank_writes (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL COLLATE NOCASE,
    level REAL NOT NULL,
    at REAL NOT NULL,
    near INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS bank_writes_slot ON bank_writes (category, level);
"""


def _record_write(conn, category: str, level: float, levels: list) -> int:
    """Note how many of a write's kept questions a round at this level
    could use (the widest band a round takes). Returns that number."""
    from pipeline.facts import rounds
    easier, harder = rounds.WINDOWS[-1]
    near = sum(1 for kept in levels if level - easier <= kept <= level + harder)
    conn.executescript(WRITES_TABLE)
    with conn:
        conn.execute("INSERT INTO bank_writes (category, level, at, near) VALUES (?, ?, ?, ?)",
                     (category, level, time.time(), near))
    return near


def resting_until(conn, category: str, level: float):
    """When a slot that has stopped filling may be written for again, or
    None if it isn't resting: the last REST_AFTER writes for it each gave
    fewer than REST_YIELD questions it could use, the latest within
    REST_DAYS."""
    conn.executescript(WRITES_TABLE)
    last = conn.execute("SELECT at, near FROM bank_writes WHERE category = ? AND level = ? "
                        "ORDER BY at DESC LIMIT ?", (category, level, REST_AFTER)).fetchall()
    if len(last) < REST_AFTER or any(r["near"] >= REST_YIELD for r in last):
        return None
    until = last[0]["at"] + REST_DAYS * 86400
    return until if until > time.time() else None


def stock_bank(conn, channel, say=None) -> str:
    """Write question-bank batches where this channel's categories are
    shortest (pipeline.facts.bank), within the run's and the day's limits."""
    from pipeline import quiz
    from pipeline.facts import bank, budget
    say = say or (lambda message: log.info(f"  [bank] {message}"))
    names = quiz_categories(channel)
    levels = quiz.levels(channel.quiz.difficulties)
    # Counted only once the bank is filed to each category's scope
    # (pipeline.facts.scope), so a renamed category isn't thought full.
    # Filing is part of stocking, so it waits too once the budget is used.
    from pipeline.facts import rounds, scope
    if budget.remaining() > 0:
        try:
            scope.sort_if_needed(conn, names, say)
        except Exception as exc:  # noqa: BLE001 - stocking goes on; the next run or round sorts again
            log.warning(f"  [bank] couldn't sort the bank into its categories ({exc})")
    # Written where the rounds made ahead fall short (pipeline.facts.rounds),
    # the slots with fewest ready rounds first.
    rounds.assemble(conn, channel)
    short = []
    for name in names:
        for label, level in levels:
            have = rounds.ready(conn, channel.key, name, label)
            if have < rounds.SETS_AHEAD:
                short.append((have, name, label, level))
    written = 0
    used_up = False
    for have, name, label, level in sorted(short):
        if written >= BANK_BATCHES:
            break
        until = resting_until(conn, name, level)
        if until:
            say(f"{name} near {label}: the last {REST_AFTER} batches each gave fewer than "
                f"{REST_YIELD} questions easy or hard enough for it; resting it until "
                f"{time.strftime('%a %d %b', time.localtime(until))}")
            continue
        # Before sending, not after: a batch is logged only once it's back.
        if not budget.room_for(budget.WRITE_BATCH_USD):
            say(budget.used_up_message())
            used_up = True
            break
        say(f"Writing {name} questions near {label} ({have} rounds ready)")
        try:
            result = bank.write_batch(conn, name, level, names) or {}
        except Exception as exc:  # noqa: BLE001 - one batch failing mustn't stop the rest
            log.warning(f"  [bank] {name} near {label}: {exc}")
            continue
        near = _record_write(conn, name, level, result.get("levels") or [])
        say(f"{name} near {label}: {result.get('kept', 0)} kept, {near} of them right for it")
        written += 1
    rounds.assemble(conn, channel)
    if not short:
        return "Every category has its rounds ready."
    wrote = f"Wrote {written} question batch{'es' if written != 1 else ''}."
    return f"{wrote} {budget.used_up_message()}" if used_up else wrote


def keep_up(channels: dict) -> bool:
    """The scheduler's duty: at most hourly, stock every quiz channel's
    categories and refresh stale facts, in the background."""
    global _last_auto
    quizzes = [c for c in channels.values() if c.format == "quiz" and not c.archived]
    if not quizzes or busy() or time.time() - _last_auto < EVERY:
        return False
    _last_auto = time.time()

    def work(conn, say):
        # Nothing waits on this run, so every call in it goes through the
        # Message Batches API at half price (pipeline.llm.batched).
        from pipeline import llm
        with llm.batched():
            return _keep_up_work(conn, say, quizzes)

    return start("keep up", work)


def _keep_up_work(conn, say, quizzes: list) -> str:
    # Imported questions (pipeline.facts.intake), then writing where rounds
    # are short, both out of the one total (pipeline.facts.budget). Both:
    # imports barely reach the easy levels (most sources' "easy" is rated
    # hard), which only writing fills.
    from pipeline.facts import budget, intake
    results = []
    if intake.pending(conn):
        names = []
        for channel in quizzes:
            names += [n for n in quiz_categories(channel) if n not in names]
        results.append(intake.process(conn, names, budget.remaining(), say)
                       if budget.room_for(budget.IMPORT_BATCH_USD) else budget.used_up_message())
    results += [stock_bank(conn, channel, say) for channel in quizzes]
    results += [stock(conn, channel, say) for channel in quizzes]
    harvest.refresh(conn, progress=say)
    return " ".join(results)
