"""
Scenes to video: the timeline engine in headless Chrome, frame by frame,
into ffmpeg.

The scene (data) and the channel's art direction (data) are put into one
page with runtime.js. For each frame the page is told the exact time
(`__seek(t)`) and screenshotted, and the frames are piped to the ffmpeg
the pipeline already uses. Deterministic: the same scene always gives
the same frames. See docs/specs/animated-scenes.md.

Uses the Chrome installed on this PC through Playwright
(`channel="chrome"`), so there's no separate browser to download.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import FRAME_HEIGHT, FRAME_WIDTH
from pipeline.scenes import props

log = get_logger(__name__)

HERE = Path(__file__).parent
RUNTIME = HERE / "runtime.js"
STYLES_DIR = HERE / "styles"
FPS = 30
JPEG_QUALITY = 94


def load_style(key: str) -> dict:
    path = STYLES_DIR / f"{key}.json"
    if not path.exists():
        raise PipelineError(f"no style {key}", user_message=f"There's no art direction called {key!r}.")
    return json.loads(path.read_text(encoding="utf-8"))


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def build_html(scene: dict, style: dict, assets: dict) -> str:
    """One self-contained page: nothing is fetched from anywhere."""
    payload = {
        "SCENE": {"width": FRAME_WIDTH, "height": FRAME_HEIGHT, **scene},
        "STYLE": style,
        "ASSETS": {name: _data_uri(p) for name, p in (assets or {}).items()},
        "ASSET_META": {name: props.axis(p) for name, p in (assets or {}).items()},
    }
    # json.dumps output is valid JS; "</" is escaped so a label containing
    # "</script>" can't end the script block.
    data = "\n".join(f"window.{k} = {json.dumps(v)};".replace("</", "<\\/")
                     for k, v in payload.items())
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;background:#000;overflow:hidden}</style></head><body>"
        f"<svg id='stage' xmlns='http://www.w3.org/2000/svg' width='{FRAME_WIDTH}' "
        f"height='{FRAME_HEIGHT}' viewBox='0 0 {FRAME_WIDTH} {FRAME_HEIGHT}'></svg>"
        f"<script>{data}</script><script>{RUNTIME.read_text(encoding='utf-8')}</script>"
        "</body></html>"
    )


class _Page:
    """A headless Chrome page with the scene loaded and built."""

    def __init__(self, scene: dict, style: dict, assets: dict):
        self.html = build_html(scene, style, assets)

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(channel="chrome", headless=True)
        except Exception as exc:  # noqa: BLE001 - reworded for a person
            self._pw.stop()
            raise PipelineError(f"couldn't start Chrome: {exc}", user_message=(
                "Couldn't start Chrome to render an animated scene. Is Chrome installed?")) from exc
        page = self._browser.new_page(viewport={"width": FRAME_WIDTH, "height": FRAME_HEIGHT})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_content(self.html)
        try:
            page.wait_for_function("window.__ready === true", timeout=15000)
        except Exception as exc:  # noqa: BLE001
            detail = errors[0] if errors else str(exc)
            self.__exit__(None, None, None)
            raise PipelineError(f"scene failed to build: {detail}",
                                user_message="An animated scene couldn't be drawn.") from exc
        self.page = page
        return self

    def frame(self, t: float) -> bytes:
        self.page.evaluate(f"window.__seek({t:.4f})")
        return self.page.screenshot(type="jpeg", quality=JPEG_QUALITY)

    def __exit__(self, *exc):
        try:
            self._browser.close()
        finally:
            self._pw.stop()


def render_frame(scene: dict, style: dict, assets: dict, t: float, out_path: Path) -> Path:
    """One still at time `t`: for previews and the picture check."""
    with _Page(scene, style, assets) as page:
        Path(out_path).write_bytes(page.frame(t))
    return Path(out_path)


def layout(scene: dict, style: dict, assets: dict, step: float = 0.5,
           stills: tuple = ()) -> tuple:
    """([(t, [{id, type, kind, box}])] every `step` seconds and at the end,
    [JPEG bytes at each of `stills`]): what the layout and picture checks
    look at, from one page load."""
    duration = float(scene["duration"])
    times = [round(i * step, 3) for i in range(int(duration / step) + 1)] + [duration - 0.05]
    with _Page(scene, style, assets) as page:
        boxes = [(t, page.page.evaluate("t => window.__layout(t)", t)) for t in times]
        shots = [page.frame(t) for t in stills]
    return boxes, shots


def render(scene: dict, style: dict, assets: dict, out_path: Path, fps: int = FPS) -> Path:
    """The whole scene to an mp4 (no audio) of `scene["duration"]` seconds."""
    import imageio_ffmpeg

    duration = float(scene["duration"])
    frames = max(1, round(duration * fps))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y",
           "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           str(out_path)]
    with _Page(scene, style, assets) as page:
        encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            for i in range(frames):
                encoder.stdin.write(page.frame(i / fps))
        finally:
            encoder.stdin.close()
            code = encoder.wait()
    if code != 0:
        raise PipelineError(f"ffmpeg exited {code}", user_message="An animated scene couldn't be encoded.")
    log.info(f"  [scene] rendered {frames} frames to {out_path.name}")
    return out_path
