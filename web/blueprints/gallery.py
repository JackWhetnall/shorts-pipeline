"""
The gallery, individual video pages, and publish/discard tracking.
"""

from __future__ import annotations

from flask import (
    Blueprint, abort, jsonify, redirect, render_template, request,
    send_from_directory, url_for,
)

from core import gallery as gallery_core
from core.logging_setup import get_logger
from core.paths import OUTPUT_DIR
from web.helpers import channel_or_404, format_date, format_iso_date, video_or_404

log = get_logger(__name__)

bp = Blueprint("gallery", __name__)


@bp.route("/channels/<key>/gallery")
def channel_gallery(key):
    channel = channel_or_404(key)
    videos = gallery_core.list_videos(channel.output_dir)
    for video in videos:
        if video["published"] and video["links"]["published_at"]:
            video["date_label"] = f"Published {format_iso_date(video['links']['published_at'])}"
        else:
            video["date_label"] = f"Created {format_date(video['mtime'])}"

    active = [v for v in videos if not v["discarded"]]
    discarded = [v for v in videos if v["discarded"]]
    return render_template(
        "gallery.html", key=key, channel=channel,
        unpublished=[v for v in active if not v["published"]],
        published=[v for v in active if v["published"]],
        discarded=discarded,
        # Shown on the delete button, because "delete 19 videos" is a
        # different decision from "reclaim 416 MB" and the second one is
        # the reason anybody does it.
        discarded_bytes=sum(_disk_size(v) for v in discarded),
    )


def _disk_size(video: dict) -> int:
    """A video plus its sidecars. Best-effort: a file that vanished between
    the listing and this call should not 500 the gallery."""
    try:
        return sum(f.stat().st_size
                   for f in gallery_core.sidecars_of(OUTPUT_DIR / video["relpath"]))
    except OSError:
        return 0


@bp.route("/channels/<key>/videos/<path:relpath>/thumbnail")
def thumbnail(key, relpath):
    channel_or_404(key)
    target = video_or_404(relpath)
    thumb = gallery_core.get_or_create_thumbnail(target)
    return send_from_directory(thumb.parent, thumb.name)


@bp.route("/channels/<key>/videos/<path:relpath>", methods=["GET", "POST"])
def video_detail(key, relpath):
    channel = channel_or_404(key)
    target = video_or_404(relpath)

    if request.method == "POST":
        gallery_core.save_publish_info(
            target, {f: request.form.get(f, "") for f in gallery_core.PUBLISH_LINK_FIELDS})
        return redirect(url_for("gallery.video_detail", key=key, relpath=relpath))

    links = gallery_core.load_publish_info(target)
    meta_path = target.with_name(f"{target.stem}_meta.txt")
    return render_template(
        "video_detail.html", key=key, channel=channel, relpath=relpath,
        name=target.name, title=gallery_core.video_title(target.name),
        links=links, published=gallery_core.is_published(links),
        discarded=links["discarded"],
        created_label=format_date(target.stat().st_mtime),
        published_label=format_iso_date(links["published_at"]),
        meta_text=(gallery_core.read_text_tolerantly(meta_path)
                   if meta_path.exists() else None),
        cost=gallery_core.load_cost_summary(target),
    )


@bp.route("/channels/<key>/videos/discard", methods=["POST"])
def discard(key):
    """Bulk discard. The gallery's multi-select posts every chosen path
    here at once, so a single bad take and a real clear-out use the same
    mechanism — there's no separate single-video route to keep in sync."""
    channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    relpaths = data.get("relpaths")
    if not isinstance(relpaths, list) or not relpaths:
        return jsonify({"error": "Nothing was selected."}), 400

    discarded = []
    for relpath in relpaths:
        try:
            target = video_or_404(relpath)
        except Exception:  # noqa: BLE001 - skip anything stale, discard the rest
            continue
        gallery_core.set_discarded(target, True)
        discarded.append(relpath)
    return jsonify({"discarded": discarded})


@bp.route("/channels/<key>/videos/<path:relpath>/restore", methods=["POST"])
def restore(key, relpath):
    channel_or_404(key)
    gallery_core.set_discarded(video_or_404(relpath), False)
    return redirect(url_for("gallery.channel_gallery", key=key))


@bp.route("/channels/<key>/videos/<path:relpath>/delete", methods=["POST"])
def delete_video(key, relpath):
    """Permanently remove one discarded video.

    `gallery.purge` refuses anything not marked discarded, so the only
    route to deleting a video is to discard it first — a decision made in
    the review queue, with a reason attached, and reversible until this
    point.
    """
    channel_or_404(key)
    try:
        gallery_core.purge(video_or_404(relpath), key)
    except ValueError:
        abort(400, description="That video isn't discarded, so it can't be deleted.")
    except OSError:
        abort(400, description="Some of that video's files are in use. "
                               "Close anything playing it and try again.")
    return redirect(url_for("gallery.channel_gallery", key=key))


@bp.route("/channels/<key>/videos/delete-discarded", methods=["POST"])
def delete_all_discarded(key):
    """Empty the discarded section in one go.

    Failures are counted rather than raised: one file locked by a media
    player should not leave the other eighteen behind.
    """
    channel = channel_or_404(key)
    removed = failed = 0
    for video in gallery_core.list_videos(channel.output_dir):
        if not video["discarded"]:
            continue
        try:
            gallery_core.purge(OUTPUT_DIR / video["relpath"], key)
            removed += 1
        except (OSError, ValueError):
            failed += 1
    if failed:
        log.warning(f"{key}: deleted {removed} discarded videos, {failed} could not be removed")
    return redirect(url_for("gallery.channel_gallery", key=key))


@bp.route("/videos/<path:relpath>")
def serve_video(relpath):
    video_or_404(relpath)
    return send_from_directory(OUTPUT_DIR, relpath)
