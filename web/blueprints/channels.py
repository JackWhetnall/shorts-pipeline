"""
Channel list, dashboard, settings, creation, and lifecycle.
"""

from __future__ import annotations

import re

from flask import (
    Blueprint, Response, abort, jsonify, redirect, render_template, request,
    url_for,
)

from core import (
    caption_preview, channel_admin, curriculum, fonts, gallery, jobs,
    scheduler, youtube,
)
from core.assets import has_logo
from core.channels import (
    ChannelConfig, Pacing, Style, channel_to_sparse_dict, read_raw, save_channel,
)
from core.logging_setup import get_logger
from core.errors import ConfigError
from core.footage_stats import library_stats
from core.paths import PROJECT_ROOT, slugify
from pipeline import quote_source
from pipeline.run import fetch_seed
from web import checklist
from web.blueprints.curriculum import channels_running_low
from web.forms import apply_channel_form, format_affiliate_links
from web.helpers import (
    all_channels, as_int, channel_or_404, channel_progress, format_date,
)

log = get_logger(__name__)

bp = Blueprint("channels", __name__)

SECTIONS = ("live", "setup", "future", "archived")
SECTION_TITLES = {"live": "Live", "setup": "Setting up",
                  "future": "Future ideas", "archived": "Archived"}


@bp.route("/")
def index():
    channels = all_channels()
    sections = {name: {} for name in SECTIONS}
    progress = {}

    for key, channel in channels.items():
        info = channel_progress(key, channel)
        info["last_published_label"] = format_date(
            gallery.latest_published_at(channel.output_dir))
        progress[key] = info
        sections[info["section"]][key] = channel

    return render_template(
        "index.html",
        channels=channels, sections=sections, statuses=SECTIONS,
        section_titles=SECTION_TITLES, progress=progress,
        has_logo={key: has_logo(key) for key in channels},
        library=library_stats(),
        # Running out of topics stops generation dead, and the warning is
        # only useful in advance — so it goes where you look daily.
        topics_running_low=channels_running_low(),
        deleted_key=request.args.get("deleted"),
        backup_path=request.args.get("backup"),
    )


@bp.route("/channels/<key>")
def dashboard(key):
    channel = channel_or_404(key)
    info = channel_progress(key, channel)

    social_links = [
        {"label": label, "url": url} for label, url in (
            ("YouTube", channel.socials.youtube_url),
            ("TikTok", channel.socials.tiktok_url),
            ("Instagram", channel.socials.instagram_url),
        ) if url
    ]
    monetization_links = [
        {"label": label, "url": url} for label, url in (
            ("Patreon", channel.monetization.patreon_url),
            ("Merch store", channel.monetization.merch_url),
        ) if url
    ] + [
        {"label": link.get("label") or "Affiliate link", "url": link["url"]}
        for link in channel.monetization.affiliate_links
    ]

    return render_template(
        "channel_dashboard.html",
        key=key, channel=channel,
        topic_plan=curriculum.progress(key) if channel.content_mode == "topic" else None,
        setup_problem=info["setup_problem"],
        video_count=info["video_count"],
        published_count=info["published_count"],
        unpublished_count=info["unpublished_count"],
        last_video_at=format_date(gallery.latest_video_mtime(channel.output_dir)),
        checklist=info["checklist_essential"],
        checklist_extras=info["checklist_extras"],
        checklist_remaining=info["checklist_remaining"],
        extras_remaining=info["extras_remaining"],
        ready_to_publish=info["checklist_remaining"] == 0 and info["section"] != "live",
        social_links=social_links, monetization_links=monetization_links,
        has_logo=has_logo(key),
        schedule=scheduler.get_schedule(key),
        cost=_channel_cost(key),
        rename_error=request.args.get("rename_error"),
    )


def _channel_cost(key: str) -> dict:
    from core import costs
    return costs.summary_for_channel(key)


