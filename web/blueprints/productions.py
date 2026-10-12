"""
A documentary channel's productions (core.production, decision 074): the
videos coming up, each made in stages the owner approves one at a time,
and each stage's work to read, edit, redo or approve.

Every stage's work runs as a job, at batch prices unless asked for now,
so it shows on Activity with Accelerate like any video.
"""

from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, send_file, url_for

from core import curriculum, jobs, production, storyboard
from core.errors import PipelineError
from core.logging_setup import get_logger
from web.helpers import channel_or_404

log = get_logger(__name__)

bp = Blueprint("productions", __name__)

UPCOMING = 5


def _channel(key: str):
    channel = channel_or_404(key)
    if channel.format != "documentary":
        abort(404, description="Only a documentary channel has productions.")
    return channel


def _back(key: str, subtopic_id: str, note: str = "", anchor: str = None):
    return redirect(url_for("productions.page", key=key, subtopic_id=subtopic_id, note=note or None,
                            _anchor=anchor))


def busy(channel_key: str) -> dict:
    """{(plan entry id, stage): job} for production stages being made or
    waiting in the queue."""
    out = {}
    for job in jobs.active_in_order():
        seed = job.get("seed") or {}
        if job.get("channel_key") == channel_key and seed.get("type") == "production":
            out[(seed.get("subtopic_id"), seed.get("stage"))] = job
    return out


def summary(channel, row: dict, working: dict) -> dict:
    data = production.load(channel.key, row["id"], row["title"])
    stages = []
    for stage in production.STAGES:
        state = production.state(data, stage)
        if (row["id"], stage) in working:
            state = "working"
        stages.append({"stage": stage, "label": production.LABELS[stage], "state": state})
    return {"row": row, "data": data, "stages": stages, "current": production.current(data)}


@bp.route("/channels/<key>/productions")
def index(key):
    channel = _channel(key)
    working = busy(key)
    upcoming = storyboard.upcoming(channel, count=UPCOMING)
    shown = {r["id"] for r in upcoming}
    # Anything else part-way through, and every film made, listed after:
    # a production stays reachable once its plan entry is used.
    others, made = [], []
    for data in production.all_for(key):
        row = curriculum.find(key, data["subtopic_id"])
        if not row or row["id"] in shown:
            continue
        (made if data.get("video") else others).append(row)
    from core import lessons, long_form
    setup_steps = long_form.steps(channel)
    # Shown until the first film is started, and whenever a needed step
    # comes undone (decision 076).
    show_setup = any(not s.done and not s.optional for s in setup_steps)
    return render_template("productions.html", key=key, channel=channel,
                           upcoming=[summary(channel, r, working) for r in upcoming],
                           others=[summary(channel, r, working) for r in others],
                           made=[summary(channel, r, working) for r in reversed(made)],
                           setup_steps=setup_steps, show_setup=show_setup,
                           first_film=upcoming[0] if upcoming else None,
                           lessons=lessons.load(key),
                           note=request.args.get("note", ""))


@bp.route("/channels/<key>/lessons", methods=["POST"])
def save_lessons(key):
    """The owner's edit of what the channel's viewers have taught it."""
    from core import lessons
    _channel(key)
    lessons.replace(key, request.form.get("lessons", "").splitlines())
    return redirect(url_for("productions.index", key=key, note="Saved."))


