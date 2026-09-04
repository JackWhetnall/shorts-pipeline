"""
The review queue and the insights page — the daily loop and the
improvement loop.

Both are deliberately cross-channel. Everything else in the app is scoped
to one channel, which mirrors how the config is organised but not how the
work is: the unit of work is a video, and you review whatever was made
today regardless of which channel made it. Reviewing five videos across
two channels used to cost about twenty clicks and a lot of
back-navigation.

Actions here take a bare `relpath` rather than a channel key plus a
relpath. The channel is derivable from the path, and requiring it would
force the queue to thread a key through every button for no benefit.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from core import gallery, insights, youtube
from core.channels import load_channels
from core.logging_setup import get_logger
from web.helpers import format_date, format_iso_date, video_or_404

log = get_logger(__name__)

bp = Blueprint("review", __name__)

# The queue ships its items to the browser as JSON so moving between them
# needs no navigation. That is the right trade at ten videos and the
# wrong one at five hundred, so the page carries a working session's
# worth and says how many are behind it.
QUEUE_PAGE_SIZE = 40


def _queue() -> list:
    """Every video awaiting a decision, oldest first.

    Oldest first on purpose: a review queue should drain, and putting the
    newest at the front means the oldest never gets looked at.
    """
    items = []
    for key, channel in load_channels(validate=False).items():
        # Once per channel, not once per video: this reads a file.
        youtube_ready = youtube.connection(key)["connected"]
        try:
            videos = gallery.list_videos(channel.output_dir)
        except Exception as exc:  # noqa: BLE001
            # One unreadable channel directory shouldn't empty the queue
            # for every other channel.
            log.warning(f"Couldn't list videos for {key}: {exc}")
            continue
        for video in videos:
            if video["discarded"] or video["published"]:
                continue
            report = video.get("report") or {}
            similarity = report.get("similarity") or {}
            items.append({
                **video,
                "channel_key": key,
                "channel_name": channel.channel_display_name,
                "youtube_connected": youtube_ready,
                "created_label": format_date(video["mtime"]),
                "footage_repeated": bool(report.get("footage_repeated")),
                "footage_degraded": bool(report.get("footage_degraded")),
                "shot_count": report.get("shot_count"),
                "similarity_flagged": bool(similarity.get("flagged")),
                "similarity_closest": similarity.get("closest_title"),
                "title_options": report.get("title_options") or [],
            })
    items.sort(key=lambda v: v["mtime"])
    return items


@bp.route("/review")
def queue():
    items = _queue()
    return render_template(
        "review.html",
        items=items[:QUEUE_PAGE_SIZE],
        total_waiting=len(items),
        discard_reasons=gallery.DISCARD_REASONS,
    )


@bp.route("/insights")
def insights_page():
    data = insights.collect()
    return render_template(
        "insights.html",
        data=data,
        headline=insights.headline(data),
        reason_labels=gallery.DISCARD_REASON_LABELS,
    )


# --- actions, addressed by path alone --------------------------------

@bp.route("/api/videos/<path:relpath>/meta", methods=["POST"])
def save_meta(relpath):
    """Title and description. Separate from publishing because you edit
    these while deciding, and publishing is the last step."""
    target = video_or_404(relpath)
    data = request.get_json(force=True, silent=True) or {}
    info = gallery.save_title_and_description(
        target, data.get("title", ""), data.get("description", ""))
    return jsonify({"ok": True, "title": info["title"]})


@bp.route("/api/videos/<path:relpath>/publish", methods=["POST"])
def publish(relpath):
    target = video_or_404(relpath)
    data = request.get_json(force=True, silent=True) or {}
    links = {f: data.get(f, "") for f in gallery.PUBLISH_LINK_FIELDS}
    if not any(v.strip() for v in links.values()):
        return jsonify({"error": "Add at least one platform link to mark this published."}), 400
    info = gallery.save_publish_info(target, links)
    return jsonify({"ok": True, "published_at": info["published_at"]})


@bp.route("/api/videos/<path:relpath>/discard", methods=["POST"])
def discard(relpath):
    target = video_or_404(relpath)
    data = request.get_json(force=True, silent=True) or {}
    gallery.set_discarded(target, True, reason=data.get("reason"))
    return jsonify({"ok": True})


@bp.route("/api/videos/<path:relpath>/restore", methods=["POST"])
def restore(relpath):
    gallery.set_discarded(video_or_404(relpath), False)
    return jsonify({"ok": True})


@bp.route("/videos/<path:relpath>/download")
def download(relpath):
    """Hand over the actual file.

    The video page streamed it in a player but offered no way to get it,
    so uploading meant leaving the app and hunting through
    output/<channel>/<date>/ for the right mp4 among its sidecars.
    """
    from flask import send_file
    target = video_or_404(relpath)
    return send_file(target, as_attachment=True, download_name=target.name)
