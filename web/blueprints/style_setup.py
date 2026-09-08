"""
The style & tone picker: turning a set of choices into a chosen, saved
style prompt, without anyone having to write one by hand.

This is deliberately not part of the settings page. Settings edits the
final plain-text prompt; this generates candidates for that field and
hands off. Keeping them separate means there is exactly one place that
owns `style_prompt` day to day (Settings), and one place whose whole job
is producing a first draft of it.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from core import style_choices
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import PathTraversalError, safe_join
from web.helpers import as_int, channel_or_404

log = get_logger(__name__)

bp = Blueprint("style_setup", __name__)

MIN_CANDIDATES, MAX_CANDIDATES = 3, 8
DEFAULT_CANDIDATES = 5


@bp.route("/channels/<key>/style-setup")
def page(key):
    channel = channel_or_404(key)
    seed_error = _seed_error(channel)
    return render_template(
        "style_setup.html", key=key, channel=channel,
        axes=style_choices.AXES, seed_error=seed_error,
        default_count=DEFAULT_CANDIDATES,
        min_count=MIN_CANDIDATES, max_count=MAX_CANDIDATES,
        is_rewrite=bool((channel.style_prompt or "").strip()),
    )


def _seed_error(channel):
    """Whether this channel can produce a real seed to sample with yet.

    The picker needs something to write about, and that comes from
    whatever the content section already collected — a topic, a quote, or
    a library source. Rather than duplicate that check, just try it: the
    same `fetch_seed` a real generation would call either returns
    something or raises the exact `user_message` that explains what is
    missing.
    """
    from pipeline.run import fetch_seed

    try:
        fetch_seed(channel)
        return None
    except PipelineError as exc:
        return exc.user_message


@bp.route("/api/channels/<key>/style-setup/candidates", methods=["POST"])
def candidates(key):
    """Draft N distinct style prompts and a short real sample of each.

    Synchronous: this is a setup-time comparison, not a render, and the
    person on the other end is looking at a spinner waiting for exactly
    this to finish, the same way `preview_script` already works.
    """
    import time

    from core import costs, job_context
    from pipeline import style_gen
    from pipeline.run import fetch_seed

    channel = channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    choices = style_choices.resolve(data.get("choices") or {})
    count = as_int(data.get("count"), DEFAULT_CANDIDATES, MIN_CANDIDATES, MAX_CANDIDATES)

    try:
        seed = fetch_seed(channel)
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 400

    started = time.time()
    try:
        drafted = style_gen.draft_candidates(channel, choices, count)
    except PipelineError as exc:
        log.warning(f"{key}: style candidate drafting failed: {exc}")
        return jsonify({"error": exc.user_message}), 502

    def _sample(candidate):
        try:
            script = style_gen.sample_for_candidate(
                channel, seed, candidate["style_prompt"])
            return {
                "blurb": candidate["blurb"],
                "style_prompt": candidate["style_prompt"],
                "sample": [s.text for s in script.segments],
                "error": None,
            }
        except PipelineError as exc:
            # One candidate failing to sample is not a reason to lose the
            # other N-1 — it is shown as unavailable, not dropped, so the
            # count on screen still matches what was asked for.
            log.warning(f"{key}: sample generation failed for one style "
                       f"candidate: {exc}")
            return {"blurb": candidate["blurb"],
                    "style_prompt": candidate["style_prompt"],
                    "sample": None, "error": exc.user_message}

    results = job_context.parallel_map(_sample, drafted, max_workers=5)
    spend = costs.summary_between(started, time.time(), key)

    return jsonify({
        "seed": seed.describe(),
        "cost": costs.format_usd(spend["total_usd"]),
        "candidates": results,
    })


@bp.route("/api/channels/<key>/style-setup/listen", methods=["POST"])
def listen(key):
    """A short cached audio clip of one candidate's sample, read by the
    channel's own chosen voice."""
    from pipeline import style_gen

    channel = channel_or_404(key)
    if not channel.voice:
        return jsonify({"error": "Pick a voice for this channel first, "
                                 "in Settings."}), 400

    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Nothing to read."}), 400

    try:
        sample = style_gen.listen_snippet(channel.voice, text, channel.speed or 1.0)
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 502
    return jsonify({"url": url_for("style_setup.serve_sample", filename=sample.name)})


@bp.route("/style-setup/samples/<path:filename>")
def serve_sample(filename):
    from flask import send_from_directory

    from core.paths import CACHE_DIR

    try:
        safe_join(CACHE_DIR / "style_setup_samples", filename)
    except PathTraversalError:
        from flask import abort
        abort(403, description="That sample isn't available.")
    return send_from_directory(CACHE_DIR / "style_setup_samples", filename)


@bp.route("/channels/<key>/style-setup/choose", methods=["POST"])
def choose(key):
    """Save the picked candidate's full prompt as this channel's style
    prompt, and nothing else — the picker's whole job ends here."""
    from core.channels import save_channel

    channel = channel_or_404(key)
    style_prompt = (request.form.get("style_prompt") or "").strip()
    if not style_prompt:
        return redirect(url_for("style_setup.page", key=key))

    channel.style_prompt = style_prompt
    save_channel(channel)
    log.info(f"{key}: style prompt set from the style picker")
    return redirect(url_for("channels.settings", key=key, saved=1,
                            note="Style prompt saved. Want a matching look "
                                 "too? See the Look section below."))
