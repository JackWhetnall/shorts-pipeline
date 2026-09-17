"""
The APIs page: what is set up, what it has cost, and where to top it up.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from core import costs, services

bp = Blueprint("services", __name__)


@bp.route("/apis")
def page():
    data = services.collect()
    return render_template("services.html", format_usd=costs.format_usd, **data)
