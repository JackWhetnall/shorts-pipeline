"""
Thumbnail variants for testing (decision 083).

A thumbnail is drawn from a recipe: a few settings, each a single thing
that can be changed and tested on its own.
- `text_scale`: how big the headline is (the hook on a short, "60
  Questions" on a long quiz).
- `accent`: the colour of the stamp (short) or the big mark and badge
  (long): one of the look's accents, or its ink.
- `background`: the look's own, dark (its ink), or an accent.
- `tilt`: how far the stamp (short) or mark (long) leans, in degrees.

The default recipe adds nothing, so variant A of a short is its opening
screen exactly as the video shows it. Each variant is rendered as a page,
not cut from the video, so B and C can differ from A in one setting each.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger(__name__)

PARAMS = {
    # name: (default, options or (low, high), step for a number)
    "text_scale": (1.0, (0.7, 1.4), 0.15),
    "accent": ("a1", ("a1", "a2", "a3", "a4", "ink"), None),
    "background": ("plain", ("plain", "dark", "accent"), None),
    "tilt": (-6.0, (-14.0, 0.0), 4.0),
}
DEFAULT = {name: spec[0] for name, spec in PARAMS.items()}
SHORT_SIZE = (1080, 1920)


def _override_css(recipe: dict, kind: str) -> str:
    """CSS for what differs from the default recipe ("" for the default)."""
    r = {**DEFAULT, **(recipe or {})}
    css = []
    accent = r["accent"]
    colour, on = (f"var(--{accent})", f"var(--on-{accent})") if accent != "ink" else ("var(--ink)", "var(--bg)")
    if kind == "short":
        if r["text_scale"] != DEFAULT["text_scale"]:
            css.append(f".hook-words span {{ font-size: {124 * r['text_scale']:.0f}px; }}")
        if accent != DEFAULT["accent"]:
            css.append(f".stamp {{ background: {colour}; color: {on}; }}")
        if r["tilt"] != DEFAULT["tilt"]:
            css.append(f".stamp {{ transform: rotate({r['tilt']:.0f}deg); }}")
        if r["background"] == "dark":
            css.append(".hook-screen { background: var(--ink); } .hook-words span { color: var(--bg); }"
                       " .stamp { border-color: var(--bg); }")
        elif r["background"] == "accent":
            css.append(".hook-screen { background: var(--a2); } .hook-words span { color: var(--on-a2); }")
    else:
        if r["text_scale"] != DEFAULT["text_scale"]:
            css.append(f".t .head {{ font-size: {150 * r['text_scale']:.0f}px; }}")
        if accent != DEFAULT["accent"]:
            css.append(f".mark {{ color: {colour}; }} .badge {{ background: {colour}; color: {on}; }}")
        if r["tilt"] != DEFAULT["tilt"]:
            css.append(f".mark {{ transform: rotate({r['tilt'] + 6:.0f}deg); }}")
        if r["background"] == "dark":
            css.append(".bg { background: var(--ink); } .t .head, .t .sub, .t .line { color: var(--bg); }")
        elif r["background"] == "accent":
            css.append(".bg { background: var(--a2); } .t .head { color: var(--on-a2); } .t .sub { color: var(--on-a2); }")
    return "".join(css)


def short_html(hook: str, category: str, difficulty: str, style: dict, recipe: dict = None) -> str:
    """A quiz short's opening screen, stamp landed, as a still page."""
    from pipeline import quiz
    from pipeline.templates import page, theme
    esc = html.escape
    words = "".join(f"<span>{esc(w)}</span>" for w in hook.split())
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"{theme.css(style)}{quiz.BOARD_CSS}.bg-grain {{ background-image: url({page.GRAIN}); }}"
        f"{_override_css(recipe, 'short')}"
        "</style></head><body><div class='bg'><div class='bg-pattern'></div><div class='bg-grain'></div>"
        "<div class='bg-vignette'></div></div>"
        f"<div class='hook-screen'><div class='hook-words'>{words}</div>"
        f"<div class='stamp-wrap'><div class='stamp'><div class='scat' data-fit='30'>{esc(category)}</div>"
        f"<div class='slvl'>{esc(difficulty)}</div></div></div></div>"
        "<script>window.TEMPLATE_DURATION = 1;</script>"
        f"<script>{page.RUNTIME.read_text(encoding='utf-8')}</script></body></html>")


