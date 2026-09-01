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
# "socials" first — a channel's social profile links are the natural first
# thing to set up, before monetization accounts that often depend on the
# channel already existing somewhere public.
SETUP_STEPS = ("socials", "email", "patreon", "merch", "amazon")
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


@app.route("/")
def index():
    channels = channel_store.get_channels()
    video_counts = {key: gallery.count_videos(ch["output_dir"]) for key, ch in channels.items()}
    has_logo = {key: logo_gen.has_logo(key) for key in channels}
    return render_template("index.html", channels=channels, video_counts=video_counts, has_logo=has_logo)


@app.route("/channels/<key>")
def channel_dashboard(key):
    channel = dict(_channel_or_404(key), key=key)
    socials = channel["socials"]
    monetization = channel["monetization"]

    video_count = gallery.count_videos(channel["output_dir"])
    latest_mtime = gallery.latest_video_mtime(channel["output_dir"])
    last_video_at = datetime.fromtimestamp(latest_mtime).strftime("%b %d, %Y") if latest_mtime else None

    has_logo = logo_gen.has_logo(key)
    has_merch_variants = logo_gen.has_merch_variants(key)

    # (label, done, link-if-not-done) - what's left to do for this channel.
    # Every field read here is guaranteed present on the merged `channel`
    # dict (config.channels._channel() always merges in the DEFAULT_*
    # dicts), so no None-checks are needed.
    checklist = [
        {"label": "Create a logo", "done": has_logo,
         "link": url_for("logo_page", key=key)},
        {"label": "Generate merch-ready logo versions", "done": has_merch_variants,
         "link": url_for("setup_step", key=key, step="merch")},
        {"label": "Add a YouTube link", "done": bool(socials["youtube_url"]),
         "link": url_for("setup_step", key=key, step="socials")},
        {"label": "Add a TikTok link", "done": bool(socials["tiktok_url"]),
         "link": url_for("setup_step", key=key, step="socials")},
        {"label": "Add an Instagram link", "done": bool(socials["instagram_url"]),
         "link": url_for("setup_step", key=key, step="socials")},
        {"label": "Add a Patreon link", "done": bool(monetization["patreon_url"]),
         "link": url_for("setup_step", key=key, step="patreon")},
        {"label": "Add a merch storefront link", "done": bool(monetization["merch_url"]),
         "link": url_for("setup_step", key=key, step="merch")},
        {"label": "Add affiliate links", "done": bool(monetization["affiliate_links"]),
         "link": url_for("setup_step", key=key, step="amazon")},
        {"label": "Create your first video", "done": video_count > 0,
         "link": url_for("create_video", key=key)},
    ]

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
        video_count=video_count, last_video_at=last_video_at,
        checklist=checklist, social_links=social_links, monetization_links=monetization_links,
        has_logo=has_logo, rename_error=request.args.get("rename_error"),
    )


@app.route("/channels/<key>/rename", methods=["POST"])
def rename_channel_route(key):
    _channel_or_404(key)
    new_key = request.form.get("new_key", "").strip()
    try:
        result = channel_store.rename_channel(key, new_key)
    except ValueError as e:
        return redirect(url_for("channel_dashboard", key=key, rename_error=str(e)))
    return redirect(url_for("channel_dashboard", key=result["new_key"]))


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
        else:
            monetization = dict(raw_entry.get("monetization") or channels_module.DEFAULT_MONETIZATION)
            if step == "patreon":
                monetization["patreon_url"] = request.form.get("patreon_url", "").strip()
            elif step == "merch":
                monetization["merch_url"] = request.form.get("merch_url", "").strip()
                for file_storage in request.files.getlist("merch_photos"):
                    if file_storage and file_storage.filename:
                        try:
                            merch_assets.save_merch_upload(key, file_storage)
                        except ValueError:
                            pass  # unsupported file type — silently skip rather than fail the whole save
            elif step == "amazon":
                monetization["affiliate_links"] = _parse_affiliate_links(request.form.get("affiliate_links", ""))
            # "email" has no field to save
            raw_entry["monetization"] = monetization

        channel_store.save_channel(key, raw_entry)
        if next_step:
            return redirect(url_for("setup_step", key=key, step=next_step))
        return redirect(url_for("channel_dashboard", key=key))

    channel = dict(channel, key=key)
    return render_template(
        f"setup_{step}.html" if step == "socials" else f"monetize_{step}.html",
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
    return redirect(url_for("setup_step", key=key, step="merch"))


@app.route("/channels/<key>/merch-assets/<path:filename>")
def serve_merch_asset(key, filename):
    merch_dir = merch_assets.merch_dir(key).resolve()
    target = (merch_dir / filename).resolve()
    if merch_dir not in target.parents:
        abort(403)
    return send_from_directory(merch_dir, filename)


@app.route("/channels/<key>/gallery")
def channel_gallery(key):
    channel = _channel_or_404(key)
    videos = gallery.list_videos(channel["output_dir"])
    return render_template("gallery.html", key=key, channel=channel, videos=videos)


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
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False, threaded=True)
