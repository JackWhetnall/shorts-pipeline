"""
A stage (script.py) to video: one self-contained page with runtime.js,
filmed frame by frame in the installed Chrome by the same capture the
motion-graphics templates use (pipeline.scenes.render).

Pictures go in as data URIs and the label face as an embedded @font-face,
so nothing is fetched and a stage renders the same on any machine that
has the font file.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from core.errors import PipelineError
from core.paths import FRAME_HEIGHT, FRAME_WIDTH
from pipeline.animation.compositor import mathtext
from pipeline.scenes import render as capture

HERE = Path(__file__).parent
RUNTIME = HERE / "runtime.js"

# Label faces by name: the files Windows ships them in, best first.
FACES = {
    "Ink Free": ("Inkfree.ttf",),
    "Segoe Print": ("segoeprb.ttf", "segoepr.ttf"),
    "Segoe UI": ("segoeuib.ttf",),
    "Segoe UI Black": ("seguibl.ttf",),
    "Bahnschrift": ("bahnschrift.ttf",),
    "Georgia": ("georgiab.ttf",),
    "Constantia": ("constanb.ttf",),
    "Book Antiqua": ("BKANT.TTF", "ANTQUAB.TTF"),
    "Rockwell": ("ROCKB.TTF",),
    "Computer Modern": ("cmr10.ttf",),              # matplotlib's copy (compositor.mathtext)
}
FONT_DIRS = (Path(r"C:\Windows\Fonts"),
             Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts")


def _mime(path: Path) -> str:
    return {".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")


def _data_uri(path: Path) -> str:
    return f"data:{_mime(path)};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def font_face(name: str) -> str:
    """An @font-face rule embedding `name`, or "" when its file isn't here
    (the page then falls back to the system's own copy, if any)."""
    folders = FONT_DIRS + ((mathtext.font_path().parent,) if name == "Computer Modern" else ())
    for filename in FACES.get(name, ()):
        for folder in folders:
            path = folder / filename
            if path.exists():
                data = base64.b64encode(path.read_bytes()).decode()
                return (f"@font-face{{font-family:'{name}';"
                        f"src:url(data:font/ttf;base64,{data}) format('truetype');}}")
    return ""


def size(stage: dict) -> tuple:
    """(width, height) of the frame a stage is made for; a stage from
    before widescreen (decision 054) is vertical."""
    frame = stage.get("frame") or {}
    return int(frame.get("w", FRAME_WIDTH)), int(frame.get("h", FRAME_HEIGHT))


def _all_assets(stage: dict, assets: dict) -> dict:
    """The pictures the page needs: the kit's, and the typeset maths the
    stage's diagrams name."""
    return {**assets, **{name: Path(p) for name, p in (stage.get("math") or {}).items()}}


def build_html(stage: dict, assets: dict) -> str:
    font = stage["labels"]["font"]
    w, h = size(stage)
    assets = _all_assets(stage, assets)
    faces = font_face(font)
    if font != "Computer Modern" and stage.get("math"):
        faces += font_face("Computer Modern")      # a diagram's plain numbers match its maths
    payload = {
        "STAGE": {"width": w, "height": h, **{k: v for k, v in stage.items() if k != "math"},
                  "labels": {**stage["labels"], "font": f"'{font}', 'Segoe UI', sans-serif"}},
        "ASSETS": {name: _data_uri(p) for name, p in assets.items()},
    }
    data = "\n".join(f"window.{k} = {json.dumps(v)};".replace("</", "<\\/")
                     for k, v in payload.items())
    return ("<!doctype html><html><head><meta charset='utf-8'><style>"
            f"{faces}"
            "html,body{margin:0;background:#000;overflow:hidden}"
            f"#frame{{position:relative;width:{w}px;height:{h}px;"
            "overflow:hidden}</style></head><body><div id='frame'></div>"
            f"<script>{data}</script><script>{RUNTIME.read_text(encoding='utf-8')}</script>"
            "</body></html>")


def render(stage: dict, assets: dict, out_path: Path) -> Path:
    """The whole stage to an mp4 (no audio) of stage["duration"] seconds."""
    missing = [n for n, p in _all_assets(stage, assets).items() if not Path(p).exists()]
    if missing:
        raise PipelineError(f"missing pictures: {missing}",
                            user_message="A picture the animation needs is missing.")
    return capture.render_page(build_html(stage, assets), float(stage["duration"]), out_path,
                               size=size(stage))


def still(stage: dict, assets: dict, t: float, out_path: Path = None) -> bytes:
    """One frame at `t`, as JPEG bytes (and saved to `out_path` if given)."""
    return capture.page_frame(build_html(stage, assets), t, out_path, size=size(stage))


def caption_png(text: str, labels: dict, out_path: Path) -> Path:
    """A caption as a transparent PNG: the text on a paper label, in the
    format's face, tilted a hair as if pinned there. For laying over
    generated shots (a paper theatre's names and dates)."""
    from html import escape

    from playwright.sync_api import sync_playwright

    font = labels.get("font", "Georgia")
    size = int(labels.get("size", 50))
    tag = labels.get("tag") or "#F3E9D2"
    ink = labels.get("color", "#2B2118")
    html = ("<!doctype html><html><head><meta charset='utf-8'><style>"
            f"{font_face(font)}html,body{{margin:0;background:transparent}}"
            f"#c{{display:inline-block;margin:24px;padding:{size * 0.32}px {size * 0.6}px;"
            f"background:{tag};color:{ink};font:{labels.get('weight', 700)} {size}px "
            f"'{font}',Georgia,serif;letter-spacing:0.02em;transform:rotate(-1.2deg);"
            "box-shadow:3px 7px 12px rgba(40,28,16,0.35);border-radius:3px;white-space:nowrap}"
            f"</style></head><body><div id='c'>{escape(text)}</div></body></html>")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": FRAME_WIDTH, "height": 400})
            page.set_content(html)
            page.evaluate("document.fonts.ready")
            box = page.locator("#c").bounding_box()
            pad = 22
            page.screenshot(path=str(out_path), type="png", omit_background=True,
                            clip={"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                                  "width": box["width"] + 2 * pad,
                                  "height": box["height"] + 2 * pad})
        finally:
            browser.close()
    return out_path


def stills(stage: dict, assets: dict, times: list) -> list:
    html = build_html(stage, assets)
    return capture.page_frames([(html, t) for t in times])
