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


def test_each_batch_is_new_ideas_in_unused_looks_and_nothing_is_ever_deleted(monkeypatch, tmp_path):
    monkeypatch.setattr(logos, "_candidates_dir", lambda key: tmp_path / "candidates")
    asked, shown = [], []

    def fake_concepts(fragment, n, before):
        shown.append(list(before))
        return [f"idea {len(before) + i}" for i in range(n)]
    monkeypatch.setattr(logos, "concepts", fake_concepts)
    monkeypatch.setattr(logos, "_generate_images", lambda prompt, n, quality: asked.append(prompt) or [b"png"])
    first = logos.generate_candidates("c", "why everyday things work")
    second = logos.generate_candidates("c", "why everyday things work")
    assert len(first) == len(second) == logos.CANDIDATE_COUNT
    assert all(p.exists() for p in first + second)                       # the first batch is kept
    assert len(set(asked)) == 2 * logos.CANDIDATE_COUNT
    assert shown[1] == [f"idea {i}" for i in range(5)]                    # told what it's already drawn
    ideas = logos._ideas("c")
    looks = [i["direction"] for i in ideas]
    assert len(set(looks)) == 10                                          # no look twice while unused ones remain
    assert all("The mark shows idea" in a for a in asked)


def test_the_least_used_looks_come_first():
    used = logos.DIRECTIONS[:10] * 2 + logos.DIRECTIONS[10:]
    assert set(logos.directions(2, random.Random(3), used=used)) == set(logos.DIRECTIONS[10:])


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
