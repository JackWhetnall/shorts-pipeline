"""
Redirects from the old setup wizard into the settings page.

The wizard was a second editor beside the settings form. Which of the two
owned a given field was genuinely unclear — some settings were editable in
both places, some in only one, and each Next committed silently with no
way to tell what had changed or to undo it.

There is one editor now: `/channels/<key>/settings`, one page, a sidebar
that jumps rather than hides, and one Save. This module is what is left —
the step URLs still resolve, so the checklist, the dashboard and any
bookmark land on the right section instead of a 404.

`words_from_of` stays here because the three-way "where do the words come
from" question is defined by this module's vocabulary, and both the
settings page and its form parser read it.
"""

from __future__ import annotations

from flask import Blueprint, abort, redirect, url_for

from pipeline import quote_source
from web.helpers import channel_or_404

bp = Blueprint("setup", __name__)

# Where each old wizard step now lives. The wizard was a second editor
# beside the settings page, and which of the two owned a given field was
# genuinely unclear — some things were editable in both, some in only one.
# There is one editor now; these keep old links and bookmarks working.
STEP_ANCHORS = {
    "content": "section-content",
    "voice": "section-voice",
    "look": "section-look",
    "socials": "section-publishing",
    "patreon": "section-money",
    "merch_store": "section-money",
    "amazon": "section-money",
}

# Steps that were never editors: they explained something and pointed at a
# page elsewhere. They keep going to that page.
STEP_PAGES = {
    "logo": "logos.logo_page",
    "merch_logo": "logos.logo_page",
    "email": None,
}


def words_from_of(channel) -> str:
    """Which of the three choices a stored channel corresponds to."""
    if channel.content_mode == "topic":
        return "original"
    if (channel.source or "") == quote_source.CUSTOM:
        return "own_quotes"
    return "built_in"


@bp.route("/channels/<key>/setup/<step>")
def setup_step(key, step):
    """Redirects into the settings page.

    Kept rather than deleted because the checklist, the dashboard and any
    bookmark still point here, and a 404 is a worse answer than the right
    section of the page that replaced it.
    """
    channel = channel_or_404(key)
    if step in STEP_PAGES:
        endpoint = STEP_PAGES[step]
        if endpoint:
            return redirect(url_for(endpoint, key=channel.key))
        return redirect(url_for("channels.dashboard", key=channel.key))
    anchor = STEP_ANCHORS.get(step)
    if anchor is None:
        abort(404, description="That isn't a setup step.")
    return redirect(url_for("channels.settings", key=channel.key) + f"#{anchor}")
