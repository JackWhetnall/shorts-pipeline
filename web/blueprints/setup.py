"""
The guided channel setup wizard.

Order matters and lives in one place. Logo is first because every later
step benefits from having one — a profile picture for socials, a mark for
merch. Merch is two steps, not one: the print-ready logo variants have to
exist before the storefront step, whose instructions assume you already
have art to upload.

Each step saves only its own fields. That used to be a real trap: because
settings saves rewrote the complete entry, a field the wizard set but the
settings form didn't know about was silently erased by the next settings
save. Sparse saves (see core.channels) removed the trap structurally, so
this no longer needs to reach around the config layer to avoid it.
"""

from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from core import assets, logos
from core.channels import save_channel
from core.errors import PipelineError
from web.forms import format_affiliate_links, parse_affiliate_links
from web.helpers import channel_or_404

bp = Blueprint("setup", __name__)

STEPS = ("logo", "email", "socials", "patreon", "merch_logo", "merch_store", "amazon")

# Steps with nothing to save: guided checkpoints that point at a page or
# a button elsewhere.
INFORMATIONAL_STEPS = {"logo", "email", "merch_logo"}


def _apply_step(channel, step: str, form, files) -> list:
    """Apply one step's fields. Returns any messages worth showing back."""
    warnings = []

    if step == "socials":
        channel.socials.youtube_url = form.get("youtube_url", "").strip()
        channel.socials.tiktok_url = form.get("tiktok_url", "").strip()
        channel.socials.instagram_url = form.get("instagram_url", "").strip()

    elif step == "patreon":
        channel.monetization.patreon_url = form.get("patreon_url", "").strip()

    elif step == "merch_store":
        channel.monetization.merch_url = form.get("merch_url", "").strip()
        for storage in files.getlist("merch_photos"):
            if not storage or not storage.filename:
                continue
            try:
                assets.save_merch_photo(channel.key, storage.filename, storage.read())
            except PipelineError as exc:
                # Previously swallowed silently: an unsupported upload
                # just didn't appear, with no explanation, which reads as
                # the app being broken rather than the file being wrong.
                warnings.append(exc.user_message)

    elif step == "amazon":
        channel.monetization.affiliate_links = parse_affiliate_links(
            form.get("affiliate_links", ""))

    return warnings


@bp.route("/channels/<key>/setup/<step>", methods=["GET", "POST"])
def setup_step(key, step):
    if step not in STEPS:
        abort(404, description="That isn't a setup step.")
    channel = channel_or_404(key)
    index = STEPS.index(step)

    if request.method == "POST":
        warnings = _apply_step(channel, step, request.form, request.files)
        save_channel(channel)
        if warnings:
            # Stay on the step so the message is actually seen, rather
            # than advancing past a partial save.
            return _render(channel, step, index, warnings=warnings)
        if index < len(STEPS) - 1:
            return redirect(url_for("setup.setup_step", key=key, step=STEPS[index + 1]))
        return redirect(url_for("channels.dashboard", key=key))

    return _render(channel, step, index)


def _render(channel, step: str, index: int, warnings: list = None):
    return render_template(
        f"setup_{step}.html",
        key=channel.key, channel=channel, step=step, steps=STEPS,
        step_index=index, step_count=len(STEPS),
        prev_step=STEPS[index - 1] if index > 0 else None,
        next_step=STEPS[index + 1] if index < len(STEPS) - 1 else None,
        merch_photos=[p.name for p in assets.list_merch_photos(channel.key)],
        affiliate_links_text=format_affiliate_links(channel.monetization.affiliate_links),
        has_logo=assets.has_logo(channel.key),
        has_merch_variants=logos.has_merch_variants(channel.key),
        variant_styles=logos.VARIANT_STYLES,
        warnings=warnings or [],
    )


@bp.route("/channels/<key>/merch/delete", methods=["POST"])
def delete_merch(key):
    channel_or_404(key)
    assets.delete_merch_photo(key, request.form.get("filename", ""))
    return redirect(url_for("setup.setup_step", key=key, step="merch_store"))


@bp.route("/channels/<key>/merch-assets/<path:filename>")
def serve_merch_asset(key, filename):
    from flask import send_from_directory
    from core.paths import PathTraversalError, channel_merch_dir, safe_join

    directory = channel_merch_dir(key)
    try:
        target = safe_join(directory, filename)
    except PathTraversalError:
        abort(403, description="That file isn't available.")
    if not target.exists():
        abort(404, description="That photo doesn't exist.")
    return send_from_directory(directory, filename)
