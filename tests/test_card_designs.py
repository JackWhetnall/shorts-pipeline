"""
A channel's own card designs (decision 123). The owner, on 20 Oct: the
new channels' cards were "basically identical", "Title, 'X' vs 'Y'",
when the point is that they're entirely distinct channels.

- every kind of card builds in each design, in shapes of its own;
- a channel with no design keeps the glass cards exactly as they were;
- the design is kept by the art settings and set from the film form;
- a chapter's title is drawn in the design;
- pictures drawn at once that share a reference sheet don't trip over
  each other making it (found the same day).
"""

from __future__ import annotations

import threading

from PIL import Image

from core.channels import ChannelConfig
from pipeline.documentary import card_designs, cards, render
from pipeline.scenes import art

DECK = [
    {"kind": "number", "heading": "Yearly pay", "value": "£50", "caption": "about £7,000 today"},
    {"kind": "versus", "heading": "Pay", "items": ["1880s|£50", "Today|£7,000"]},
    {"kind": "quote", "heading": "The rule book", "caption": "The lamps shall be lighted at sunset."},
    {"kind": "timeline", "heading": "The watches", "items": ["4 a.m.|Last watch", "Noon|Lunch", "Sunset|Light up"]},
    {"kind": "list", "heading": "Every morning", "items": ["Trim the wicks", "Polish the lens"]},
    {"kind": "map", "heading": "The Smalls", "caption": "off Wales", "lat": 51.72, "lon": -5.67},
]
MARKS = {  # what each kind of card is made of, in each design
    "time_card": {"number": "paper clock", "versus": "paper ledger", "quote": "pinhead", "timeline": "paper rota",
                  "list": "paper duty", "map": "class='tag"},
    "scandal": {"number": "class='burst'", "versus": "class='heart'", "quote": "class='clip'",
                "timeline": "class='pinned'", "list": "heart small", "map": "class='lips'"},
}


def _style(design=None):
    return art.resolve({"preset": "clean_flat", **({"card_design": design} if design else {})})


def test_every_card_builds_in_each_design_in_its_own_shapes():
    for design, marks in MARKS.items():
        for card in DECK:
            page = cards.build(card, _style(design), 6.0)
            body = page[page.index("</style>"):]
            assert marks[card["kind"]] in body, (design, card["kind"])
            assert "chip vs" not in body


def test_no_design_keeps_the_glass_cards_as_they_were():
    for card in DECK:
        assert cards.build(card, _style(), 6.0) == cards.build(card, _style("glass"), 6.0)
    assert "chip vs" in cards.build(DECK[1], _style(), 6.0)
    assert card_designs.of({}) == card_designs.of({"card_design": "nonsense"}) == "glass"


def test_the_design_is_kept_and_set_from_the_film_form():
    assert art.clean({"card_design": "scandal"})["card_design"] == "scandal"
    assert "card_design" not in art.sparse({"card_design": "glass"})
    from web.forms import apply_channel_form
    channel = ChannelConfig(key="c", channel_display_name="C", format="documentary")
    channel.scenes.art = {"preset": "clean_flat", "accent1": "#C8372D"}
    apply_channel_form(channel, {"documentary_present": "1", "documentary_card_design": "time_card"})
    assert channel.scenes.art["card_design"] == "time_card" and channel.scenes.art["accent1"] == "#C8372D"


def test_a_chapter_title_is_drawn_in_the_design():
    plain = render.label_overlay((960, 540), "7 a.m.: Cleaning the lens", 0, "", {})
    for design in ("time_card", "scandal"):
        drawn = render.label_overlay((960, 540), "7 a.m.: Cleaning the lens", 0, "", {"card_design": design})
        assert drawn.getbbox() is not None and drawn.tobytes() != plain.tobytes()


def test_pictures_drawn_at_once_share_a_reference_sheet_safely(tmp_path, monkeypatch):
    from pipeline.animation import keyframes
    monkeypatch.setattr(keyframes, "COMBINED_DIR", tmp_path / "sheets")
    refs = []
    for n in range(3):
        path = tmp_path / f"ref{n}.png"
        Image.new("RGB", (64, 64), (40 * n, 80, 120)).save(path)
        refs.append(path)
    found, errors = [], []

    def make():
        try:
            found.append(keyframes.combine(refs))
        except Exception as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=make) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(set(found)) == 1 and found[0].exists()
    assert not list((tmp_path / "sheets").glob("*.part.png"))
