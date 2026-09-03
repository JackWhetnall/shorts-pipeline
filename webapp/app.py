"""
Local web GUI for the pipeline: pick a channel, edit its settings, create
a new channel, trigger a video generation with live progress, and browse
finished videos — instead of hand-editing config/channels.py and running
main.py blind. See CLAUDE.md's "Web GUI" section for the overall design
(config storage, non-interactive generation flow, job execution model).

Run with: python webapp/app.py
Then open http://127.0.0.1:5000/
"""

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, request, jsonify, render_template, redirect, url_for, send_from_directory, abort

import config.channels as channels_module
import main as main_module
import merch_assets
from quote_source import SOURCES
import webapp.channel_store as channel_store
import webapp.gallery as gallery
import webapp.jobs as jobs
import webapp.logo_gen as logo_gen
import webapp.voice_lab as voice_lab

OUTPUT_ROOT = (PROJECT_ROOT / "output").resolve()
CHANNELS_ASSETS_ROOT = (PROJECT_ROOT / "channels").resolve()
# Logo first (every later step benefits from having one - a profile
# picture for socials, a mark for merch), then a dedicated email, then
# socials, then monetization accounts in the order they're easiest to set
# up (Patreon needs nothing else first; merch logos need the primary logo
# from step 1; the merch store needs those logo variants; Amazon
# Associates is easiest last since it wants an existing public presence).
SETUP_STEPS = ("logo", "email", "socials", "patreon", "merch_logo", "merch_store", "amazon")
# Order here is display order on the home page (top section to bottom).
# Only "archived" is ever actually stored - live/setup/future are
# computed by _section_for() from real state, never hand-set. See
# config/channels.py's DEFAULT_ARCHIVED.
CHANNEL_SECTIONS = ("live", "setup", "future", "archived")
PACING_INT_FIELDS = {"caption_max_group_size", "segment_count"}
STYLE_TEXT_FIELDS = ("base_color", "highlight_color", "stroke_color",
                      "outro_title_color", "outro_subtext_color")
STYLE_INT_FIELDS = ("font_size", "stroke_width")

app = Flask(__name__)


def _lines(text: str) -> list:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _affiliate_links_text(links: list) -> str:
    """The reverse of _parse_affiliate_links below — formats stored
    {"label", "url"} dicts back into the "Label | url" textarea lines a
    user would type, so re-opening the settings form shows what's saved."""
    lines = []
    for link in links or []:
        label = link.get("label")
        lines.append(f"{label} | {link['url']}" if label else link["url"])
    return "\n".join(lines)


def _parse_affiliate_links(text: str) -> list:
    links = []
    for line in _lines(text):
        if "|" in line:
            label, url = line.split("|", 1)
            links.append({"label": label.strip(), "url": url.strip()})
        else:
            links.append({"label": "", "url": line})
    return links


def _channel_or_404(key: str) -> dict:
    channels = channel_store.get_channels()
    if key not in channels:
        abort(404)
    return dict(channels[key], affiliate_links_text=_affiliate_links_text(channels[key]["monetization"]["affiliate_links"]))