@bp.route("/channels/<key>/settings", methods=["GET", "POST"])
def settings(key):
    channel = channel_or_404(key)
    if request.method == "POST":
        apply_channel_form(channel, request.form)
        # Saved either way. Refusing the save made a half-set-up channel
        # uneditable: you could not fix its style prompt until you had
        # also given it a voice and a source, which is the rigidity the
        # setup wizard exists to remove. Nothing incomplete can reach a
        # render — channel_progress gates that — so the honest thing here
        # is to save the edit and say what is still outstanding.
        try:
            channel.validate()
        except ConfigError as exc:
            save_channel(channel)
            return redirect(url_for("channels.settings", key=key, saved=1,
                                    incomplete=exc.user_message))
        save_channel(channel)
        return redirect(url_for("channels.settings", key=key, saved=1))

    return render_template(
        "channel_settings.html", channel=channel,
        affiliate_links_text=format_affiliate_links(channel.monetization.affiliate_links),
        saved=request.args.get("saved"),
        incomplete=request.args.get("incomplete"),
        connected=request.args.get("connected"),
        youtube_upload=_youtube_state(key),
        published_count=gallery.video_state_counts(channel.output_dir)["published"],
        topic_plan=curriculum.progress(key) if channel.content_mode == "topic" else None,
        source_labels=quote_source.SOURCE_LABELS,
        voice_name=_voice_name(channel.voice),
    )


def _voice_name(voice_id: str) -> str:
    """The voice's name, if it is one of the premade ones already cached.

    Best-effort and cache-only: the settings page should not make an HTTP
    call, and a cloned voice legitimately will not be in the list.
    """
    if not voice_id:
        return ""
    try:
        from core import voice_lab
        for voice in voice_lab.get_cached_voices():
            if voice["voice_id"] == voice_id:
                return voice["name"]
    except Exception:  # noqa: BLE001 - a label is never worth an error
        pass
    return ""


def _youtube_state(key: str) -> dict:
    """Whether uploads are set up, for the settings page's Links panel.

    Reads two small files. Kept out of the template so the page still
    renders if the token file is unreadable.
    """
    try:
        state = youtube.connection(key)
        state["configured"] = youtube.is_configured()
        return state
    except Exception:  # noqa: BLE001 - a settings page must always render
        log.exception("Could not read YouTube connection state")
        return {"connected": False, "configured": False, "account": ""}


@bp.route("/channels/new", methods=["GET", "POST"])
def new_channel():
    """Just a name. Everything else is the setup wizard.

    This used to be the entire settings form: an output directory, a raw
    ElevenLabs voice ID, a content mode, a style prompt and four tabs of
    options, on one page, before the channel existed. You could not fill
    it in without already having a voice ID to hand, and it let through a
    channel whose voice was the letter "a" and whose output directory was
    the folder every channel writes into.

    Creating on a name alone works because a half-set-up channel is
    already a state this app understands — the home page has a "Setting
    up" section for exactly that, and the checklist says what is missing.
    """
    if request.method == "POST":
        display_name = request.form.get("channel_display_name", "").strip()
        key = (request.form.get("key") or "").strip() or slugify(display_name)

        error = None
        if not display_name:
            error = "Give the channel a name."
        elif not key:
            error = ("That name has no letters or numbers in it, so there is "
                     "nothing to build a folder name from. Set the key yourself.")
        elif key in read_raw():
            error = f'A channel called "{key}" already exists.'

        if error:
            return render_template("new_channel.html", display_name=display_name,
                                   key=key, error=error), 400

        # Defaults that make the channel valid the moment it has a voice
        # and a source. Nothing here is a guess the user has to undo.
        channel = ChannelConfig(key=key, channel_display_name=display_name,
                                content_mode="topic")
        channel_admin.create_channel(channel, complete=False)
        log.info(f"Created channel {key}")
        return redirect(url_for("setup.setup_step", key=key, step="content"))

    return render_template("new_channel.html", display_name="", key="")


@bp.route("/channels/<key>/create")
def create_video(key):
    channel = channel_or_404(key)
    return render_template("create_video.html", key=key, channel=channel)


# --- lifecycle --------------------------------------------------------

@bp.route("/channels/<key>/rename", methods=["POST"])
def rename(key):
    channel_or_404(key)
    try:
        result = channel_admin.rename_channel(key, request.form.get("new_name", ""))
    except ConfigError as exc:
        return redirect(url_for("channels.dashboard", key=key,
                                rename_error=exc.user_message))
    return redirect(url_for("channels.dashboard", key=result["new_key"]))


@bp.route("/channels/<key>/archive", methods=["POST"])
def archive(key):
    channel_or_404(key)
    channel_admin.set_archived(key, True)
    return redirect(url_for("channels.settings", key=key))


