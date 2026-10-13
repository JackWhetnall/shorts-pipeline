"""
Money: what the channels cost a month, how long the money and the voice
allowance last, and what it takes to get it back (core.money, decision 067).
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from core import money
from core.channels import load_channels

bp = Blueprint("money", __name__)


@bp.route("/money")
def page():
    from core import spare_voice
    channels = load_channels(validate=False)
    return render_template("money.html", f=money.forecast(channels), channels=channels,
                           spare=spare_voice.current_plan(channels),
                           providers=money.PROVIDERS, note=request.args.get("note", ""))


@bp.route("/money/balance", methods=["POST"])
def set_balance():
    provider = request.form.get("provider", "")
    if provider not in money.PROVIDERS:
        return redirect(url_for("money.page", note="Unknown account."))
    label = money.PROVIDERS[provider]["label"]
    if request.form.get("add"):
        try:
            added = float(request.form["add"])
        except ValueError:
            return redirect(url_for("money.page", note="The top-up has to be a number of dollars."))
        usd = money.top_up(provider, added)
        return redirect(url_for("money.page", note=f"{label}: +${added:.0f}, ${usd:.2f} now.") + "#balances")
    try:
        usd = float(request.form.get("usd") or "")
    except ValueError:
        return redirect(url_for("money.page", note="The balance has to be a number of dollars."))
    money.set_balance(provider, usd)
    return redirect(url_for("money.page", note=f"{label}: ${usd:.2f} from now on.") + "#balances")


@bp.route("/money/settings", methods=["POST"])
def save_settings():
    changes = {}
    for name in ("elevenlabs_monthly_usd", "long_rpm", "shorts_rpm"):
        try:
            changes[name] = max(0.0, float(request.form.get(name) or ""))
        except ValueError:
            pass
    channels = load_channels(validate=False)
    changes["in_ypp"] = [key for key in channels if request.form.get(f"ypp_{key}")]
    changes["spare_voice"] = bool(request.form.get("spare_voice"))
    money.save_settings(changes)
    return redirect(url_for("money.page", note="Saved.") + "#assumptions")
