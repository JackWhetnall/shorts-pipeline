"""
A picture's references go as one sheet of numbered panels (decision 096):
each reference is billed the same whatever its size, so one sheet costs
about half of three or four separate ones.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from core.channels import Documentary
from pipeline.animation import keyframes


LOOK = {"image": "flat shapes", "frame": "wide"}


def _png(path: Path, colour) -> Path:
    Image.new("RGB", (300, 400), colour).save(path)
    return path


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(keyframes, "COMBINED_DIR", tmp_path / "sheets")
    style = _png(tmp_path / "style.png", "blue")
    sheets = {"ana": _png(tmp_path / "ana.png", "red"), "river": _png(tmp_path / "river.png", "green")}
    board = {"elements": {"ana": {"kind": "character", "name": "Ana"},
                          "river": {"kind": "place", "name": "River"}}}
    return style, sheets, board


def test_references_go_as_one_numbered_sheet_and_the_prompt_says_so(tmp_path, monkeypatch):
    style, sheets, board = _setup(tmp_path, monkeypatch)
    shot = {"index": 3, "framing": "wide", "image": "Ana by the river.", "elements": ["river", "ana"]}
    job = keyframes.request(shot, board, LOOK, style, sheets, tmp_path, "m", combined=True)
    assert len(job["references"]) == 1 and job["references"][0].parent == tmp_path / "sheets"
    assert job["prompt"].startswith(keyframes.PANELS) and "Image 2 is Ana" in job["prompt"]
    sheet = Image.open(job["references"][0])
    assert sheet.size == keyframes.COMBINED_SIZE
    assert sheet.getpixel((300, 600))[2] > 200                        # the style sheet, left
    assert sheet.getpixel((1700, 300))[0] > 200                       # Ana's sheet, top right
    assert sheet.getpixel((1700, 900))[1] > 100                       # the river's, below
    again = keyframes.request(dict(shot, index=4), board, LOOK, style, sheets, tmp_path, "m", combined=True)
    assert again["references"] == job["references"]                   # one sheet, kept for the next picture


def test_separately_or_with_one_reference_nothing_changes(tmp_path, monkeypatch):
    style, sheets, board = _setup(tmp_path, monkeypatch)
    shot = {"index": 0, "framing": "wide", "image": "The river.", "elements": ["river"]}
    separate = keyframes.request(shot, board, LOOK, style, sheets, tmp_path, "m")
    assert separate["references"] == [style, sheets["river"]]
    assert not separate["prompt"].startswith(keyframes.PANELS)
    alone = keyframes.request(dict(shot, elements=[]), board, LOOK, style, sheets, tmp_path, "m", combined=True)
    assert alone["references"] == [style] and not alone["prompt"].startswith(keyframes.PANELS)


def test_films_are_drawn_from_one_sheet_unless_a_channel_turns_it_off():
    assert Documentary().combined_references is True
