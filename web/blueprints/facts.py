"""
The fact store's page: how many facts each quiz category has and how many
each channel hasn't used, adding a category, going deeper, and what the
background runs are doing (pipeline.facts, decision 049).
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from core.channels import load_channels
from core.logging_setup import get_logger

log = get_logger(__name__)

bp = Blueprint("facts", __name__)


def _quiz_channels() -> list:
    return [c for c in load_channels(validate=False).values() if c.format == "quiz" and not c.archived]


@bp.route("/facts")
def page():
    from pipeline.facts import keep, pick, store
    conn = store.connect()
    channels = _quiz_channels()
    rows = []
    for record in store.categories(conn):
        general = bool(record["spec"].get("general"))
        pool = pick.pool(conn, record["name"], general)
        row = {"name": record["name"], "general": general, "askable": len(pool),
               "sets": [s.get("name", "") for s in record["spec"].get("sets", [])],
               "harvested_at": (record["harvested_at"] or "")[:10], "depth": record["depth"],
               "channels": []}
        for channel in channels:
            used = store.used_ids(conn, channel.key)
            if record["name"] in keep.quiz_categories(channel) or general:
                row["channels"].append({"name": channel.channel_display_name,
                                        "unused": sum(1 for f in pool if f["id"] not in used),
                                        "short": keep.short_levels(conn, channel, record["name"])})
        rows.append(row)
    runs = store.recent_runs(conn, 8)
    return render_template("facts.html", totals=store.totals(conn), rows=rows, runs=runs,
                           bank=_bank_rows(conn, channels), busy=keep.busy(),
                           note=request.args.get("note", ""))


def _bank_rows(conn, channels) -> dict:
    """The question bank per category: checked questions, and for each quiz
    channel how many it hasn't used and the levels where it's short."""
    from pipeline import quiz
    from pipeline.facts import bank, keep
    rows = {}
    for channel in channels:
        levels = quiz.levels(channel.quiz.difficulties)
        for name in keep.quiz_categories(channel):
            row = rows.setdefault(name, {"name": name, "checked": conn.execute(
                "SELECT COUNT(DISTINCT q.id) FROM questions q JOIN question_tags t ON t.question_id = q.id "
                "WHERE t.category = ? AND q.status = 'ok'", (name,)).fetchone()[0], "channels": []})
            have = bank.counts(conn, channel.key, name, levels)
            row["channels"].append({"name": channel.channel_display_name,
                                    "unused": len(bank.pool(conn, channel.key, name)),
                                    "short": [label for label, n in have.items() if n < keep.BANK_LOW]})
    total = conn.execute("SELECT COUNT(*) FROM questions WHERE status = 'ok'").fetchone()[0]
    return {"rows": sorted(rows.values(), key=lambda r: r["name"]), "total": total,
            "spent": bank.spent_today(), "limit": keep.BANK_DAILY_USD}


@bp.route("/facts/bank", methods=["POST"])
def write_bank():
    from pipeline.facts import keep
    channels = _quiz_channels()

    def work(conn, say):
        return " ".join(keep.stock_bank(conn, channel, say) for channel in channels)
    return _start("write questions", work)


def _start(action: str, work):
    from pipeline.facts import keep
    started = keep.start(action, work)
    note = "Started." if started else "Something is already running; try again when it's done."
    return redirect(url_for("facts.page", note=note))


@bp.route("/facts/categories", methods=["POST"])
def add_category():
    from pipeline.facts import categories, harvest
    name = " ".join((request.form.get("name") or "").split())[:60]
    if not name:
        return redirect(url_for("facts.page", note="Give the category a name."))

    def work(conn, say):
        say(f"{name}: mapping it onto Wikidata")
        categories.define(conn, name)
        result = harvest.harvest(conn, name, progress=say)
        return f"{name}: {result['members']} tagged, {result['new_facts']} new facts."
    return _start(f"add {name}", work)


@bp.route("/facts/categories/<name>/grow", methods=["POST"])
def grow(name):
    from pipeline.facts import harvest

    def work(conn, say):
        result = harvest.harvest(conn, name, grow=True, progress=say)
        return f"{name}: {result['members']} more tagged, {result['new_facts']} new facts."
    return _start(f"grow {name}", work)


@bp.route("/facts/stock", methods=["POST"])
def stock():
    from pipeline.facts import keep
    channels = _quiz_channels()

    def work(conn, say):
        return " ".join(keep.stock(conn, channel, say) for channel in channels)
    return _start("stock quiz channels", work)
