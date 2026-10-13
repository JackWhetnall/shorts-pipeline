"""
A ceiling on what one film may cost (decision 094).

Every film's spend is added up from the cost log (each record knows its
film: core.job_context.set_production). A film that reaches its ceiling
is stopped before its next paid call, keeping everything it has made, so
the owner can look and carry it on rather than lose the money spent.

The ceiling is set where it should never be reached by an ordinary
film, only by one where something has gone wrong (a loop of redraws, a
stage retried over and over): twice what the channel's recent films
have cost, and never under FLOOR. The owner's words: "breaking a cost
limit should be a rare 'something has gone fundamentally wrong' rather
than 'this one's a bit more expensive than the others'." A film can be
allowed more (`allow_more`), once someone has looked.
"""

from __future__ import annotations

import json
import statistics

from core import production
from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

TIMES_USUAL = 2.0
FLOOR = 5.0                     # dollars: the ceiling is never lower
USUAL_UNTIL_KNOWN = 3.5         # a film's cost before a channel has made any (the salt film: $3.86)
RECENT = 5                      # the films the usual cost is measured on


class FilmOverBudget(PipelineError):
    pass


def _spend_by_film(channel_key: str) -> dict:
    """{plan-entry id: dollars} from the cost log, for this channel."""
    from core import costs
    totals: dict = {}
    try:
        with open(costs.COST_LOG_PATH, encoding="utf-8") as f:
            for line in f:
                if '"production"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("channel_key") == channel_key and row.get("production"):
                    totals[row["production"]] = totals.get(row["production"], 0.0) + (row.get("cost_usd") or 0.0)
    except OSError:
        pass
    return totals


def spent(channel_key: str, subtopic_id: str) -> float:
    return round(_spend_by_film(channel_key).get(subtopic_id, 0.0), 4)


def usual(channel_key: str) -> float:
    """What the channel's films usually cost: the median of its latest
    RECENT made films, or USUAL_UNTIL_KNOWN before it has made two."""
    totals = _spend_by_film(channel_key)
    made = [d for d in production.all_for(channel_key)
            if production.state(d, "video") in ("ready", "approved") and totals.get(d["subtopic_id"], 0) > 0]
    made.sort(key=lambda d: (d.get("stages", {}).get("video") or {}).get("at", ""))
    costs_ = [totals[d["subtopic_id"]] for d in made[-RECENT:]]
    return round(statistics.median(costs_), 2) if len(costs_) >= 2 else USUAL_UNTIL_KNOWN


def ceiling(channel_key: str, subtopic_id: str) -> float:
    data = production.load(channel_key, subtopic_id)
    return round(max(FLOOR, TIMES_USUAL * usual(channel_key)) + float(data.get("budget_extra") or 0), 2)


def check(channel_key: str, subtopic_id: str) -> None:
    """Raises FilmOverBudget once the film has spent its ceiling. Called
    before every paid call made for a film, and before each stage."""
    if not channel_key or not subtopic_id:
        return
    used, top = spent(channel_key, subtopic_id), ceiling(channel_key, subtopic_id)
    if used >= top:
        raise FilmOverBudget(
            f"{channel_key}/{subtopic_id} has spent ${used:.2f} of its ${top:.2f} ceiling",
            user_message=(f"Paused: this film has cost ${used:.2f}, over twice what a film usually costs "
                          f"(${usual(channel_key):.2f}), so something has probably gone wrong. Everything made "
                          f"so far is kept: look at it, then allow it more to carry on."))


def check_current() -> None:
    """check() for the film the current work is for, if it is for one."""
    from core import job_context
    check(job_context.get_channel_key(), job_context.get_production())


def allow_more(channel_key: str, subtopic_id: str) -> float:
    """Raise the film's ceiling by one more usual film. Returns the new ceiling."""
    extra = usual(channel_key)
    production.update(channel_key, subtopic_id,
                      lambda d: d.update(budget_extra=round(float(d.get("budget_extra") or 0) + extra, 2)))
    log.info(f"{channel_key}/{subtopic_id}: allowed ${extra:.2f} more")
    return ceiling(channel_key, subtopic_id)
