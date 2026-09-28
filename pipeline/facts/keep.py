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
    if not record["harvested_at"]:
        harvest.harvest(conn, name, progress=say)
        fetched = True
    short = short_levels(conn, channel, name)
    if short:
        say(f"{name}: running short at {', '.join(short)}; going deeper")
        harvest.harvest(conn, name, grow=True, progress=say)
        fetched = True
    return fetched


def keep_up(channels: dict) -> bool:
    """The scheduler's duty: at most hourly, stock every quiz channel's
    categories and refresh stale facts, in the background."""
    global _last_auto
    quizzes = [c for c in channels.values() if c.format == "quiz" and not c.archived]
    if not quizzes or busy() or time.time() - _last_auto < EVERY:
        return False
    _last_auto = time.time()

    def work(conn, say):
        results = [stock(conn, channel, say) for channel in quizzes]
        harvest.refresh(conn, progress=say)
        return " ".join(results)

    return start("keep up", work)