@bp.route("/channels/<key>/productions/<subtopic_id>")
def page(key, subtopic_id):
    channel = _channel(key)
    row = curriculum.find(key, subtopic_id)
    if row is None:
        abort(404, description="That video is no longer in the plan.")
    working = busy(key)
    info = summary(channel, row, working)
    data = info["data"]
    from pipeline.documentary import script as scripts
    from pipeline.documentary import stills as storyboard_stills
    scene_count = len((data.get("script") or {}).get("scenes") or [])
    minutes = float(channel.documentary.minutes)
    scenes = (data.get("script") or {}).get("scenes") or []
    missing = [i for i, s in enumerate(scenes) if str(i) not in (data.get("stills") or {})]
    # What a fresh storyboard would keep (decision 088), for the button's price.
    try:
        keeping = len(storyboard_stills.reusable(channel, data, scenes)) if scenes and \
            production.state(data, "stills") in ("todo", "stale", "failed") else 0
    except Exception as exc:  # noqa: BLE001 - the page shows without the estimate
        log.warning(f"Couldn't work out which pictures to keep: {exc}")
        keeping = 0
    to_draw = sum(1 for s in scenes if s.get("medium") != "card") - keeping
    video_rel = _made(channel, (data.get("video") or {}).get("path"))
    report, viewers = {}, {}
    if video_rel:
        from core import gallery, retention
        from core.paths import OUTPUT_DIR
        made_path = OUTPUT_DIR / video_rel
        report = gallery.load_report(made_path) or {}
        viewers = retention.for_video(made_path)
    return render_template(
        "production.html", key=key, channel=channel, row=row, info=info, data=data,
        look_chosen=look_chosen(channel),
        stage_jobs={stage: job for (sid, stage), job in working.items() if sid == subtopic_id},
        framings=scripts.FRAMINGS, cameras=scripts.CAMERA,
        words=scripts.words(data["script"]) if data.get("script") else 0,
        stills_cost=storyboard_stills.cost_estimate(channel, max(0, to_draw) if scenes else round(
            minutes * 60 / channel.documentary.scene_seconds)),
        missing=missing, keeping=keeping, to_draw=max(0, to_draw),
        missing_cost=storyboard_stills.cost_estimate(channel, len(missing)),
        voice_chars=sum(len(s["narration"]) + 1 for s in (data.get("script") or {}).get("scenes") or []),
        video=video_rel, report=report, viewers=viewers,
        angle=production.chosen_angle(data), packaging=production.packaging(data),
        old_video=_made(channel, (data.get("video") or {}).get("retired")),
        teaser_videos=[v for v in (_made(channel, p) for p in (data.get("teasers") or {}).get("videos") or []) if v],
        speed={stage: _speed(key, stage) for stage in production.STAGES},
        note=request.args.get("note", ""))


def _speed(channel_key: str, stage: str) -> dict:
    """Each stage's price and finish, at batch prices and now (core.estimates)."""
    from core import estimates
    try:
        return estimates.describe({"type": "production", "stage": stage}, channel_key)
    except Exception as exc:  # noqa: BLE001 - the page shows without the estimate
        log.warning(f"Couldn't estimate {stage}: {exc}")
        return None


@bp.route("/channels/<key>/productions/<subtopic_id>/state")
def state(key, subtopic_id):
    """The stages' states, polled by the page while one is being made so it
    fills in by itself when it's done."""
    from flask import jsonify
    _channel(key)
    data = production.load(key, subtopic_id)
    working = [stage for (sid, stage) in busy(key) if sid == subtopic_id]
    return jsonify({"stages": {s: production.state(data, s) for s in production.STAGES}, "busy": working})


def _made(channel, rel: str):
    """A made video's path as the video page takes it, if it's still there."""
    if not rel:
        return None
    from core import gallery
    from core.paths import OUTPUT_DIR
    path = gallery.resolve_output_dir(channel.output_dir) / rel
    if not path.exists():
        return None
    return str(path.relative_to(OUTPUT_DIR)).replace("\\", "/")


@bp.route("/channels/<key>/productions/<subtopic_id>/asset/<path:name>")
def asset(key, subtopic_id, name):
    _channel(key)
    path = production.asset(key, subtopic_id, name)
    if not path.is_file():
        abort(404)
    return send_file(path, max_age=3600)


def look_chosen(channel) -> bool:
    return bool(channel.animation.style)


