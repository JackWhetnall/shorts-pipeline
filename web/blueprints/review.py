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

from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from core import audience, costs, gallery, insights, posting, publish_queue, youtube
from core.errors import PipelineError
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
    from pipeline import quiz
    items = []
    for key, channel in load_channels(validate=False).items():
        # Once per channel, not once per video: this reads a file.
        youtube_ready = youtube.connection(key)["connected"]
        slots = {str(Path(p).resolve()): when for p, when in publish_queue.schedule_for(channel)}
        try:
            videos = gallery.list_videos(channel.output_dir)
        except Exception as exc:  # noqa: BLE001
            # One unreadable channel directory shouldn't empty the queue
            # for every other channel.
            log.warning(f"Couldn't list videos for {key}: {exc}")
            continue
        for video in videos:
            if video["discarded"] or video["out"]:
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
                "footage_unconfident": int(report.get("footage_unconfident") or 0),
                "scenes": int(report.get("scenes") or 0),
                "scenes_fell_back": int(report.get("scenes_fell_back") or 0),
                "scene_notes": report.get("scene_notes") or [],
                "script_suspect": report.get("script_suspect") or "",
                "shot_count": report.get("shot_count"),
                "similarity_flagged": bool(similarity.get("flagged")),
                "similarity_closest": similarity.get("closest_title"),
                "title_options": report.get("title_options") or [],
                "gate": report.get("gate"),
                "checks": report.get("checks") or {},
                "autopilot": report.get("autopilot"),
                "queued": video["queued"],
                "approved_by": video["links"].get("approved_by"),
                "slot_label": _slot_label(slots, video) if video["queued"] else "",
                # A quiz round, whose questions have their own page.
                "is_quiz": quiz.round_sidecar(gallery.OUTPUT_DIR / video["relpath"]).exists(),
            })
    items.sort(key=lambda v: v["mtime"])
    return items


def _slot_label(slots: dict, video: dict) -> str:
    path = str((gallery.OUTPUT_DIR / video["relpath"]).resolve())
    return _when_label(slots.get(path), queued=True)


def _when_label(when, queued: bool) -> str:
    if when is None:
        return "Goes out on the next check" if queued else ""
    return "Goes out " + when.strftime("%a %d %b, %H:%M")


@bp.route("/review")
def queue():
    items = _queue()
    names = {}
    for item in items:
        names.setdefault(item["channel_key"], item["channel_name"])
    return render_template(
        "review.html",
        items=items[:QUEUE_PAGE_SIZE],
        review_channels=sorted(names.items(), key=lambda kv: kv[1].lower()),
        total_waiting=len(items),
        discard_reasons=gallery.DISCARD_REASONS,
    )


@bp.route("/queued")
def queued_page():
    """Everything approved, in the order it will go out, with when: a grid
    rather than flicking through Review one video at a time."""
    rows = []
    for key, channel in load_channels(validate=False).items():
        plan = channel.publishing
        for path, when in publish_queue.schedule_for(channel):
            info = gallery.load_publish_info(path)
            waits = publish_queue.waiting_for(channel, path)
            if waits:
                label = f"Waits for #{waits}, still in review"
            elif not plan.enabled:
                label = "Waits until the publishing plan is on"
            elif not publish_queue.can_publish(channel):
                label = "Waits until YouTube is connected"
            else:
                label = _when_label(when, queued=True)
            rows.append({"channel_key": key, "channel": channel.channel_display_name,
                         "relpath": str(path.relative_to(gallery.OUTPUT_DIR)).replace("\\", "/"),
                         "title": info["title"] or gallery.video_title(path.name),
                         "number": publish_queue.number_of(path), "when": when, "label": label,
                         "long": gallery.is_long(path)})
    far = datetime.max.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda r: (r["when"] or far, r["channel"], r["number"]))
    return render_template("queued.html", rows=rows)


@bp.route("/insights")
def insights_page():
    data = insights.collect()
    channels = load_channels(validate=False)
    connections = {key: youtube.connection(key) for key in channels}
    return render_template(
        "insights.html",
        data=data,
        headline=insights.headline(data),
        reason_labels=gallery.DISCARD_REASON_LABELS,
        # Channels whose connection predates the statistics permission:
        # they can upload, but their numbers can't be read until reconnected.
        needs_reconnect=[(key, channels[key].channel_display_name)
                         for key, c in connections.items() if c["connected"] and not c["stats"]],
        any_stats_connection=any(c["stats"] for c in connections.values()),
        audience_status={channels[k].channel_display_name: v
                         for k, v in audience.status().items() if k in channels},
        spend_kinds=costs.by_kind(((data.get("spend") or {}).get("all_time") or {}).get("by_operation") or {}),
    )


@bp.route("/insights/refresh-stats", methods=["POST"])
def refresh_stats():
    """Fetch every published video's numbers now, rather than waiting for
    the scheduler's twice-daily refresh."""
    audience.refresh(load_channels(validate=False), force=True)
    return redirect(url_for("review.insights_page") + "#audience")


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


