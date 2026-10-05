"""
What stocking the question bank may cost in all, not per day (decision 064).

Stocking is a job with an end: write, import, check, rate and file
questions until every quiz category has its rounds ready
(pipeline.facts.rounds). A daily cap hid that. It spent the cap every day
whatever was left to do, and $0.75 a day reads as small long after the
job itself has cost $20. So the limit is on the total, the total is shown
beside it, and the hourly run stops when it's reached.

Counted: every background call that stocks the bank (the hourly run and
the Facts page's buttons). Not counted: questions a video writes for
itself mid-job, which are that video's cost and on its cost sidecar.

Each batch is checked before it's sent, not after: a batch's cost is only
logged once its results are back, and checking the log after the fact let
the import run spend twice its daily limit (2 Oct). `room_for` asks whether
the next batch's expected cost still fits.
"""

from __future__ import annotations

import json

from core import paths
from core.logging_setup import get_logger

log = get_logger(__name__)

# Until set on the Facts page. When this was introduced the bank already
# had 5,550 questions and 192 of its 234 rounds ready, for $21.22, with
# $3.77 of Claude credit left for everything. Videos come first, so the
# default leaves only a few batches until the owner raises it.
DEFAULT_LIMIT_USD = 22.0
LIMIT_PATH = paths.QUESTION_BANK_BUDGET_PATH

# What one batch is expected to cost at full price, from the cost log on
# 5 Oct: a 25-question write with its checks and rating $0.081; an import
# batch of 25 $0.034. Full price, so a run by hand (not batched) fits too.
WRITE_BATCH_USD = 0.09
IMPORT_BATCH_USD = 0.04

PREFIXES = ("bank_", "intake_", "category_", "facts_")


def counts(record: dict) -> bool:
    """Whether a cost record is part of stocking the bank."""
    return (not record.get("job_id")
            and str(record.get("operation") or "").startswith(PREFIXES))


def spent(records: list = None) -> float:
    """Everything stocking the bank has cost, ever."""
    from core import costs
    records = costs.read_records() if records is None else records
    return sum(float(r.get("cost_usd") or 0) for r in records if counts(r))


def limit() -> float:
    try:
        return float(json.loads(LIMIT_PATH.read_text(encoding="utf-8"))["limit_usd"])
    except FileNotFoundError:
        return DEFAULT_LIMIT_USD
    except (ValueError, KeyError, TypeError):
        log.warning(f"{LIMIT_PATH.name} is unreadable; using the default question bank budget")
        return DEFAULT_LIMIT_USD


def set_limit(usd: float) -> float:
    usd = round(max(0.0, float(usd)), 2)
    LIMIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIMIT_PATH.write_text(json.dumps({"limit_usd": usd}, indent=1), encoding="utf-8")
    return usd


def remaining() -> float:
    return max(0.0, limit() - spent())


def room_for(batch_usd: float) -> bool:
    """Whether a batch expected to cost `batch_usd` still fits the total."""
    return remaining() >= batch_usd


def used_up_message() -> str:
    return (f"The question bank's budget is used: ${spent():.2f} of ${limit():.2f}. "
            "Raise it on the Facts page to write or import more.")


def summary(conn, channels: list) -> dict:
    """The job and its cost, for the Facts page: rounds ready and short
    across the quiz channels, how many days of publishing the ready rounds
    cover, and the spend against the limit."""
    from pipeline import quiz
    from pipeline.facts import keep, rounds
    ready = short = 0
    per_day = 0.0
    for channel in channels:
        for name in keep.quiz_categories(channel):
            for label, _level in quiz.levels(channel.quiz.difficulties):
                have = rounds.ready(conn, channel.key, name, label)
                ready += min(have, rounds.SETS_AHEAD)
                short += max(0, rounds.SETS_AHEAD - have)
        per_day += shorts_per_day(channel)
    return {"spent": spent(), "limit": limit(), "remaining": remaining(),
            "ready": ready, "short": short,
            "days": int(ready / per_day) if per_day else None}


def shorts_per_day(channel) -> float:
    """How many shorts a channel's publishing plan puts out a day."""
    plan = channel.publishing
    if not plan.enabled:
        return 0.0
    if not plan.slots:
        return 1.0
    days = len(plan.weekdays) if plan.weekdays else 7
    return len(plan.slots) * days / 7