def _parse_channel_form(form, key: str) -> dict:
    """Builds a complete channels.json entry from a submitted settings/
    new-channel form. Always writes the full field set (see
    channel_store.py's docstring on why that's an acceptable trade-off)."""
    content_mode = form.get("content_mode", "topic")
    entry = {
        "content_mode": content_mode,
        "voice": form.get("voice", "").strip(),
        "style_prompt": form.get("style_prompt", "").strip(),
        "channel_display_name": form.get("channel_display_name", "").strip(),
        "outro_subtext": form.get("outro_subtext", "").strip(),
        "output_dir": form.get("output_dir", f"output/{key}").strip(),
        "avoid_imagery": _lines(form.get("avoid_imagery", "")),
        "speed": float(form["speed"]) if form.get("speed") else channels_module.DEFAULT_SPEED,
    }
    if content_mode == "static_corpus":
        entry["source"] = form.get("source", "").strip()
    else:
        entry["topics"] = _lines(form.get("topics", ""))

    pacing = {}
    for field in channels_module.DEFAULT_PACING:
        raw = form.get(f"pacing_{field}")
        if raw is None or raw == "":
            continue
        pacing[field] = int(float(raw)) if field in PACING_INT_FIELDS else float(raw)
    entry["pacing"] = pacing

    style = {}
    for field in STYLE_TEXT_FIELDS:
        raw = form.get(f"style_{field}")
        if raw:
            style[field] = raw.strip()
    for field in STYLE_INT_FIELDS:
        raw = form.get(f"style_{field}")
        if raw not in (None, ""):
            style[field] = int(float(raw))
    bg_raw = form.get("style_outro_bg_color", "")
    if bg_raw.strip():
        style["outro_bg_color"] = [int(x.strip()) for x in bg_raw.split(",") if x.strip()]
    entry["style"] = style

    entry["socials"] = {
        "youtube_url": form.get("youtube_url", "").strip(),
        "tiktok_url": form.get("tiktok_url", "").strip(),
        "instagram_url": form.get("instagram_url", "").strip(),
    }
    entry["monetization"] = {
        "patreon_url": form.get("patreon_url", "").strip(),
        "merch_url": form.get("merch_url", "").strip(),
        "affiliate_links": _parse_affiliate_links(form.get("affiliate_links", "")),
    }
    entry["end_screen"] = {
        "enabled": form.get("end_screen_enabled") == "on",
        "duration_seconds": float(form.get("end_screen_duration_seconds") or 3.0),
        "ctas": {
            # Settings saves write the complete entry (channel_store.py),
            # not a sparse override — an empty string here would
            # permanently overwrite the default text rather than fall
            # back to it, since there's no later merge step that would
            # ever see "missing" instead of "blank". Resolve the default
            # right here instead.
            cta_key: {
                "enabled": form.get(f"cta_{cta_key}_enabled") == "on",
                "text": form.get(f"cta_{cta_key}_text", "").strip()
                        or channels_module.DEFAULT_END_SCREEN["ctas"][cta_key]["text"],
            }
            for cta_key in ("patreon", "merch", "affiliate")
        },
    }

    return entry


# Stable ids for every launch-checklist item, independent of label text -
# used both to key manual_checklist_overrides and to build the toggle
# route's URL. Order here IS checklist order (see _build_checklist).
CHECKLIST_ITEM_IDS = (
    "logo", "youtube", "tiktok", "instagram", "patreon",
    "merch_logo", "merch_store", "affiliate", "first_video",
)


def _build_checklist(key: str, channel: dict, has_logo: bool, has_merch_variants: bool, video_count: int) -> list:
    """The launch checklist's single source of truth — (id, label, done,
    manual, link-if-not-done), in the same order as SETUP_STEPS (logo ->
    socials -> monetization) plus "first video" at the end, outside the
    wizard entirely. Used by both index() (just the counts, for section
    placement) and channel_dashboard() (the full labeled list) so the two
    pages can never disagree about what's actually done. Every field read
    here is guaranteed present on the merged `channel` dict
    (config.channels._channel() always merges in the DEFAULT_* dicts), so
    no None-checks are needed.

    An item in channel["manual_checklist_overrides"] counts as done
    (manual=True) regardless of its real underlying condition — some
    steps (Patreon's signup flow, say) are annoying enough that "note I'm
    skipping this one" beats leaving it permanently red. "done" always
    reflects done-for-progress-purposes (real OR manual); "manual" is
    just which one it was, for the "-" vs checkmark distinction in the
    template."""
    socials = channel["socials"]
    monetization = channel["monetization"]
    overrides = set(channel["manual_checklist_overrides"])
    real = dict(zip(CHECKLIST_ITEM_IDS, [
        has_logo,
        bool(socials["youtube_url"]),
        bool(socials["tiktok_url"]),
        bool(socials["instagram_url"]),
        bool(monetization["patreon_url"]),
        has_merch_variants,
        bool(monetization["merch_url"]),
        bool(monetization["affiliate_links"]),
        video_count > 0,
    ]))
    labels = dict(zip(CHECKLIST_ITEM_IDS, [
        "Create a logo", "Add a YouTube link", "Add a TikTok link",
        "Add an Instagram link", "Add a Patreon link",
        "Generate merch-ready logo versions", "Add a merch storefront link",
        "Add affiliate links", "Create your first video",
    ]))
    links = dict(zip(CHECKLIST_ITEM_IDS, [
        url_for("logo_page", key=key),
        url_for("setup_step", key=key, step="socials"),
        url_for("setup_step", key=key, step="socials"),
        url_for("setup_step", key=key, step="socials"),
        url_for("setup_step", key=key, step="patreon"),
        url_for("setup_step", key=key, step="merch_logo"),
        url_for("setup_step", key=key, step="merch_store"),
        url_for("setup_step", key=key, step="amazon"),
        url_for("create_video", key=key),
    ]))
    return [
        {
            "id": item_id,
            "label": labels[item_id],
            "manual": item_id in overrides,
            "done": real[item_id] or item_id in overrides,
            "link": links[item_id],
            "toggle_link": url_for("toggle_checklist_manual", key=key, item_id=item_id),
        }
        for item_id in CHECKLIST_ITEM_IDS
    ]