def start(channel, row: dict, stage: str, now: bool = False, **extra) -> str:
    """Queue a stage's job. Returns its id."""
    data = production.load(channel.key, row["id"], row["title"])
    if stage in ("stills", "video", "teasers") and not look_chosen(channel):
        raise PipelineError("no look", user_message=(
            "Choose the channel's look first (Settings, Animation): every picture on the channel "
            "is drawn in it, so it's worth choosing before the first one."))
    if not production.can_start(data, stage):
        raise PipelineError(f"{stage} not ready", user_message="Approve the stages before this one first.")
    if (row["id"], stage) in busy(channel.key):
        raise PipelineError("already queued", user_message="That's already being made.")
    seed = {"type": "production", "subtopic_id": row["id"], "stage": stage,
            "topic": f"{row['title']}: {production.LABELS[stage].lower()}",
            **{k: v for k, v in extra.items() if v not in (None, "", 0, [], {})}}
    return jobs.start_job(channel.key, seed, ahead=not now, behind=True)


@bp.route("/channels/<key>/productions/<subtopic_id>/start/<stage>", methods=["POST"])
def start_stage(key, subtopic_id, stage):
    channel = _channel(key)
    row = curriculum.find(key, subtopic_id)
    if row is None or stage not in production.STAGES:
        abort(404)
    form = request.form
    extra = {"note": " ".join(form.get("note", "").split())}
    if form.get("chapter"):
        extra["chapter"] = int(form["chapter"])
    if form.get("missing"):
        data = production.load(key, subtopic_id)
        extra["only"] = [i for i in range(len((data.get("script") or {}).get("scenes") or []))
                         if str(i) not in (data.get("stills") or {})]
    if form.get("scene") not in (None, ""):
        index = int(form["scene"])
        extra["only"] = [index]
        if extra["note"]:
            extra["notes"] = {str(index): extra["note"]}
    try:
        start(channel, row, stage, now=form.get("now") == "on", **extra)
    except PipelineError as exc:
        return _back(key, subtopic_id, exc.user_message, stage)
    return _back(key, subtopic_id, "Started. It shows on Activity; this page fills in when it's done.", stage)


@bp.route("/channels/<key>/productions/<subtopic_id>/approve/<stage>", methods=["POST"])
def approve(key, subtopic_id, stage):
    channel = _channel(key)
    row = curriculum.find(key, subtopic_id)
    if row is None or stage not in production.STAGES:
        abort(404)
    try:
        if stage == "teasers":
            # Approving the teasers' scripts is what makes them.
            start(channel, row, "teasers", now=request.form.get("now") == "on")
            return _back(key, subtopic_id, "Making the teasers; they go to Review when they're done.", stage)
        choice = request.form.get("angle")
        production.approve(key, subtopic_id, stage,
                           choice=int(choice) if stage == "pitch" and choice not in (None, "") else None)
        if stage == "outline":
            from pipeline.documentary import cast
            cast.merge(key, subtopic_id, production.load(key, subtopic_id)["outline"].get("cast") or [])
    except PipelineError as exc:
        return _back(key, subtopic_id, exc.user_message, stage)
    nxt = production.STAGES[production.STAGES.index(stage) + 1] if stage != production.STAGES[-1] else None
    return _back(key, subtopic_id, "Approved." + (f" Next: the {production.LABELS[nxt].lower()}."
                                                  if nxt else ""), nxt or stage)


@bp.route("/channels/<key>/productions/<subtopic_id>/title", methods=["POST"])
def retitle(key, subtopic_id):
    """Another angle's title and thumbnail words, the film kept (decision 090)."""
    channel = _channel(key)
    if curriculum.find(key, subtopic_id) is None:
        abort(404)
    try:
        index = int(request.form.get("angle", ""))
    except ValueError:
        abort(400)
    try:
        data = production.retitle(key, subtopic_id, index)
        video = (data.get("video") or {}).get("path")
        if video:
            from pipeline.documentary import run, thumbs
            thumbs.retitled(channel, data, run._root(channel) / video)
    except PipelineError as exc:
        return _back(key, subtopic_id, exc.user_message, "pitch")
    return _back(key, subtopic_id, "Title changed.", "pitch")


