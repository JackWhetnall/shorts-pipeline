"""
Logos that look like their own channel (decision 099): the prompt used to
coach every logo towards the same glossy, gradient, full-colour sticker,
and all five candidates came from one prompt, so every channel's logo was
orange on a navy disc. Each candidate now takes a different direction.
"""

from __future__ import annotations

import random

from core import logos


def test_no_house_style_in_the_prompt():
    prompt = logos.build_prompt("why everyday things work", direction="Monoline icon.").lower()
    for coached in ("gradient", "shading", "vivid", "layered detail"):
        assert coached not in prompt
    assert "monoline icon." in prompt and "no text" in prompt


def test_each_candidate_takes_a_different_direction(monkeypatch, tmp_path):
    monkeypatch.setattr(logos, "_candidates_dir", lambda key: tmp_path / "candidates")
    asked = []
    monkeypatch.setattr(logos, "_generate_images", lambda prompt, n, quality: asked.append(prompt) or [b"png"])
    paths = logos.generate_candidates("c", "why everyday things work")
    assert len(paths) == logos.CANDIDATE_COUNT and all(p.read_bytes() == b"png" for p in paths)
    assert len(set(asked)) == logos.CANDIDATE_COUNT
    assert len(set(logos.directions(5, random.Random(1)))) == 5


def test_the_logo_page_shows_ideas_already_made_and_their_price(monkeypatch, tmp_path):
    from core import assets
    from web import create_app
    folder = tmp_path / "candidates"
    folder.mkdir()
    (folder / "ab_0.png").write_bytes(b"png")
    monkeypatch.setattr(assets, "candidates_dir", lambda key: folder)
    client = create_app().test_client()
    key = next(iter(__import__("core.channels", fromlist=["load_channels"]).load_channels()))
    page = client.get(f"/channels/{key}/logo").get_data(as_text=True)
    assert "candidates/ab_0.png" in page and "$0.21" in page