def _section_for(channel: dict, checklist_remaining: int, checklist_total: int, published_count: int) -> str:
    """live/setup/future are COMPUTED, never hand-set — a channel belongs
    wherever its real state says it does. Only "archived" is an actual
    stored flag, and it always wins (a channel doesn't un-archive itself
    just because its checklist still happens to be complete)."""
    if channel["archived"]:
        return "archived"
    if checklist_remaining == 0 and published_count > 0:
        return "live"
    if checklist_remaining < checklist_total:
        return "setup"
    return "future"


def _channel_progress(key: str, channel: dict) -> dict:
    """One-stop computation of everything both index() and the
    generate-eligibility checks need for a single channel: real video/
    publish counts (one gallery.video_state_counts pass), checklist
    completeness, the computed section, and whether a job's currently
    running for it. index() and the quick-generate routes both call this
    rather than each recomputing "is this channel eligible" their own
    way, so they can never disagree about it."""
    has_logo = logo_gen.has_logo(key)
    has_merch_variants = logo_gen.has_merch_variants(key)
    state = gallery.video_state_counts(channel["output_dir"])
    checklist = _build_checklist(key, channel, has_logo, has_merch_variants, state["active"])
    checklist_remaining = sum(1 for item in checklist if not item["done"])
    section = _section_for(channel, checklist_remaining, len(checklist), state["published"])
    active_job = jobs.get_running_job_for_channel(key)
    return {
        "video_count": state["active"],
        "published_count": state["published"],
        "unpublished_count": state["unpublished"],
        "discarded_count": state["discarded"],
        "checklist": checklist,
        "checklist_remaining": checklist_remaining,
        "section": section,
        "active_job": active_job,
        "can_generate": section == "live" and state["unpublished"] == 0 and active_job is None,
    }


@app.route("/")
def index():
    channels = channel_store.get_channels()
    has_logo = {key: logo_gen.has_logo(key) for key in channels}

    sections = {s: {} for s in CHANNEL_SECTIONS}
    progress = {}
    for key, ch in channels.items():
        prog = _channel_progress(key, ch)
        last_published = gallery.latest_published_at(ch["output_dir"])
        progress[key] = {
            **prog,
            "last_published_label": datetime.fromtimestamp(last_published).strftime("%b %d, %Y") if last_published else None,
        }
        sections[prog["section"]][key] = ch

    return render_template(
        "index.html", channels=channels, has_logo=has_logo, progress=progress,
        sections=sections, statuses=CHANNEL_SECTIONS,
        deleted_key=request.args.get("deleted"), backup_path=request.args.get("backup"),
    )


@app.route("/channels/<key>")
def channel_dashboard(key):
    channel = dict(_channel_or_404(key), key=key)
    socials = channel["socials"]
    monetization = channel["monetization"]

    prog = _channel_progress(key, channel)
    latest_mtime = gallery.latest_video_mtime(channel["output_dir"])
    last_video_at = datetime.fromtimestamp(latest_mtime).strftime("%b %d, %Y") if latest_mtime else None

    has_logo = logo_gen.has_logo(key)
    checklist = prog["checklist"]
    checklist_remaining = prog["checklist_remaining"]
    # Nothing to click once checklist_remaining hits 0 - going live now
    # just happens the moment a video is published (see _section_for), so
    # this is purely informational, not a call to action.
    ready_to_publish = checklist_remaining == 0 and prog["section"] != "live"

    social_links = [
        {"label": "YouTube", "url": socials["youtube_url"]},
        {"label": "TikTok", "url": socials["tiktok_url"]},
        {"label": "Instagram", "url": socials["instagram_url"]},
    ]
    social_links = [link for link in social_links if link["url"]]

    monetization_links = [
        {"label": "Patreon", "url": monetization["patreon_url"]},
        {"label": "Merch store", "url": monetization["merch_url"]},
    ]
    monetization_links = [link for link in monetization_links if link["url"]]
    monetization_links += [
        {"label": link.get("label") or "Affiliate link", "url": link["url"]}
        for link in monetization["affiliate_links"]
    ]

    return render_template(
        "channel_dashboard.html", key=key, channel=channel,
        video_count=prog["video_count"], last_video_at=last_video_at,
        checklist=checklist, checklist_remaining=checklist_remaining,
        ready_to_publish=ready_to_publish,
        social_links=social_links, monetization_links=monetization_links,
        has_logo=has_logo, rename_error=request.args.get("rename_error"),
    )