@bp.route("/channels/<key>/productions/<subtopic_id>/outline", methods=["POST"])
def save_outline(key, subtopic_id):
    _channel(key)
    form = request.form
    turns = form.getlist("chapter_turn") or [""] * len(form.getlist("chapter_title"))
    chapters = [{"title": t.strip(), "says": s.strip(), "turn": u.strip(), "shows": w.strip(),
                 "minutes": _float(m, 1.0)}
                for t, s, u, w, m in zip(form.getlist("chapter_title"), form.getlist("chapter_says"), turns,
                                         form.getlist("chapter_shows"), form.getlist("chapter_minutes"))
                if s.strip()]
    cast = [{"name": " ".join(n.split()), "kind": k if k in ("character", "place", "object") else "character",
             "description": " ".join(d.split())}
            for n, k, d in zip(form.getlist("cast_name"), form.getlist("cast_kind"),
                               form.getlist("cast_description")) if n.strip()]
    if not chapters:
        return _back(key, subtopic_id, "The outline needs at least one chapter.", "outline")
    old = production.load(key, subtopic_id).get("outline") or {}
    outline = {**old, "through_line": form.get("through_line", "").strip(),
               "visual_concept": form.get("visual_concept", "").strip(),
               "title_options": [t.strip() for t in form.get("title_options", "").splitlines() if t.strip()]
               or old.get("title_options", []),
               "chapters": chapters, "cast": cast}
    try:
        production.edited(key, subtopic_id, "outline", outline)
        from pipeline.documentary import cast as library
        library.merge(key, subtopic_id, cast)
    except PipelineError as exc:
        return _back(key, subtopic_id, exc.user_message, "outline")
    return _back(key, subtopic_id, "Saved and approved.", "outline")


@bp.route("/channels/<key>/productions/<subtopic_id>/script", methods=["POST"])
def save_script(key, subtopic_id):
    _channel(key)
    form = request.form
    old = production.load(key, subtopic_id).get("script") or {}
    scenes = []
    import json
    from pipeline.documentary import script as scripts
    n = len(form.getlist("narration"))
    media = form.getlist("medium") or ["picture"] * n
    queries = form.getlist("art_query") or [""] * n
    card_json = form.getlist("card") or [""] * n
    fields = zip(form.getlist("chapter"), form.getlist("narration"), form.getlist("direction"),
                 form.getlist("framing"), form.getlist("camera"), form.getlist("caption"),
                 form.getlist("cast"), media, queries, card_json)
    for chapter, narration, direction, framing, camera, caption, cast, medium, query, card in fields:
        narration, direction = " ".join(narration.split()), " ".join(direction.split())
        if not narration:
            continue
        scene = {"chapter": int(chapter or 1), "narration": narration, "direction": direction,
                 "framing": framing, "camera": camera, "caption": " ".join(caption.split()),
                 "cast": [c.strip() for c in cast.split(";") if c.strip()],
                 "medium": medium if medium in scripts.MEDIA else "picture"}
        # A card or painting kept as it was written (decision 086).
        if scene["medium"] == "card":
            try:
                scene["card"] = scripts.clean_card(json.loads(card or "{}"))
            except ValueError:
                scene["card"] = {}
            if not scene["card"]:
                scene["medium"] = "picture"
                scene.pop("card")
        if scene["medium"] == "painting":
            scene["art_query"] = " ".join(query.split())
            if not scene["art_query"]:
                scene["medium"] = "picture"
        scenes.append(scene)
    if not scenes:
        return _back(key, subtopic_id, "The script needs at least one scene.", "script")
    try:
        production.edited(key, subtopic_id, "script", {**old, "scenes": scenes,
                                                       "description": form.get("description", "").strip()})
    except PipelineError as exc:
        return _back(key, subtopic_id, exc.user_message, "script")
    return _back(key, subtopic_id, "Saved and approved.", "script")


def _float(raw, default):
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return default
