"""
Animated scenes' settings: the art direction preview, and saving a
channel's look and how much of each video is animated.

The same form (templates/_scene_settings.html) appears on the draft
channel page and on each channel's dashboard. See decision 035.
"""

from __future__ import annotations

from flask import Blueprint, request, send_file, url_for

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR
from pipeline.scenes import art

log = get_logger(__name__)

bp = Blueprint("scenes", __name__)

PREVIEW_DIR = CACHE_DIR / "art_previews"
FIELDS = ("preset", "background", "pattern", "pattern_color", *art.COLOR_KEYS,
          "font_display", "font_text", "stroke_width", "prop_style")


def art_from(values) -> dict:
    """The art settings in a form or query string (fields named art_*)."""
    return art.sparse({f: values.get(f"art_{f}") for f in FIELDS if values.get(f"art_{f}")})


def form_context(settings: dict, share: int) -> dict:
    """What _scene_settings.html needs."""
    return {
        "scene_art": art.editable(settings),
        "scene_preview_url": url_for("scenes.preview", **{f"art_{k}": v for k, v in
                                                          art.clean(settings).items()}),
        "scene_share": share,
        "scene_presets": {k: art.editable({"preset": k}) | {"label": p["label"],
                                                            "description": p["description"]}
                          for k, p in art.presets().items()},
        "scene_fonts": art.FONTS,
        "scene_patterns": art.PATTERNS,
        "scene_color_labels": {"background": "Background", "ink": "Lines and text",
                               "ink_soft": "Soft text", "label_fill": "Label fill",
                               "accent1": "Accent 1", "accent2": "Accent 2",
                               "accent3": "Accent 3", "accent4": "Accent 4",
                               "accent5": "Accent 5", "pattern_color": "Pattern"},
    }


@bp.route("/scenes/art-preview.jpg")
def preview():
    """A still in the art direction given by the query string. Cached by
    content, so each look renders once (about two seconds)."""
    try:
        path = art.preview(art_from(request.args), PREVIEW_DIR)
    except PipelineError as exc:
        log.warning(f"art preview failed: {exc}")
        return exc.user_message, 503
    return send_file(path, mimetype="image/jpeg", max_age=86400)


@bp.route("/scenes/template-sheet.jpg")
def template_sheet():
    """Every motion-graphics template in the look given by the query
    string, as one sheet. Filmed once per look (about 20 seconds)."""
    from pipeline.templates import gallery
    style = art.resolve(art_from(request.args))
    try:
        path = gallery.sheet(style, PREVIEW_DIR, CACHE_DIR / "template_icons" / style["key"])
    except PipelineError as exc:
        return exc.user_message, 503
    return send_file(path, mimetype="image/jpeg", max_age=86400)