@app.route("/channels/<key>/rename", methods=["POST"])
def rename_channel_route(key):
    _channel_or_404(key)
    new_name = request.form.get("new_name", "").strip()
    try:
        result = channel_store.rename_channel(key, new_name)
    except ValueError as e:
        return redirect(url_for("channel_dashboard", key=key, rename_error=str(e)))
    return redirect(url_for("channel_dashboard", key=result["new_key"]))


@app.route("/channels/<key>/checklist/<item_id>/toggle-manual", methods=["POST"])
def toggle_checklist_manual(key, item_id):
    _channel_or_404(key)
    if item_id not in CHECKLIST_ITEM_IDS:
        abort(404)
    raw = channel_store.get_raw_entries()
    raw_entry = raw[key]
    overrides = set(raw_entry.get("manual_checklist_overrides") or [])
    if item_id in overrides:
        overrides.discard(item_id)
    else:
        overrides.add(item_id)
    raw_entry["manual_checklist_overrides"] = sorted(overrides)
    channel_store.save_channel(key, raw_entry)
    return redirect(url_for("channel_dashboard", key=key))


@app.route("/channels/<key>/archive", methods=["POST"])
def archive_channel_route(key):
    _channel_or_404(key)
    raw = channel_store.get_raw_entries()
    raw_entry = raw[key]
    raw_entry["archived"] = True
    channel_store.save_channel(key, raw_entry)
    return redirect(url_for("channel_settings", key=key))


@app.route("/channels/<key>/unarchive", methods=["POST"])
def unarchive_channel_route(key):
    _channel_or_404(key)
    raw = channel_store.get_raw_entries()
    raw_entry = raw[key]
    raw_entry["archived"] = False
    channel_store.save_channel(key, raw_entry)
    return redirect(url_for("channel_settings", key=key))


@app.route("/channels/<key>/delete", methods=["GET"])
def delete_channel_confirm(key):
    channel = dict(_channel_or_404(key), key=key)
    video_count = gallery.count_videos(channel["output_dir"])
    return render_template("delete_channel_confirm.html", key=key, channel=channel, video_count=video_count)


