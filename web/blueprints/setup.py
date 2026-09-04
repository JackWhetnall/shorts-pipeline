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

from core import assets, corpus, curriculum, logos, voice_lab
from core.channels import save_channel
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.voice_lab import CADENCE_PRESETS
from pipeline import quote_source
from web.forms import format_affiliate_links, lines, parse_affiliate_links
from web.helpers import channel_or_404

log = get_logger(__name__)

bp = Blueprint("setup", __name__)

# Content first, then identity, then money. The wizard used to start at
# the logo, which meant the two things a channel cannot run without — what
# it says and whose voice says it — were only reachable through a settings
# form that asked for them alongside an output directory and a raw voice
# ID. A channel got created that could not have made a video.
STEPS = ("content", "voice", "logo", "email", "socials", "patreon",
         "merch_logo", "merch_store", "amazon")

# Steps with nothing to save: guided checkpoints that point at a page or
# a button elsewhere.
INFORMATIONAL_STEPS = {"logo", "email", "merch_logo"}

# What a channel cannot make a video without. The wizard can be left at
# any point, but these are the ones the dashboard keeps asking about.
ESSENTIAL_STEPS = ("content", "voice")


def _apply_step(channel, step: str, form, files) -> list:
    """Apply one step's fields. Returns any messages worth showing back."""
    warnings = []

    if step == "content":
        warnings += _apply_content(channel, form)

    elif step == "voice":
        voice = form.get("voice", "").strip()
        if voice:
            channel.voice = voice
        try:
            channel.speed = float(form.get("speed", channel.speed))
        except (TypeError, ValueError):
            pass
        # The cadence preset is resolved here, not in the browser, so the
        # preset table has exactly one definition.
        preset = CADENCE_PRESETS.get(form.get("preset"))
        if preset:
            for field, value in preset["pacing"].items():
                if field in channel.pacing.keys():
                    setattr(channel.pacing, field, float(value))

    elif step == "socials":
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


def _apply_content(channel, form) -> list:
    """What this channel makes, and where its words come from.

    The three choices are presented as one question because they are one
    decision, but they map onto two stored fields — `content_mode` and
    `source` — which is why this translation lives here rather than in a
    <select> whose values the config layer would have to understand.
    """
    warnings = []
    words_from = form.get("words_from", "").strip()

    if words_from == "original":
        channel.content_mode = "topic"
        channel.topics = lines(form.get("topics", ""))
    elif words_from == "own_quotes":
        channel.content_mode = "static_corpus"
        channel.source = quote_source.CUSTOM
        result = corpus.save(channel.key, form.get("quotes", ""))
        if result["skipped"]:
            warnings.append(f"{result['skipped']} line(s) were too short to use "
                            f"as a quote and were left out.")
        if not result["kept"]:
            warnings.append("No usable quotes yet — add at least one before "
                            "this channel can make a video.")
    elif words_from == "built_in":
        channel.content_mode = "static_corpus"
        source = form.get("source", "").strip()
        if source in quote_source.SOURCES:
            channel.source = source

    channel.channel_display_name = (form.get("channel_display_name", "").strip()
                                    or channel.channel_display_name)
    style_prompt = form.get("style_prompt", "").strip()
    if style_prompt:
        channel.style_prompt = style_prompt
    channel.avoid_imagery = lines(form.get("avoid_imagery", ""))
    return warnings


def words_from_of(channel) -> str:
    """Which of the three choices a stored channel corresponds to."""
    if channel.content_mode == "topic":
        return "original"
    if (channel.source or "") == quote_source.CUSTOM:
        return "own_quotes"
    return "built_in"


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
        **_step_extras(channel, step),
    )


def _step_extras(channel, step: str) -> dict:
    """Data only one step needs, fetched only when that step is shown.

    The voice list in particular is an HTTP call on a cold cache; every
    other step would pay for it for nothing.
    """
    if step == "content":
        return {
            "words_from": words_from_of(channel),
            "sources": sorted(quote_source.SOURCES),
            "source_labels": quote_source.SOURCE_LABELS,
            "quotes_text": corpus.raw_text(channel.key),
            "quote_count": corpus.count(channel.key),
            "topic_plan": curriculum.progress(channel.key),
        }
    if step == "voice":
        voices, voice_error = [], None
        try:
            voices = voice_lab.get_cached_voices()
        except PipelineError as exc:
            # A missing key or a key without voices_read shouldn't be a
            # dead end: you can still paste an ID you already have.
            voice_error = exc.user_message
        return {"voices": voices, "voice_error": voice_error,
                "presets": CADENCE_PRESETS}
    return {}


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
