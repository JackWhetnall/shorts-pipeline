"""
The APIs page: what is set up, what it has cost, and where to top it up.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from core import costs, services, voice_quota
from core.channels import load_channels

bp = Blueprint("services", __name__)


@bp.route("/api/services/<key>/test", methods=["POST"])
def test(key):
    """Does this key really work: a tiny real request, answered in words."""
    return jsonify(services.test_key(key))


@bp.route("/apis")
def page():
    data = services.collect()
    quota = voice_quota.summary(list(load_channels(validate=False)))
    return render_template("services.html", format_usd=costs.format_usd,
                           voice_quota=quota, **data)