@app.route("/channels/<key>/delete", methods=["POST"])
def delete_channel_route(key):
    _channel_or_404(key)
    if request.form.get("confirm_key") != key:
        abort(400)
    zip_path = channel_store.delete_channel(key)
    backup_rel = str(zip_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    return redirect(url_for("index", deleted=key, backup=backup_rel))


@app.route("/api/channels/reorder", methods=["POST"])
def api_reorder_channels():
    data = request.get_json(force=True, silent=True) or {}
    keys = data.get("keys")
    if not isinstance(keys, list) or not keys:
        return jsonify({"error": "Missing keys"}), 400
    channel_store.reorder_channels(keys)
    return jsonify({"ok": True})


@app.route("/channels/<key>/settings", methods=["GET", "POST"])
def channel_settings(key):
    channel = _channel_or_404(key)
    if request.method == "POST":
        entry = _parse_channel_form(request.form, key)
        channel_store.save_channel(key, entry)
        return redirect(url_for("channel_settings", key=key))
    channel = dict(channel, key=key)
    return render_template("channel_settings.html", channel=channel, sources=list(SOURCES.keys()))


@app.route("/channels/new", methods=["GET", "POST"])
def new_channel():
    default_channel = {
        "key": "", "content_mode": "topic", "voice": "", "style_prompt": "",
        "channel_display_name": "", "outro_subtext": "Subscribe for more",
        "output_dir": "", "avoid_imagery": [], "topics": [], "source": "",
        "pacing": channels_module.DEFAULT_PACING,
        "style": channels_module.DEFAULT_STYLE,
        "speed": channels_module.DEFAULT_SPEED,
        "socials": channels_module.DEFAULT_SOCIALS,
        "monetization": channels_module.DEFAULT_MONETIZATION,
        "end_screen": channels_module.DEFAULT_END_SCREEN,
        "affiliate_links_text": "",
    }
    if request.method == "POST":
        key = request.form.get("key", "").strip()
        error = None
        if not key or not channel_store.KEY_RE.match(key):
            error = "Channel key must be lowercase letters, numbers, and underscores only."
        elif key in channel_store.get_raw_entries():
            error = f'Channel "{key}" already exists.'
        if error:
            return render_template("new_channel.html", channel={**default_channel, **request.form, "key": key},
                                    sources=list(SOURCES.keys()), error=error), 400

        entry = _parse_channel_form(request.form, key)
        channel_store.save_channel(key, entry)
        (PROJECT_ROOT / entry["output_dir"]).mkdir(parents=True, exist_ok=True)
        return redirect(url_for("index"))

    return render_template("new_channel.html", channel=default_channel, sources=list(SOURCES.keys()))


@app.route("/channels/<key>/create")
def create_video(key):
    channel = _channel_or_404(key)
    return render_template("create_video.html", key=key, channel=channel)


# --- Logo generation ---

@app.route("/channels/<key>/logo")
def logo_page(key):
    channel = _channel_or_404(key)
    candidates = sorted(logo_gen._candidates_dir(key).glob("*.png")) if logo_gen._candidates_dir(key).exists() else []
    return render_template(
        "logo_gen.html", key=key, channel=channel,
        has_logo=logo_gen.has_logo(key),
        has_merch_variants=logo_gen.has_merch_variants(key),
        candidates=[c.name for c in candidates],
        variant_styles=logo_gen.VARIANT_STYLES,
        candidate_count=logo_gen.CANDIDATE_COUNT,
    )


@app.route("/api/channels/<key>/logo/generate", methods=["POST"])
def api_logo_generate(key):
    _channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    fragment = (data.get("fragment") or "").strip()
    if not fragment:
        return jsonify({"error": "Describe what the channel is about first."}), 400
    try:
        paths = logo_gen.generate_candidates(key, fragment)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({
        "candidates": [
            {"filename": p.name, "url": url_for("serve_logo_asset", key=key, filename=f"candidates/{p.name}")}
            for p in paths
        ],
    })


@app.route("/api/channels/<key>/logo/select", methods=["POST"])
def api_logo_select(key):
    _channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "Missing filename"}), 400

    candidate_path = (logo_gen._candidates_dir(key) / filename).resolve()
    if logo_gen._candidates_dir(key).resolve() not in candidate_path.parents or not candidate_path.exists():
        return jsonify({"error": "Unknown candidate"}), 400

    try:
        logo_gen.select_logo(key, candidate_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "redirect": url_for("logo_page", key=key)})


@app.route("/api/channels/<key>/logo/variants/generate", methods=["POST"])
def api_logo_variants_generate(key):
    _channel_or_404(key)
    try:
        variant_paths = logo_gen.generate_merch_variants(key)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    labels = {s["key"]: s["label"] for s in logo_gen.VARIANT_STYLES}
    labels["monochrome"] = "Monochrome (single-color print)"
    return jsonify({
        "variants": [
            {"key": vkey, "label": labels.get(vkey, vkey),
             "url": url_for("serve_logo_asset", key=key, filename=path.name)}
            for vkey, path in variant_paths.items()
        ],
    })


@app.route("/channels/<key>/logo-assets/<path:filename>")
def serve_logo_asset(key, filename):
    logo_dir = logo_gen._logo_dir(key).resolve()
    target = (logo_dir / filename).resolve()
    if logo_dir not in target.parents:
        abort(403)
    return send_from_directory(logo_dir, filename)


# --- Channel setup wizard (socials, then monetization) ---

