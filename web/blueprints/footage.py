"""
The footage library, as a page.

264 clips and no way to look at them. When a match came out poor there
was no way to see what had been available, whether a clip's description
was simply wrong, or where coverage was thin — the only view was a
terminal command printing 264 paragraphs.

Being able to see the library matters more than it sounds, because a bad
description silently poisons every future match for that clip and there
was no way to notice, let alone fix it.
"""

from __future__ import annotations

import subprocess

from flask import Blueprint, abort, jsonify, render_template, request, send_file

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import LIBRARY_DIR, safe_join, PathTraversalError
from pipeline.footage import retrieval, store
from web.helpers import as_int

log = get_logger(__name__)

bp = Blueprint("footage", __name__)

# Each uncached thumbnail costs ~230 ms to extract, so the first view of
# a page is roughly this many times that. 36 keeps it under ten seconds
# while still filling a wide screen; every later view is instant.
PAGE_SIZE = 36


@bp.route("/footage")
def browse():
    query = (request.args.get("q") or "").strip()
    show = request.args.get("show", "all")
    page = as_int(request.args.get("page"), default=1, minimum=1)

    clips = store.all_clips()

    if query:
        # Reuse the same lexical index the matcher uses, so what you see
        # here is what the matcher would have seen.
        with store.connect() as conn:
            rows = retrieval._search(conn, " OR ".join(
                f'"{t}"' for t in retrieval._terms(query)) or "", 500)
        ranked = [r["filename"] for r in rows]
        by_name = {c.filename: c for c in clips}
        clips = [by_name[n] for n in ranked if n in by_name]

    if show == "unverified":
        clips = [c for c in clips if not c.license_verified]
    elif show == "unused":
        clips = [c for c in clips if not c.use_count]
    elif show == "missing":
        clips = [c for c in clips if not (LIBRARY_DIR / c.filename).exists()]
    elif show == "unenriched":
        clips = [c for c in clips if not c.enriched]
    elif show == "rejected":
        clips = [c for c in clips if c.reject_count]

    total = len(clips)
    start = (page - 1) * PAGE_SIZE
    visible = clips[start:start + PAGE_SIZE]

    return render_template(
        "footage.html",
        clips=visible, total=total, query=query, show=show,
        page=page, pages=max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        library_total=store.count(),
        unverified=store.unverified_license_count(),
        unenriched=sum(1 for c in store.all_clips() if not c.enriched),
    )


@bp.route("/footage/<path:filename>/preview")
def preview(filename):
    """Stream a clip so it can be watched in place. A description is only
    checkable against the thing it describes."""
    try:
        target = safe_join(LIBRARY_DIR, filename)
    except PathTraversalError:
        abort(403, description="That file isn't available.")
    if not target.exists():
        abort(404, description="That clip's file is missing from the library.")
    return send_file(target, mimetype="video/mp4", conditional=True)


@bp.route("/footage/<path:filename>/thumb")
def thumbnail(filename):
    """Cached poster frame, generated on first request."""
    from core.footage_stats import clip_thumbnail

    clip = store.get(filename)
    if clip is None:
        abort(404, description="No clip by that name.")
    try:
        thumb = clip_thumbnail(clip.filename)
    except FileNotFoundError:
        abort(404, description="That clip's file is missing from the library.")
    except Exception as exc:  # noqa: BLE001 - a bad clip must not 500 the grid
        log.warning(f"  [footage] couldn't make a thumbnail for {filename}: {exc}")
        abort(404, description="Couldn't read a frame from that clip.")
    return send_file(thumb, mimetype="image/jpeg", conditional=True)


@bp.route("/api/footage/<path:filename>/describe", methods=["POST"])
def redescribe(filename):
    """Regenerate a clip's description from its own frames.

    A wrong description is invisible and permanent: it silently poisons
    every future match for that clip, and until now there was no way to
    correct one short of deleting the clip and re-adding it.
    """
    from pipeline.footage import intake

    clip = store.get(filename)
    if clip is None:
        return jsonify({"error": "No clip by that name."}), 404
    path = LIBRARY_DIR / clip.filename
    if not path.exists():
        return jsonify({"error": "That clip's file is missing."}), 404

    frames = intake.extract_frames(path)
    clip.description = intake.describe(frames)
    clip.frame_hashes = [intake.frame_hash(f) for f in frames]
    store.upsert(clip)
    log.info(f"  [footage] re-described {clip.filename}")
    return jsonify({"ok": True, "description": clip.description})


@bp.route("/api/footage/<path:filename>/license", methods=["POST"])
def set_license(filename):
    clip = store.get(filename)
    if clip is None:
        return jsonify({"error": "No clip by that name."}), 404
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("license") or "").strip()
    if not text:
        return jsonify({"error": "Enter the licence terms you've confirmed."}), 400
    clip.license = text
    clip.license_verified = True
    store.upsert(clip)
    return jsonify({"ok": True, "license": clip.license})


@bp.route("/api/footage/<path:filename>/delete", methods=["POST"])
def delete(filename):
    clip = store.get(filename)
    if clip is None:
        return jsonify({"error": "No clip by that name."}), 404
    try:
        target = safe_join(LIBRARY_DIR, clip.filename)
    except PathTraversalError:
        abort(403)
    target.unlink(missing_ok=True)
    store.delete([clip.filename])
    log.info(f"  [footage] deleted {clip.filename}")
    return jsonify({"ok": True})
