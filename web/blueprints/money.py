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
    from web import focus
    channels = load_channels(validate=False)
    f = money.forecast(channels)
    key = focus.current(channels)
    if key:
        f = money.for_channel(f, key)          # the channel chosen in the header (decision 107)
    return render_template("money.html", f=f, channels=channels,
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


@bp.route("/money/outlook")
def outlook():
    """Where one channel is heading: audience, the Partner Programme, cost
    and payback, in charts (core.outlook, decision 107)."""
    from core import outlook as ahead
    from web import focus
    channels = load_channels(validate=False)
    live = {k: c for k, c in channels.items() if not c.archived and c.publishing.enabled}
    choices = [(k, c.channel_display_name or k) for k, c in live.items()]
    key = request.args.get("channel") or focus.current(channels)
    if key not in live:
        key = next(iter(live), None)
    if key is None:
        return redirect(url_for("money.page", note="No channel publishes yet."))
    return render_template("outlook.html", o=ahead.picture(channels[key], money.forecast(channels)),
                           choices=choices)


@bp.route("/money/voice")
def voice():
    """Where the ElevenLabs allowance goes this month, film by film and
    short by short, and what to change if it won't last (core.voice_budget,
    decision 120)."""
    from core import voice_budget
    return render_template("voice_budget.html", v=voice_budget.picture(), note=request.args.get("note", ""))


@bp.route("/money/voice/apply", methods=["POST"])
def voice_apply():
    """One suggestion's settings change, saved."""
    import json
    from core import voice_budget
    from core.errors import PipelineError
    try:
        voice_budget.apply(request.form.get("channel", ""), json.loads(request.form.get("change") or "{}"))
    except (PipelineError, ValueError) as exc:
        message = exc.user_message if isinstance(exc, PipelineError) else "That change can't be made here."
        return redirect(url_for("money.voice", note=message))
    return redirect(url_for("money.voice", note="Changed."))