@bp.route("/channels/<key>/unarchive", methods=["POST"])
def unarchive(key):
    channel_or_404(key)
    channel_admin.set_archived(key, False)
    return redirect(url_for("channels.settings", key=key))


@bp.route("/channels/<key>/checklist/<item_id>/toggle-manual", methods=["POST"])
def toggle_checklist(key, item_id):
    channel_or_404(key)
    if item_id not in checklist.ITEM_IDS:
        abort(404, description="That isn't a checklist item.")
    channel_admin.toggle_checklist_override(key, item_id)
    return redirect(url_for("channels.dashboard", key=key))


@bp.route("/channels/<key>/delete", methods=["GET"])
def delete_confirm(key):
    channel = channel_or_404(key)
    state = gallery.video_state_counts(channel.output_dir)
    return render_template("delete_channel_confirm.html", key=key, channel=channel,
                           video_count=state["total"])


@bp.route("/channels/<key>/delete", methods=["POST"])
def delete(key):
    channel_or_404(key)
    # The typed-key confirmation is enforced here as well as in the
    # browser: a disabled submit button is a convenience, never a check.
    if request.form.get("confirm_key") != key:
        abort(400, description="The typed channel name didn't match.")
    zip_path = channel_admin.delete_channel(key)
    backup = str(zip_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    return redirect(url_for("channels.index", deleted=key, backup=backup))


@bp.route("/api/channels/reorder", methods=["POST"])
def reorder():
    data = request.get_json(force=True, silent=True) or {}
    keys = data.get("keys")
    if not isinstance(keys, list) or not keys:
        return jsonify({"error": "No channel order was sent."}), 400
    channel_admin.reorder_channels(keys)
    return jsonify({"ok": True})


# --- scheduling -------------------------------------------------------

@bp.route("/channels/<key>/schedule", methods=["POST"])
def set_schedule(key):
    channel_or_404(key)
    hour_raw = (request.form.get("hour") or "").strip()
    schedule = scheduler.Schedule(
        enabled=request.form.get("schedule_enabled") == "on",
        every_days=as_int(request.form.get("every_days"), default=1, minimum=1, maximum=90),
        hour=as_int(hour_raw, default=None, minimum=0, maximum=23) if hour_raw else None,
    )
    scheduler.set_schedule(key, schedule)
    return redirect(url_for("channels.dashboard", key=key))


# --- generation triggers ---------------------------------------------

def _times_used(channel, seed) -> dict:
    """Has this quote or topic come up before?

    Filenames were deliberately made readable so repeats are visible at a
    glance — but only while browsing a folder. At the moment of decision,
    with Reroll and Use this on screen, nothing said so.
    """
    from core.paths import slugify
    stem = slugify(seed.title, fallback="video")
    directory = (PROJECT_ROOT / channel.output_dir)
    if not directory.exists():
        return {"count": 0, "last": None}
    matches = [p for p in directory.rglob("*.mp4")
               if p.stem == stem or p.stem.rsplit("_", 1)[0] == stem]
    if not matches:
        return {"count": 0, "last": None}
    return {"count": len(matches),
            "last": format_date(max(p.stat().st_mtime for p in matches))}


@bp.route("/api/channels/<key>/seed", methods=["POST"])
def api_seed(key):
    channel = channel_or_404(key)
    seed = fetch_seed(channel)
    return jsonify({
        "seed": seed.to_jsonable(),
        "description": seed.describe(),
        "history": _times_used(channel, seed),
    })


@bp.route("/api/channels/<key>/preview-script", methods=["POST"])
def preview_script(key):
    """Generate a script and nothing else.

    Tuning the style prompt used to mean rendering a complete video to see
    what changed — minutes and real money for a text edit. This is one
    call, a few seconds, about a cent."""
    import time
    from core import costs
    from pipeline.script_gen import preview_script as run_preview

    channel = channel_or_404(key)
    started = time.time()
    seed = fetch_seed(channel)
    script = run_preview(seed, channel)
    spend = costs.summary_between(started, time.time(), key)

    return jsonify({
        "seed": seed.describe(),
        "cost": costs.format_usd(spend["total_usd"]),
        "script": {
            "title": script.title,
            "title_options": script.title_options,
            "description_body": script.description_body,
            "segments": [{"text": s.text, "shot_brief": s.shot_brief,
                          "keywords": s.keywords} for s in script.segments],
        },
    })


@bp.route("/api/channels/<key>/voice", methods=["POST"])
def apply_voice(key):
    """Set a voice and speed from the Voice Lab.

    The Lab knew the voice, the speed and the cadence, and then asked you
    to remember an ID, open another page and type it in."""
    from core.channels import save_channel

    channel = channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    voice_id = (data.get("voice_id") or "").strip()
    if not voice_id:
        return jsonify({"error": "No voice was chosen."}), 400
    channel.voice = voice_id
    try:
        channel.speed = float(data.get("speed", channel.speed))
    except (TypeError, ValueError):
        pass
    # The cadence preset is resolved here rather than in the browser, so
    # the preset table has exactly one definition.
    from core.voice_lab import CADENCE_PRESETS
    preset = CADENCE_PRESETS.get(data.get("preset"))
    if preset:
        for field, value in preset["pacing"].items():
            if field in channel.pacing.keys():
                setattr(channel.pacing, field, float(value))
    save_channel(channel)
    return jsonify({"ok": True, "channel": channel.channel_display_name})


@bp.route("/api/channels/<key>/generate", methods=["POST"])
def api_generate(key):
    channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    seed = data.get("seed")
    if not seed:
        return jsonify({"error": "No quote or topic was chosen."}), 400
    return jsonify({"job_id": jobs.start_job(key, seed)})


@bp.route("/channels/<key>/generate-now", methods=["POST"])
def generate_now(key):
    """Fetch a seed and start, skipping the review step.

    Reviewing a seed is useful when you're watching. It adds nothing to a
    run you're about to walk away from, which is what this button is for.
    """
    channel = channel_or_404(key)
    seed = fetch_seed(channel)
    return jsonify({"job_id": jobs.start_job(key, seed.to_jsonable())})


@bp.route("/api/channels/generate-all", methods=["POST"])
def api_generate_all():
    """Start every eligible channel, using the same eligibility rule as
    the per-card button."""
    started, skipped = [], []
    for key, channel in all_channels().items():
        info = channel_progress(key, channel)
        if not info["can_generate"]:
            skipped.append({"key": key, "reason": _why_not(info)})
            continue
        try:
            jobs.start_job(key, fetch_seed(channel).to_jsonable())
            started.append(key)
        except Exception as exc:  # noqa: BLE001 - one channel must not stop the rest
            from core.errors import friendly_message
            skipped.append({"key": key, "reason": friendly_message(exc)})
    return jsonify({"started": started, "skipped": skipped})


def _why_not(info: dict) -> str:
    if info["setup_problem"]:
        # The most actionable reason, so it goes first — "not live yet"
        # tells you nothing about the fact that the voice is unset.
        return info["setup_problem"]
    if info["active_job"]:
        return "already generating"
    if info["section"] != "live":
        return "not live yet"
    if info["unpublished_count"]:
        return f"{info['unpublished_count']} video(s) still unpublished"
    return "not eligible"


@bp.route("/api/caption-preview", methods=["POST"])
def caption_preview_image():
    """A real caption frame, rendered from the Look form's current values.

    POST rather than GET because the values come from the form as it is
    being edited, not from what is saved — the whole point is to see an
    unsaved change before committing to it. Unknown or malformed values
    fall back to the schema defaults, so a half-typed hex colour renders
    the previous frame instead of a 500.
    """
    style = Style(
        font_face=request.form.get("font_face") or Style.font_face,
        font_size=as_int(request.form.get("font_size"), Style.font_size, 12, 200),
        base_color=_hex(request.form.get("base_color"), Style.base_color),
        highlight_color=_hex(request.form.get("highlight_color"), Style.highlight_color),
        stroke_color=_hex(request.form.get("stroke_color"), Style.stroke_color),
        stroke_width=as_int(request.form.get("stroke_width"), Style.stroke_width, 0, 30),
    )
    try:
        png = caption_preview.render(style, Pacing())
    except Exception:
        log.exception("Caption preview failed")
        return jsonify({"error": "Could not render a preview."}), 500
    return Response(png, mimetype="image/png",
                    headers={"Cache-Control": "no-store"})


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex(value: str, fallback: str) -> str:
    value = (value or "").strip()
    return value if _HEX_RE.match(value) else fallback
