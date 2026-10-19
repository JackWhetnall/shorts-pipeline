"""
The owner's notes on the films of 18 October (decision 113): cards that
showed 0s and 1s, a versus of two descriptions, the same figure twice
and a year as "1,913"; a title contradicting the cards; a cutaway to a
climbing harness in the middle of a spacecraft scene; plane seats facing
the windows; whispering; and endings that didn't close the film.
"""

from __future__ import annotations

from pipeline import tts
from pipeline.documentary import cards, editor, pictures, stills


def _card_scene(card, line="A line."):
    return {"narration": line, "medium": "card", "card": card, "direction": "a picture behind"}


def test_the_card_editor_fixes_a_card_and_turns_a_pointless_one_into_its_picture(monkeypatch):
    scenes = [{"narration": "Before.", "medium": "picture"},
              _card_scene({"kind": "number", "heading": "Times it let go", "value": "0", "caption": "", "items": []},
                          "It never let go."),
              _card_scene({"kind": "versus", "heading": "Gears", "value": "", "caption": "",
                           "items": ["Clockwise|worked", "Counterclockwise|worked"]}, "Both worked."),
              {"narration": "After.", "medium": "picture"}]
    seen = {}

    def fake(system, user, schema, **kw):
        seen["user"] = user
        return {"fixes": [
            {"scene": 1, "problem": "a count of 0", "picture": True, "kind": "number", "heading": "", "value": "",
             "caption": "", "items": []},
            {"scene": 2, "problem": "two descriptions", "picture": False, "kind": "number",
             "heading": "Gear trains built", "value": "2", "caption": "one each way", "items": []}]}
    monkeypatch.setattr(editor, "call_json", fake)
    out, notes = editor.review_cards({"scenes": scenes}, {"title": "T", "thumbnail": {"words": "W"}})
    assert out["scenes"][1]["medium"] == "picture" and out["scenes"][1]["card"] == {}
    assert out["scenes"][2]["card"]["value"] == "2" and out["scenes"][2]["card"]["kind"] == "number"
    assert "The title: T" in seen["user"] and "It never let go." in seen["user"]
    assert [n["scene"] for n in notes] == [1, 2]


def test_the_same_figure_on_two_cards_keeps_only_the_first(monkeypatch):
    monkeypatch.setattr(editor, "call_json", lambda *a, **k: {"fixes": []})
    a = {"kind": "number", "heading": "Hooks per square inch", "value": "300", "caption": "", "items": []}
    b = {"kind": "number", "heading": "Per square inch", "value": "300", "caption": "", "items": []}
    out, notes = editor.review_cards({"scenes": [_card_scene(a), _card_scene(b)]})
    assert out["scenes"][0]["medium"] == "card" and out["scenes"][1]["medium"] == "picture"
    assert notes == [{"scene": 1, "problem": "the same figure as an earlier card"}]


def test_a_year_counts_up_without_a_comma_and_a_written_comma_stays():
    _, year = cards._number({"value": "1913", "heading": "h"}, 3)
    _, big = cards._number({"value": "12,262 m", "heading": "h"}, 3)
    assert "data-grouping='0'" in year and "data-grouping" not in big
    assert "data-grouping='0'" in cards.UNGROUPED and "replace(/,/g" in cards.UNGROUPED


def test_the_fact_check_reads_the_title_and_can_correct_it(monkeypatch):
    seen = {}

    def fake(system, user, schema, **kw):
        seen["user"] = user
        return {"fixes": [], "description": "", "title": "Why Velcro Has 300 Hooks Per Inch",
                "thumbnail_words": ""}
    monkeypatch.setattr(editor, "call_json", fake)
    out, notes = editor.fact_check({"scenes": [{"narration": "Three hundred hooks."}]},
                                   {"title": "Why Velcro Has Ten Thousand Hooks Per Inch", "thumbnail": {"words": "W"}})
    assert "Ten Thousand Hooks" in seen["user"]
    assert out["packaging_fix"] == {"title": "Why Velcro Has 300 Hooks Per Inch"} and notes[-1]["scene"] == -2


def test_a_whisper_is_voiced_softly():
    assert tts.soften("[whispers] Look closer.") == "[softly] Look closer."
    assert "[whispers]" not in open("pipeline/documentary/script.py", encoding="utf-8").read().split("DELIVERY")[1][:400]


def test_the_ending_closes_the_film_without_having_to_restate_its_answer():
    # Decision 115: an answer, a "now you know" or a "next time you..." all
    # close a film; a cryptic image, a bare instruction or a next episode don't.
    final = " ".join(editor.FINAL.split())
    assert "doesn't have to repeat the title's question" in final
    assert "try the tomato juice and see if you can taste the difference" in final
    assert "A weed is still holding on" in final and "Order the tomato juice." in final
    assert "next time on this channel" in final


def test_pictures_stay_with_their_place_and_wrong_layouts_are_flaws():
    assert "climbing harness" in pictures.SYSTEM and pictures.BALANCE["explainer"][1] >= 9
    assert "facing the" in stills.FLAWS and "windows" in stills.FLAWS
