"""
The APIs page: what is set up, what it has cost, and where to top it up.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from core import costs, services, voice_quota
from core.channels import load_channels

bp = Blueprint("services", __name__)


@bp.route("/apis")
def page():
    data = services.collect()
    quota = voice_quota.summary(list(load_channels(validate=False)))
    return render_template("services.html", format_usd=costs.format_usd,
                           voice_quota=quota, **data)