@app.route("/channels/<key>/setup/<step>", methods=["GET", "POST"])
def setup_step(key, step):
    if step not in SETUP_STEPS:
        abort(404)
    channel = _channel_or_404(key)
    step_index = SETUP_STEPS.index(step)
    prev_step = SETUP_STEPS[step_index - 1] if step_index > 0 else None
    next_step = SETUP_STEPS[step_index + 1] if step_index < len(SETUP_STEPS) - 1 else None

    if request.method == "POST":
        # Update the RAW stored entry (not the DEFAULT_*-merged `channel`
        # dict) so this only ever touches "socials"/"monetization" —
        # merging onto an already-merged dict and saving it back would
        # re-apply config.channels._channel()'s list-concatenating
        # defaults (e.g. avoid_imagery) a second time on next load. See
        # channel_store.py.
        raw = channel_store.get_raw_entries()
        raw_entry = raw[key]
        if step == "socials":
            socials = dict(raw_entry.get("socials") or channels_module.DEFAULT_SOCIALS)
            socials["youtube_url"] = request.form.get("youtube_url", "").strip()
            socials["tiktok_url"] = request.form.get("tiktok_url", "").strip()
            socials["instagram_url"] = request.form.get("instagram_url", "").strip()
            raw_entry["socials"] = socials
        elif step in ("patreon", "merch_store", "amazon"):
            monetization = dict(raw_entry.get("monetization") or channels_module.DEFAULT_MONETIZATION)
            if step == "patreon":
                monetization["patreon_url"] = request.form.get("patreon_url", "").strip()
            elif step == "merch_store":
                monetization["merch_url"] = request.form.get("merch_url", "").strip()
                for file_storage in request.files.getlist("merch_photos"):
                    if file_storage and file_storage.filename:
                        try:
                            merch_assets.save_merch_upload(key, file_storage)
                        except ValueError:
                            pass  # unsupported file type — silently skip rather than fail the whole save
            elif step == "amazon":
                monetization["affiliate_links"] = _parse_affiliate_links(request.form.get("affiliate_links", ""))
            raw_entry["monetization"] = monetization
        # "logo", "email", "merch_logo" have nothing to save - their own
        # pages/API calls handle everything, this step is just a guided
        # checkpoint in the sequence.

        channel_store.save_channel(key, raw_entry)
        if next_step:
            return redirect(url_for("setup_step", key=key, step=next_step))
        return redirect(url_for("channel_dashboard", key=key))

    channel = dict(channel, key=key)
    return render_template(
        f"setup_{step}.html",
        key=key, channel=channel, step=step, steps=SETUP_STEPS,
        step_index=step_index, step_count=len(SETUP_STEPS),
        prev_step=prev_step, next_step=next_step,
        merch_photos=[p.name for p in merch_assets.list_merch_photos(key)],
        has_logo=logo_gen.has_logo(key),
        has_merch_variants=logo_gen.has_merch_variants(key),
        variant_styles=logo_gen.VARIANT_STYLES,
    )


@app.route("/channels/<key>/merch/delete", methods=["POST"])
def merch_delete(key):
    _channel_or_404(key)
    filename = request.form.get("filename", "")
    merch_assets.delete_merch_photo(key, filename)
    return redirect(url_for("setup_step", key=key, step="merch_store"))


@app.route("/channels/<key>/merch-assets/<path:filename>")
def serve_merch_asset(key, filename):
    merch_dir = merch_assets.merch_dir(key).resolve()
    target = (merch_dir / filename).resolve()
    if merch_dir not in target.parents:
        abort(403)
    return send_from_directory(merch_dir, filename)


def _video_title(filename: str) -> str:
    """Filenames are already sensible slugs (main.py's _title_for_seed/
    _unique_stem) - just swap separators for spaces, no separate title
    field needed."""
    return Path(filename).stem.replace("_", " ").replace("-", " ")


@app.route("/channels/<key>/gallery")
def channel_gallery(key):
    channel = _channel_or_404(key)
    videos = gallery.list_videos(channel["output_dir"])
    for v in videos:
        v["title"] = _video_title(v["name"])
        if v["published"] and v["links"]["published_at"]:
            published_dt = datetime.fromisoformat(v["links"]["published_at"])
            v["date_label"] = f"Published {published_dt.strftime('%b %d, %Y')}"
        else:
            v["date_label"] = f"Created {datetime.fromtimestamp(v['mtime']).strftime('%b %d, %Y')}"
    active = [v for v in videos if not v["discarded"]]
    discarded = [v for v in videos if v["discarded"]]
    unpublished = [v for v in active if not v["published"]]
    published = [v for v in active if v["published"]]
    return render_template(
        "gallery.html", key=key, channel=channel,
        unpublished=unpublished, published=published, discarded=discarded,
    )


