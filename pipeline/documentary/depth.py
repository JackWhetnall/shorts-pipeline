"""
Real depth in a still: the camera moves and near things move more than
far ones (decision 088).

A push or pan across a flat picture scales everything equally, which is
why the first films read as slideshows however the shots were cut. With
a depth map, each point moves by how near it is: a figure slides against
the street behind them, as through a real lens (the "3D Ken Burns"
effect).

Depth comes from Depth Anything V2 Small (Apache-2.0), run here on the
CPU with onnxruntime: about a second a picture, kept beside the still so
it's worked out once. The model file lives in cache/models (downloaded
with the owner's agreement, 12 Oct 2026); without it, shots fall back to
the flat camera move.

The motion is drawn at FRAME (540p) and scaled up by the finishing pass:
four times fewer pixels to move, and a soft painted or filmic still loses
nothing a viewer would see.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from core.logging_setup import get_logger
from core.paths import CACHE_DIR

log = get_logger(__name__)

MODEL = CACHE_DIR / "models" / "depth_anything_v2_small.onnx"
INPUT = (518, 294)              # width, height: multiples of 14, as the model needs
FRAME = (960, 540)
FPS = 30
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# (zoom at the start, zoom at the end, sideways travel as a share of the
# width, how much more the nearest point moves than the farthest)
MOVES = {
    "push_in": (1.06, 1.15, 0.0, 0.07),
    "pull_out": (1.15, 1.06, 0.0, 0.07),
    "pan_left": (1.10, 1.10, -0.035, 0.05),
    "pan_right": (1.10, 1.10, 0.035, 0.05),
    "still": (1.06, 1.08, 0.0, 0.04),
}

_session = None


def available() -> bool:
    if not MODEL.exists():
        return False
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _model():
    global _session
    if _session is None:
        import onnxruntime as ort
        _session = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    return _session


def depth_map(still: Path) -> np.ndarray:
    """Nearness 0 (far) to 1 (near), FRAME-sized, smoothed so edges don't
    tear. Kept as a PNG beside the still, made again if the still is."""
    from scipy.ndimage import gaussian_filter
    still = Path(still)
    kept = still.parent / "depth" / f"{still.stem}.png"
    if kept.exists() and kept.stat().st_mtime >= still.stat().st_mtime:
        return np.asarray(Image.open(kept), dtype=np.float32) / 255
    image = Image.open(still).convert("RGB").resize(INPUT, Image.BICUBIC)
    x = (np.asarray(image, dtype=np.float32) / 255 - MEAN) / STD
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    out = _model().run(None, {"pixel_values": x})[0][0]
    lo, hi = np.percentile(out, 2), np.percentile(out, 98)
    near = np.clip((out - lo) / max(hi - lo, 1e-6), 0, 1)
    near = np.asarray(Image.fromarray((near * 255).astype(np.uint8)).resize(FRAME, Image.BICUBIC),
                      dtype=np.float32) / 255
    near = gaussian_filter(near, sigma=6)
    kept.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((near * 255).astype(np.uint8)).save(kept)
    return near


def _sampler(image: np.ndarray):
    """A fast bilinear lookup into `image` (h, w, 3 uint8) at float pixel
    coordinates: flat gathers, the four corners blended in float32."""
    h, w = image.shape[:2]
    flat = image.reshape(-1, 3)

    def sample(sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
        np.clip(sx, 0, w - 1.001, out=sx)
        np.clip(sy, 0, h - 1.001, out=sy)
        x0, y0 = sx.astype(np.int32), sy.astype(np.int32)
        fx, fy = (sx - x0).ravel()[:, None], (sy - y0).ravel()[:, None]
        i = (y0 * w + x0).ravel()
        a, b = flat.take(i, axis=0).astype(np.float32), flat.take(i + 1, axis=0).astype(np.float32)
        c, d = flat.take(i + w, axis=0).astype(np.float32), flat.take(i + w + 1, axis=0).astype(np.float32)
        top = a + (b - a) * fx
        out = top + (c + (d - c) * fx - top) * fy
        return out.reshape(h, w, 3).astype(np.uint8)
    return sample


def frames(still: Path, near: np.ndarray, seconds: float, move: str = "push_in"):
    """The shot's frames, the camera's move with parallax."""
    z0, z1, travel, depth_gain = MOVES.get(move, MOVES["push_in"])
    w, h = FRAME
    image = np.asarray(Image.open(still).convert("RGB").resize(FRAME, Image.LANCZOS), dtype=np.uint8)
    sample = _sampler(image)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = xs - w / 2, ys - h / 2
    cx, cy = w / 2, h / 2
    n = max(2, round(seconds * FPS))
    spread = (1 + 2.5 * (near - 0.5)).astype(np.float32)
    for i in range(n):
        e = 0.5 - 0.5 * np.cos(np.pi * i / (n - 1))          # eased progress
        zoom = z0 + (z1 - z0) * e
        # Near points zoom and slide a little more than far ones.
        inv = 1.0 / (zoom * (1 + depth_gain * (e if z1 >= z0 else 1 - e) * near))
        sx = cx + dx * inv - (travel * w * (e - 0.5)) * spread
        sy = cy + dy * inv
        yield sample(sx, sy)


def clip(still: Path, out: Path, seconds: float, move: str = "push_in") -> Path:
    """The parallax move as a clip, FRAME-sized, ungraded."""
    import imageio_ffmpeg
    near = depth_map(still)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{FRAME[0]}x{FRAME[1]}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "14", "-pix_fmt", "yuv420p", str(out)]
    encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for frame in frames(still, near, seconds, move):
            encoder.stdin.write(frame.tobytes())
    finally:
        encoder.stdin.close()
        code = encoder.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg exited {code} making a parallax shot")
    return Path(out)
