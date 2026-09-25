"""
Every template in a channel's look, as one contact sheet: what the
channel's graphics will look like, shown on its dashboard. Cached by the
look's content, so it's filmed once per look.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from pipeline.templates import library, page, samples

COLUMNS, TILE_W, TILE_H = 4, 270, 480


def sheet(style: dict, cache_dir: Path, icon_folder: Path) -> Path:
    from PIL import Image

    from pipeline.scenes import render

    runtime = page.RUNTIME.stat().st_mtime
    digest = hashlib.sha1(json.dumps([style, samples.SAMPLES, runtime], sort_keys=True,
                                     default=str).encode()).hexdigest()[:16]
    out = Path(cache_dir) / f"templates_{digest}.jpg"
    if out.exists():
        return out
    icons = page.icon_resolver(style, icon_folder)
    pages = []
    for name, slots in samples.SAMPLES.items():
        times = samples.sample_times(name, slots)
        pages.append((page.build(name, slots, times, style, 6.0, icons), 5.9))
    frames = render.page_frames(pages)
    rows = -(-len(frames) // COLUMNS)
    board = Image.new("RGB", (COLUMNS * TILE_W, rows * TILE_H), (20, 20, 24))
    for i, data in enumerate(frames):
        tile = Image.open(io.BytesIO(data)).convert("RGB").resize((TILE_W, TILE_H))
        board.paste(tile, ((i % COLUMNS) * TILE_W, (i // COLUMNS) * TILE_H))
    out.parent.mkdir(parents=True, exist_ok=True)
    board.save(out, quality=86)
    return out


def names() -> list:
    return list(library.TEMPLATES)
