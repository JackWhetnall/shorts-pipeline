"""
Every word on screen is checked (decision 098): the first overseen film
(t0003) went through with captions saying Mars was "fully mapped since
2006" after the lines had been corrected to "near-complete", because the
fact check could only correct a card's value or items, and the overseer
had no way to edit a heading, a caption or the thumbnail words.
"""

from __future__ import annotations

from core import overseer, production
from pipeline.documentary import editor


def _card(caption="Mars: fully mapped since 2006"):
    return {"narration": "Why is the sea harder?", "medium": "card",
            "card": {"kind": "number", "heading": "Ocean floor seen", "value": "26%", "caption": caption, "items": []}}


def test_the_fact_check_sees_each_part_of_a_card_and_corrects_a_caption_alone(monkeypatch):
    seen = []
    monkeypatch.setattr(editor, "call_json", lambda system, user, *a, **k: seen.append(user) or {"description": "", "fixes": [
        {"scene": 0, "problem": "overstates", "narration": "", "card": "", "card_heading": "",
         "card_caption": "Mars: mapped almost everywhere"}]})
    out, notes = editor.fact_check({"scenes": [_card()]})
    assert 'caption "Mars: fully mapped since 2006"' in seen[0]
    card = out["scenes"][0]["card"]
    assert card["caption"] == "Mars: mapped almost everywhere" and card["value"] == "26%"
    assert out["scenes"][0]["narration"] == "Why is the sea harder?" and notes[0]["scene"] == 0


def test_a_row_with_nothing_to_change_changes_nothing(monkeypatch):
    monkeypatch.setattr(editor, "call_json", lambda *a, **k: {"description": "", "fixes": [
        {"scene": 0, "problem": "p", "narration": "", "card": "", "card_heading": "", "card_caption": ""}]})
    out, notes = editor.fact_check({"scenes": [_card()]})
    assert out["scenes"][0] == _card() and notes == []


def test_the_overseer_edits_headings_captions_and_the_thumbnail_words(monkeypatch):
    data = {"script": {"scenes": [_card()]}, "history": [],
            "pitch": {"chosen": 0, "angles": [{"title": "T", "thumbnail": {"words": "1% Ever Seen"}}]}}
    monkeypatch.setattr(production, "update", lambda k, s, change, *a: change(data))
    overseer.edit("c", "t", 0, card_heading="Seafloor mapped in detail", card_caption="Mars: almost all of it")
    overseer.edit("c", "t", -1, thumb_words="26% Mapped")
    card = data["script"]["scenes"][0]["card"]
    assert card["heading"] == "Seafloor mapped in detail" and card["caption"] == "Mars: almost all of it"
    assert data["pitch"]["angles"][0]["thumbnail"]["words"] == "26% Mapped"


def test_the_script_sheet_says_the_hook_is_never_shown():
    assert "never shown or spoken" in open("core/overseer.py", encoding="utf-8").read()
    assert "--card-caption" in open("docs/overseer.md", encoding="utf-8").read()