@bp.route("/api/videos/<path:relpath>/queue", methods=["POST"])
def approve(relpath):
    """Approve a video: it joins its channel's publishing queue and goes out
    at the next free slot (core.publish_queue)."""
    target = video_or_404(relpath)
    key = gallery._channel_key_for(target)
    channel = load_channels(validate=False).get(key) if key else None
    if channel is None:
        return jsonify({"error": "Couldn't tell which channel this video belongs to."}), 400
    try:
        publish_queue.enqueue(target, approved_by="you")
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 400
    when = next((w for p, w in publish_queue.schedule_for(channel)
                 if Path(p).resolve() == target.resolve()), None)
    return jsonify({"ok": True, "slot_label": _when_label(when, queued=True)})


def _channel_of(target: Path):
    key = gallery._channel_key_for(target)
    channel = load_channels(validate=False).get(key) if key else None
    if channel is None:
        raise PipelineError("unknown channel", user_message="Couldn't tell which channel this video belongs to.")
    return channel


@bp.route("/api/videos/<path:relpath>/publish-now", methods=["POST"])
def publish_now(relpath):
    """Publish by hand, in one click: save the title and description, upload
    to YouTube through the API, and hand the video to TikTok and Instagram,
    whose posting steps show on its page."""
    target = video_or_404(relpath)
    data = request.get_json(force=True, silent=True) or {}
    try:
        channel = _channel_of(target)
        if "title" in data or "description" in data:
            gallery.save_title_and_description(target, data.get("title", ""), data.get("description", ""))
        result = publish_queue.publish_now(channel, target, privacy=data.get("privacy", "public"))
    except PipelineError as exc:
        log.warning(f"Publishing {relpath} failed: {exc}")
        return jsonify({"error": exc.user_message}), 400
    # TikTok and Instagram are then posted step by step from the video's
    # page (or To post), which the page goes to next.
    return jsonify({"ok": True, **result,
                    "next": url_for("gallery.video_detail", key=channel.key, relpath=relpath)
                    if result["pending"] else ""})


@bp.route("/api/videos/<path:relpath>/reveal", methods=["POST"])
def reveal(relpath):
    """Show the file in Explorer, selected: no hunting through dated
    folders for the right mp4 among its sidecars. From this PC only."""
    from core import phone_access
    if not phone_access.is_local(request.remote_addr):
        return jsonify({"error": "That opens a window on the PC, so it only works from the PC."}), 403
    try:
        posting.reveal(video_or_404(relpath))
    except OSError as exc:
        log.warning(f"Couldn't open Explorer: {exc}")
        return jsonify({"error": "Couldn't open Explorer on this PC."}), 500
    return jsonify({"ok": True})


@bp.route("/api/videos/<path:relpath>/unqueue", methods=["POST"])
def unqueue(relpath):
    publish_queue.unqueue(video_or_404(relpath))
    return jsonify({"ok": True})


@bp.route("/to-post")
def handoff_page():
    """Videos that have gone out and are waiting to be posted to TikTok or
    Instagram from this PC (core.posting)."""
    channels = load_channels(validate=False)
    rows = publish_queue.awaiting_posts(channels)
    for row in rows:
        row["relpath"] = str(row["video_path"].relative_to(gallery.OUTPUT_DIR)).replace("\\", "/")
        row["post"] = posting.plan(channels[row["channel_key"]], row["video_path"])
    return render_template("handoff.html", rows=rows, labels=posting.LABELS)


@bp.route("/api/videos/<path:relpath>/start-post", methods=["POST"])
def start_post(relpath):
    """Open the channel's browser profile at the platform's upload page and
    the video in Explorer. The page that called this has already put the
    caption on the clipboard; it's returned too, in case that failed."""
    target = video_or_404(relpath)
    key = gallery._channel_key_for(target)
    channel = load_channels(validate=False).get(key) if key else None
    if channel is None:
        return jsonify({"error": "Couldn't tell which channel this video belongs to."}), 400
    data = request.get_json(force=True, silent=True) or {}
    try:
        result = posting.start_post(channel, target, data.get("platform", ""))
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 400
    except OSError as exc:
        log.warning(f"Couldn't open the browser or Explorer: {exc}")
        return jsonify({"error": "Couldn't open the browser or Explorer on this PC."}), 500
    return jsonify({"ok": True, **result})


@bp.route("/api/videos/<path:relpath>/posted", methods=["POST"])
def mark_posted(relpath):
    target = video_or_404(relpath)
    data = request.get_json(force=True, silent=True) or {}
    try:
        publish_queue.mark_posted(target, data.get("platform", ""), data.get("url", ""))
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 400
    return jsonify({"ok": True})


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
    from core.paths import slugify
    target = video_or_404(relpath)
    # Named by its title, not its stem: the file lands in Downloads among
    # others, and "countries_tricky_2.mp4" says little.
    title = gallery.load_publish_info(target)["title"] or target.stem
    return send_file(target, as_attachment=True,
                     download_name=f"{slugify(title, fallback=target.stem)}{target.suffix}")
