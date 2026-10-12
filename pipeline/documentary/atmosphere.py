"""
Air in a still picture: embers, dust, rain or snow (decision 087).

The owner, of the first One Day In History film: the visuals "look a bit
like a powerpoint". A painted still with a slow camera move is a slide,
however good the painting. What makes a still feel like a frame of film
is that something in it moves: sparks rising off an oven, dust in a
shaft of light, rain. These are drawn here, as loops of light on black,
and screened over the picture by the camera (`finish.camera_shot`), so
they only ever add light. Each loop's particles travel a whole number of
screens in its length, so it repeats without a seam. Made once and
kept; free.

And a light meter: the same film's pictures averaged 16% brightness,
dingy even at noon. `exposure` lifts a dark still towards a daytime
level (less for a scene that is meant to be at night), never darkens.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from core.logging_setup import get_logger
from core.paths import CACHE_DIR

log = get_logger(__name__)

FOLDER = CACHE_DIR / "atmosphere"
VERSION = 2
SIZE = (960, 540)               # drawn small and scaled up: soft is right for this
FPS = 30
SECONDS = 10
STRENGTH = {"embers": 0.95, "dust": 0.45, "rain": 0.5, "snow": 0.8}

KEYWORDS = [
    ("rain", r"\b(rain|raining|drizzle|downpour|storm|wet street|soaked)\b"),
    ("snow", r"\b(snow|snowing|snowfall|blizzard|sleet)\b"),
    ("embers", r"\b(oven|ovens|fire|fires|firelight|forge|hearth|bonfire|flames?|kiln|furnace|torch|torches|embers?|sparks?|blaze|burning)\b"),
    ("dust", r"\b(dust|dusty|flour|smoke|smoky|haze|hazy|mill|workshop|loft|attic|barn|cellar|shaft of light|sunbeam|market|lane|alley|street|road)\b"),
]
NIGHT = re.compile(r"\b(night|midnight|dark|darkness|candle|candlelit|lamplit|lantern|moon|moonlit|after dark)\b", re.I)


def pick(direction: str):
    """The kind of air a scene's direction calls for, or None."""
    for kind, pattern in KEYWORDS:
        if re.search(pattern, direction or "", re.I):
            return kind
    return None


def strength(kind: str) -> float:
    return STRENGTH.get(kind, 0.5)


def _particles(kind: str, rng) -> list:
    w, h = SIZE
    if kind == "embers":
        n = 55
        return [{"x": rng.uniform(0, w), "y": rng.uniform(0, h), "loops": int(rng.choice([1, 2])),
                 "sway": rng.uniform(4, 18), "phase": rng.uniform(0, 2 * math.pi), "r": rng.uniform(1.4, 3.4),
                 "blur": rng.random() < 0.35,
                 "flicker": int(rng.choice([2, 3, 4])), "colour": (255, int(rng.uniform(120, 190)), 40)}
                for _ in range(n)]
    if kind == "dust":
        n = 90
        return [{"x": rng.uniform(0, w), "y": rng.uniform(0, h), "loops": 1, "sway": rng.uniform(10, 40),
                 "phase": rng.uniform(0, 2 * math.pi), "r": rng.uniform(0.6, 2.8), "flicker": 1,
                 "colour": (255, 236, 200), "blur": rng.random() < 0.3}
                for _ in range(n)]
    if kind == "snow":
        n = 110
        return [{"x": rng.uniform(0, w), "y": rng.uniform(0, h), "loops": int(rng.choice([1, 2])),
                 "sway": rng.uniform(8, 30), "phase": rng.uniform(0, 2 * math.pi), "r": rng.uniform(1.0, 3.2),
                 "flicker": 1, "colour": (245, 248, 255)}
                for _ in range(n)]
    # rain
    n = 160
    return [{"x": rng.uniform(0, w), "y": rng.uniform(0, h), "loops": int(rng.choice([6, 7, 8])),
             "sway": 0, "phase": 0, "r": rng.uniform(0.6, 1.2), "flicker": 1, "colour": (200, 215, 235)}
            for _ in range(n)]


def _frame(kind: str, particles: list, t: float) -> Image.Image:
    """One frame at `t` (0 to 1 of the loop)."""
    w, h = SIZE
    image = Image.new("RGB", SIZE, (0, 0, 0))
    soft = Image.new("RGB", SIZE, (0, 0, 0))
    draw, draw_soft = ImageDraw.Draw(image), ImageDraw.Draw(soft)
    for p in particles:
        travel = p["loops"] * h * t
        if kind == "embers":
            y = (p["y"] - travel) % h               # rising
        else:
            y = (p["y"] + travel) % h               # falling or drifting down
        x = (p["x"] + p["sway"] * math.sin(2 * math.pi * t + p["phase"])) % w
        glow = 0.55 + 0.45 * math.sin(2 * math.pi * p["flicker"] * t + p["phase"]) if kind == "embers" else 1.0
        colour = tuple(int(c * glow) for c in p["colour"])
        if kind == "rain":
            draw.line((x, y, x - 6, y + 22), fill=tuple(int(c * 0.7) for c in colour), width=1)
            continue
        r = p["r"]
        target = draw_soft if p.get("blur") else draw
        target.ellipse((x - r, y - r, x + r, y + r), fill=colour)
    if kind in ("dust", "embers", "snow"):
        image = Image.fromarray(np.maximum(np.asarray(image.filter(ImageFilter.GaussianBlur(0.8))),
                                           np.asarray(soft.filter(ImageFilter.GaussianBlur(3)))))
    return image


def clip(kind: str) -> Path:
    """The loop for `kind`, made once and kept."""
    import imageio_ffmpeg
    FOLDER.mkdir(parents=True, exist_ok=True)
    out = FOLDER / f"{kind}_v{VERSION}.mp4"
    if out.exists():
        return out
    rng = np.random.default_rng({"embers": 1, "dust": 2, "rain": 3, "snow": 4}.get(kind, 5))
    particles = _particles(kind, rng)
    frames = FPS * SECONDS
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{SIZE[0]}x{SIZE[1]}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "16", "-pix_fmt", "yuv420p", str(out.with_suffix(".tmp.mp4"))]
    encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(frames):
            encoder.stdin.write(np.asarray(_frame(kind, particles, i / frames), dtype=np.uint8).tobytes())
    finally:
        encoder.stdin.close()
        encoder.wait()
    out.with_suffix(".tmp.mp4").replace(out)
    log.info(f"  [atmosphere] made the {kind} loop")
    return out


# --- the light meter ---------------------------------------------------------------------

DAY_LEVEL = 0.34                # mean brightness a daytime picture is lifted towards
NIGHT_LEVEL = 0.24
MAX_GAMMA = 1.8


def brightness(path: Path) -> float:
    image = np.asarray(Image.open(path).convert("RGB").resize((192, 108)), dtype=np.float32) / 255
    return float((0.2126 * image[..., 0] + 0.7152 * image[..., 1] + 0.0722 * image[..., 2]).mean())


def exposure(path: Path, direction: str = "") -> list:
    """ffmpeg filters lifting a dark still towards a natural level, or []."""
    level = brightness(path)
    target = NIGHT_LEVEL if NIGHT.search(direction or "") else DAY_LEVEL
    if level >= target or level <= 0.01:
        return []
    gamma = min(MAX_GAMMA, math.log(level) / math.log(target))
    if gamma < 1.05:
        return []
    return [f"eq=gamma={gamma:.2f}:contrast=1.08:saturation=1.06"]