def short_inputs(video_path) -> dict:
    """What a quiz short's opening screen shows, from what's kept beside it."""
    video_path = Path(video_path)
    sidecar = json.loads(video_path.with_name(f"{video_path.stem}_quiz.json").read_text(encoding="utf-8"))
    hook = ""
    script = video_path.with_name(f"{video_path.stem}_script.json")
    if script.exists():
        hook = (json.loads(script.read_text(encoding="utf-8")).get("quiz") or {}).get("hook", "")
    return {"hook": hook or f"{sidecar.get('category', 'Quiz')}: how many can you get?",
            "category": sidecar.get("category", ""), "difficulty": sidecar.get("difficulty", "")}


def render_short(channel, video_path, recipe: dict, out: Path) -> Path:
    from pipeline.scenes import art, render
    inputs = short_inputs(video_path)
    page = short_html(inputs["hook"], inputs["category"], inputs["difficulty"],
                      art.resolve(channel.scenes.art), recipe)
    render.page_frame(page, 0.0, out, size=SHORT_SIZE)
    return Path(out)


def long_inputs(channel, video_path) -> dict:
    """A long quiz's thumbnail words, rebuilt from its sidecar and rounds."""
    from core import gallery
    from pipeline import longform, quiz
    video_path = Path(video_path)
    data = json.loads(quiz.round_sidecar(video_path).read_text(encoding="utf-8"))
    by_stem = {v.stem: v for v in gallery.videos_in(gallery.resolve_output_dir(channel.output_dir), long=False)}
    rounds = []
    for stem in data.get("rounds") or []:
        side = by_stem.get(stem)
        if side and quiz.round_sidecar(side).exists():
            r = json.loads(quiz.round_sidecar(side).read_text(encoding="utf-8"))
            rounds.append({"category": r.get("category", ""), "difficulty": r.get("difficulty", "")})
    count = len(rounds) or len(data.get("rounds") or [])
    single = bool(data.get("category"))
    if single:
        sub = f"{data['category']}: {rounds[0]['difficulty']} to {rounds[-1]['difficulty']}" if rounds else data["category"]
        chips = [r["difficulty"] for r in rounds]
    else:
        sub = f"{data.get('difficulty', '')} pub quiz"
        chips = [r["category"] for r in rounds]
    badge = data.get("label", "") + (" · Answers at the end" if data.get("variant") == "at_end" else " · Answers as you go")
    return {"headline": f"{count * channel.quiz.questions} Questions", "subtitle": sub, "line": "",
            "chips": chips, "badge": badge}


def render_long(channel, video_path, recipe: dict, out: Path) -> Path:
    from pipeline import longform
    from pipeline.documentary import thumbs
    from pipeline.scenes import art, render
    if thumbs.is_documentary(video_path):       # decision 086: its own designed thumbnail
        return thumbs.render_variant(channel, video_path, recipe, out)
    i = long_inputs(channel, video_path)
    page = longform.thumbnail_html(art.resolve(channel.scenes.art), i["headline"], i["subtitle"], i["line"],
                                   i["chips"], i["badge"])
    extra = _override_css(recipe, "long")
    if extra:
        page = page.replace("</style>", extra + "</style>", 1)
    render.page_frame(page, 0.0, out, size=longform.THUMB)
    return Path(out)


def variant_path(video_path, label: str) -> Path:
    video_path = Path(video_path)
    return video_path.with_name(f"{video_path.stem}_thumb_{label.lower()}.jpg")


def describe_change(change) -> str:
    """"text bigger", "accent a2 → a3": for a page, in a few words."""
    if not change:
        return "as now"
    name, before, after = change
    if name == "text_scale":
        return "text bigger" if after > before else "text smaller"
    if name == "tilt":
        return "more tilt" if abs(after) > abs(before) else "less tilt"
    return f"{name} {after}"