@app.route("/channels/<key>/videos/<path:relpath>/thumbnail")
def serve_video_thumbnail(key, relpath):
    _channel_or_404(key)
    target = (OUTPUT_ROOT / relpath).resolve()
    if OUTPUT_ROOT not in target.parents or not target.exists():
        abort(404)
    thumb_path = gallery.get_or_create_thumbnail(target)
    return send_from_directory(thumb_path.parent, thumb_path.name)


@app.route("/channels/<key>/videos/<path:relpath>", methods=["GET", "POST"])
def video_detail(key, relpath):
    channel = _channel_or_404(key)
    target = (OUTPUT_ROOT / relpath).resolve()
    if OUTPUT_ROOT not in target.parents or not target.exists():
        abort(404)

    if request.method == "POST":
        links = {field: request.form.get(field, "") for field in gallery.PUBLISH_LINK_FIELDS}
        gallery.save_publish_info(target, links)
        return redirect(url_for("video_detail", key=key, relpath=relpath))

    links = gallery.load_publish_info(target)
    meta_path = target.with_name(f"{target.stem}_meta.txt")
    meta_text = gallery.read_meta_text(meta_path) if meta_path.exists() else None
    created_label = datetime.fromtimestamp(target.stat().st_mtime).strftime("%b %d, %Y")
    published_label = None
    if links["published_at"]:
        published_label = datetime.fromisoformat(links["published_at"]).strftime("%b %d, %Y")

    return render_template(
        "video_detail.html", key=key, channel=channel, relpath=relpath,
        name=target.name, title=_video_title(target.name), links=links,
        published=gallery.is_published(links), discarded=links["discarded"],
        created_label=created_label, published_label=published_label,
        meta_text=meta_text,
    )


@app.route("/api/channels/<key>/seed", methods=["POST"])
def api_seed(key):
    channel = _channel_or_404(key)
    try:
        seed = main_module.fetch_candidate_seed(channel)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"seed": seed})


@app.route("/api/channels/<key>/generate", methods=["POST"])
def api_generate(key):
    _channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    seed = data.get("seed")
    if not seed:
        return jsonify({"error": "Missing seed"}), 400
    try:
        job_id = jobs.start_job(key, seed)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"job_id": job_id})


@app.route("/channels/<key>/generate-now", methods=["POST"])
def generate_now(key):
    """The home page's one-click 'Generate video' — fetches a seed AND
    starts the job in one call, deliberately skipping create_video.html's
    manual seed-preview step. That review step is genuinely useful when
    you're sitting there watching, but this button exists specifically
    for "trigger it and walk away" - reviewing a seed you won't look at
    for another 10 minutes anyway doesn't add anything."""
    channel = _channel_or_404(key)
    try:
        seed = main_module.fetch_candidate_seed(channel)
        job_id = jobs.start_job(key, seed)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"job_id": job_id})


@app.route("/api/channels/generate-all", methods=["POST"])
def api_generate_all():
    """Runs generate_now's fetch-seed-and-start logic for every channel
    _channel_progress finds eligible (live, nothing unpublished, no job
    already running) - the exact same check the home page used to decide
    whether to show each channel's own Generate button, so this can never
    start a job somewhere the individual button wouldn't have allowed."""
    channels = channel_store.get_channels()
    started, skipped = [], []
    for key, ch in channels.items():
        prog = _channel_progress(key, ch)
        if not prog["can_generate"]:
            skipped.append({"key": key, "reason": "not eligible"})
            continue
        try:
            seed = main_module.fetch_candidate_seed(ch)
            jobs.start_job(key, seed)
            started.append(key)
        except Exception as e:
            skipped.append({"key": key, "reason": str(e)})
    return jsonify({"started": started, "skipped": skipped})


