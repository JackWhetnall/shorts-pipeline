"""
Intake tool for new raw downloads. Naive center-cropping (what
manage_library.py's _normalize() does by default) is wrong whenever the
subject in a source clip isn't centered on the axis that gets cropped —
this catches that before the clip ever enters the library.

Two phases, so you only have to sit at the keyboard for the fast part:
1. Interactive: for every video in footage/new_downloads/, shows one
   labeled contact-sheet image with 5 candidate crop positions (along
   whichever axis actually has slack after scaling to cover 1080x1920)
   and asks you to pick one (or skip). Collects all the picks up front.
2. Unattended: encodes each real normalized clip with its chosen crop
   into footage/normalized/, moves the original into
   footage/old_downloads/, then chains straight into captioning
   (manage_library.add_normalized_clip) — no more input needed, so you
   can walk away once phase 1 is done.

Usage:
    python footage/review_new_downloads.py
"""

import os
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from moviepy.editor import VideoFileClip

sys.path.insert(0, str(Path(__file__).parent))
from manage_library import W, H, _normalize, add_normalized_clip  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))
from video_assemble import _load_font  # noqa: E402

ROOT = Path(__file__).parent.parent
FOOTAGE_DIR = Path(__file__).parent
NEW_DOWNLOADS_DIR = FOOTAGE_DIR / "new_downloads"
OLD_DOWNLOADS_DIR = FOOTAGE_DIR / "old_downloads"
NORMALIZED_DIR = FOOTAGE_DIR / "normalized"

PANEL_WIDTH = 220
PANEL_HEIGHT = int(PANEL_WIDTH * H / W)
LABEL_HEIGHT = 28

# (label, key, fraction along the slack axis: 0.0 = one edge, 1.0 = the other)
POSITIONS_HORIZONTAL = [("left", "l", 0.0), ("center-left", "cl", 0.25), ("center", "c", 0.5),
                         ("center-right", "cr", 0.75), ("right", "r", 1.0)]
POSITIONS_VERTICAL = [("top", "l", 0.0), ("center-top", "cl", 0.25), ("center", "c", 0.5),
                       ("center-bottom", "cr", 0.75), ("bottom", "r", 1.0)]

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def _candidate_positions(src_w, src_h):
    """Which axis has leftover slack after scaling to cover WxH, and the 5
    positions to offer along it. None if the source already matches the
    target ratio (nothing to choose)."""
    target_ratio = W / H
    src_ratio = src_w / src_h
    if abs(src_ratio - target_ratio) < 1e-3:
        return None
    if src_ratio > target_ratio:
        return "x", POSITIONS_HORIZONTAL
    return "y", POSITIONS_VERTICAL


def _cropped_frame(resized_clip, axis, frac, t):
    frame = Image.fromarray(resized_clip.get_frame(t))
    full_w, full_h = frame.size
    if axis == "x":
        x = int(frac * (full_w - W))
        box = (x, 0, x + W, H)
    else:
        y = int(frac * (full_h - H))
        box = (0, y, W, y + H)
    return frame.crop(box)


def _build_contact_sheet(src: Path):
    """Returns (axis, positions, sheet_image) or (None, None, None) if the
    clip needs no crop choice."""
    clip = VideoFileClip(str(src))
    src_w, src_h = clip.size
    axis_positions = _candidate_positions(src_w, src_h)
    if axis_positions is None:
        clip.close()
        return None, None, None

    axis, positions = axis_positions
    resized = clip.resize(height=H) if axis == "x" else clip.resize(width=W)
    t = min(2.0, clip.duration / 2)

    font = _load_font(16)
    panels = []
    for label, key, frac in positions:
        thumb = _cropped_frame(resized, axis, frac, t).resize((PANEL_WIDTH, PANEL_HEIGHT))
        panel = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT + LABEL_HEIGHT), "black")
        panel.paste(thumb, (0, 0))
        ImageDraw.Draw(panel).text((8, PANEL_HEIGHT + 6), f"{key}: {label}", font=font, fill="white")
        panels.append(panel)

    sheet = Image.new("RGB", (PANEL_WIDTH * len(panels), PANEL_HEIGHT + LABEL_HEIGHT), "black")
    for i, panel in enumerate(panels):
        sheet.paste(panel, (i * PANEL_WIDTH, 0))

    resized.close()
    clip.close()
    return axis, positions, sheet


def _prompt_position(positions):
    valid_keys = {key for _, key, _ in positions} | {"s"}
    while True:
        answer = input(f"  Pick a crop [{'/'.join(k for _, k, _ in positions)}/s to skip]: ").strip().lower()
        if answer in valid_keys:
            return answer


def _collect_choice(src: Path):
    """Interactive part only: show the contact sheet, get the crop pick.
    Returns a plan dict for _apply_plan(), or None if skipped."""
    print(f"\n{src.name}")
    axis, positions, sheet = _build_contact_sheet(src)

    if axis is None:
        print("  Aspect ratio already matches target - using center, no choice needed.")
        return {"src": src, "frac": 0.5, "axis": "x"}

    sheet_path = ROOT / "cache" / f"crop_preview_{src.stem}.jpg"
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path)
    os.startfile(sheet_path)

    answer = _prompt_position(positions)
    if answer == "s":
        print("  Skipped - left in new_downloads/ for next time.")
        return None
    frac = next(f for _, key, f in positions if key == answer)
    return {"src": src, "frac": frac, "axis": axis}


def _apply_plan(plan: dict):
    """Unattended part: the actual ffmpeg encode, archiving, and
    captioning — no user input from here on."""
    src, frac, chosen_axis = plan["src"], plan["frac"], plan["axis"]
    print(f"\n{src.name}")

    x_expr = f"{frac}*(in_w-out_w)" if chosen_axis == "x" else "(in_w-out_w)/2"
    y_expr = f"{frac}*(in_h-out_h)" if chosen_axis == "y" else "(in_h-out_h)/2"

    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    OLD_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest_name = src.stem.lower().replace(" ", "_") + ".mp4"
    normalized_path = NORMALIZED_DIR / dest_name

    print(f"  Normalizing -> footage/normalized/{dest_name} ...")
    _normalize(src, normalized_path, x_expr=x_expr, y_expr=y_expr)

    archived_path = OLD_DOWNLOADS_DIR / src.name
    shutil.move(str(src), str(archived_path))
    print(f"  Original archived -> footage/old_downloads/{src.name}")

    try:
        add_normalized_clip(normalized_path, dest_name=dest_name, source=str(archived_path))
    except Exception as e:
        print(f"  Captioning failed ({e}) - the clip is safe in footage/normalized/{dest_name}.")
        print(f"  Retry later with: python footage/manage_library.py add footage/normalized/{dest_name}")


def main():
    NEW_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    clips = sorted(f for f in NEW_DOWNLOADS_DIR.iterdir() if f.suffix.lower() in VIDEO_EXTS)
    if not clips:
        print(f"No video files found in {NEW_DOWNLOADS_DIR}")
        return

    print(f"Found {len(clips)} clip(s) in footage/new_downloads/.")
    print("Pick a crop for each one now; the slow part (encoding + captioning) runs afterward with no more input needed.\n")

    plans = [plan for plan in (_collect_choice(src) for src in clips) if plan is not None]

    if not plans:
        print("\nNothing to process.")
        return

    print(f"\nAll {len(plans)} crop(s) chosen - processing now, unattended...")
    for plan in plans:
        _apply_plan(plan)

    print(f"\nDone. {len(plans)} clip(s) added to the library.")


if __name__ == "__main__":
    main()