@app.route("/api/channels/<key>/current-job")
def api_current_job(key):
    """Lets a page discover an already-in-flight job for this channel on
    load (create_video.html resuming its progress view after you navigate
    away and back; the home page's per-card progress bar after a reload)
    without needing to already know the job's id."""
    _channel_or_404(key)
    return jsonify({"job": jobs.get_running_job_for_channel(key)})


@app.route("/api/channels/<key>/last-failed-job")
def api_last_failed_job(key):
    """Lets create_video.html proactively show "your last attempt was
    interrupted/failed while X — retry?" on load, when there's no active
    job for this channel. Nothing else exposes a job id, so without this
    an interrupted job would be invisible until you knew to look for it."""
    _channel_or_404(key)
    return jsonify({"job": jobs.get_latest_terminal_job_for_channel(key)})


@app.route("/api/jobs/<job_id>/retry", methods=["POST"])
def api_retry_job(job_id):
    try:
        jobs.retry_job(job_id)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"job_id": job_id})


@app.route("/channels/<key>/videos/discard", methods=["POST"])
def discard_videos_route(key):
    """Bulk discard - the multi-select flow on the gallery's Unpublished
    section posts here with one or more relpaths, covering both 'discard
    this one bad take' (a single-item selection) and true bulk discarding
    with the same mechanism, so there's no separate single-video discard
    route to keep in sync with this one."""
    _channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    relpaths = data.get("relpaths")
    if not isinstance(relpaths, list) or not relpaths:
        return jsonify({"error": "Missing relpaths"}), 400
    discarded = []
    for relpath in relpaths:
        target = (OUTPUT_ROOT / relpath).resolve()
        if OUTPUT_ROOT not in target.parents or not target.exists():
            continue
        gallery.set_discarded(target, True)
        discarded.append(relpath)
    return jsonify({"discarded": discarded})


@app.route("/channels/<key>/videos/<path:relpath>/restore", methods=["POST"])
def restore_video_route(key, relpath):
    _channel_or_404(key)
    target = (OUTPUT_ROOT / relpath).resolve()
    if OUTPUT_ROOT not in target.parents or not target.exists():
        abort(404)
    gallery.set_discarded(target, False)
    return redirect(url_for("channel_gallery", key=key))


@app.route("/api/jobs/<job_id>")
def api_job(job_id):
    job = jobs.get_job(job_id)
    if job is None:
        abort(404)
    result_path_rel = None
    if job["result_path"]:
        result_path_rel = str(Path(job["result_path"]).resolve().relative_to(OUTPUT_ROOT)).replace("\\", "/")
    return jsonify({**job, "result_path_rel": result_path_rel})


@app.route("/videos/<path:relpath>")
def serve_video(relpath):
    target = (OUTPUT_ROOT / relpath).resolve()
    if OUTPUT_ROOT != target and OUTPUT_ROOT not in target.parents:
        abort(403)
    return send_from_directory(OUTPUT_ROOT, relpath)


@app.route("/voice-lab")
def voice_lab_page():
    error = None
    try:
        voices = voice_lab.get_cached_voices()
    except Exception as e:
        voices, error = [], str(e)
    return render_template(
        "voice_lab.html", voices=voices, presets=voice_lab.CADENCE_PRESETS, error=error,
    )


@app.route("/api/voice-lab/refresh-voices", methods=["POST"])
def api_refresh_voices():
    try:
        voices = voice_lab.refresh_voices()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"voices": voices})


@app.route("/api/voice-lab/test", methods=["POST"])
def api_voice_lab_test():
    data = request.get_json(force=True, silent=True) or {}
    voice_id = data.get("voice_id")
    preset = data.get("preset")
    try:
        speed = float(data.get("speed", 1.0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid speed"}), 400
    if not voice_id or not preset:
        return jsonify({"error": "Missing voice_id or preset"}), 400
    try:
        sample_path = voice_lab.get_or_create_snippet(voice_id, preset, speed)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"sample_url": url_for("serve_voice_lab_sample", filename=sample_path.name)})


@app.route("/voice-lab/samples/<path:filename>")
def serve_voice_lab_sample(filename):
    target = (voice_lab.SAMPLES_DIR / filename).resolve()
    if voice_lab.SAMPLES_DIR.resolve() not in target.parents:
        abort(403)
    return send_from_directory(voice_lab.SAMPLES_DIR, filename)


if __name__ == "__main__":
    jobs.load_persisted_jobs()
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False, threaded=True)
