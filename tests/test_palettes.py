"""
Curated caption palettes: every combination on offer has to actually be
legible and internally consistent. The Slate Mono entry originally shipped
with a highlight colour (#D9DCE3) so close to white that the "current
word" indicator was invisible in a real render — caught only by actually
rendering it, not by reading the hex. These tests check the property that
rendering exposed, so the bug can't come back silently.
"""

from __future__ import annotations

import pytest

from core import palettes


def _rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _distance(a: str, b: str) -> float:
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    return ((ar - br) ** 2 + (ag - bg) ** 2 + (ab - bb) ** 2) ** 0.5


class TestPaletteLegibility:
    # Below this, two colours read as "the same" in a caption at a glance.
    # Chosen from the failing case: Slate Mono's original highlight was
    # ~26 by this measure and was visibly unreadable; its replacement is
    # ~154. The threshold sits well below the fix and well above the bug.
    MIN_DISTANCE = 60

    @pytest.mark.parametrize("palette", palettes.PALETTES, ids=lambda p: p.key)
    def test_highlight_is_distinguishable_from_base(self, palette):
        assert _distance(palette.base_color, palette.highlight_color) >= self.MIN_DISTANCE

    @pytest.mark.parametrize("palette", palettes.PALETTES, ids=lambda p: p.key)
    def test_stroke_is_distinguishable_from_both_text_colors(self, palette):
        """The stroke is what keeps a caption readable over bright footage;
        a stroke too close to the text colour it outlines defeats that."""
        assert _distance(palette.stroke_color, palette.base_color) >= self.MIN_DISTANCE
        assert _distance(palette.stroke_color, palette.highlight_color) >= self.MIN_DISTANCE

    @pytest.mark.parametrize("palette", palettes.PALETTES, ids=lambda p: p.key)
    def test_every_face_it_offers_actually_resolves(self, palette):
        """A palette pointing at a font this machine can't find would
        silently fall back to the generic default, quietly undoing the
        pairing this module exists to guarantee."""
        from core import fonts

        for face_key in palette.font_faces:
            assert face_key in fonts.FACES_BY_KEY

    def test_keys_are_unique(self):
        keys = [p.key for p in palettes.PALETTES]
        assert len(keys) == len(set(keys))

    def test_get_falls_back_to_the_default_for_an_unknown_key(self):
        assert palettes.get("does_not_exist").key == palettes.DEFAULT_PALETTE

    def test_get_returns_the_requested_palette(self):
        assert palettes.get("forest").key == "forest"


class TestRandomChoice:
    def test_the_font_always_belongs_to_the_chosen_palette(self):
        """random_choice must never pair a palette with a face from a
        different palette's list."""
        import random

        for _ in range(200):
            palette, face = palettes.random_choice(random.Random())
            assert face in palette.font_faces

    def test_is_reproducible_with_a_seeded_rng(self):
        import random

        a = palettes.random_choice(random.Random(42))
        b = palettes.random_choice(random.Random(42))
        assert a == b

    def test_can_reach_every_palette_given_enough_draws(self):
        import random

        rng = random.Random(7)
        seen = {palettes.random_choice(rng)[0].key for _ in range(500)}
        assert seen == set(palettes.PALETTES_BY_KEY)


class TestApplyToStyle:
    def test_writes_every_colour_field(self):
        from core.channels import Style

        style = Style()
        palette = palettes.get("violet_mystic")
        palettes.apply_to_style(style, palette)

        assert style.base_color == palette.base_color
        assert style.highlight_color == palette.highlight_color
        assert style.stroke_color == palette.stroke_color
        assert style.outro_title_color == palette.outro_title_color
        assert style.outro_subtext_color == palette.outro_subtext_color
        assert style.outro_bg_color == palette.outro_bg_color
        assert style.title_card_title_color == palette.title_card_title_color
        assert style.title_card_channel_color == palette.title_card_channel_color
        assert style.title_card_bg_color == palette.title_card_bg_color

    def test_defaults_to_the_palettes_first_face(self):
        from core.channels import Style

        style = Style()
        palette = palettes.get("forest")
        palettes.apply_to_style(style, palette)
        assert style.font_face == palette.font_faces[0]

    def test_a_face_outside_the_palette_is_ignored_in_favour_of_the_default(self):
        """A caller passing a face that doesn't belong to this palette
        would otherwise silently break the pairing the palette exists to
        guarantee."""
        from core.channels import Style

        style = Style()
        palette = palettes.get("forest")
        palettes.apply_to_style(style, palette, font_face="impact")
        assert style.font_face == palette.font_faces[0]

    def test_a_face_that_does_belong_is_kept(self):
        from core.channels import Style

        style = Style()
        palette = palettes.get("forest")
        chosen = palette.font_faces[-1]
        palettes.apply_to_style(style, palette, font_face=chosen)
        assert style.font_face == chosen


class TestPaletteGrid:
    """A rendered check, not just arithmetic on hex strings — this is what
    actually caught the Slate Mono bug, so it stays as a real assertion
    rather than being replaced by the cheaper distance test above."""

    def test_the_highlighted_word_is_visibly_different_from_the_rest(self):
        import io

        from PIL import Image

        from core import caption_preview
        from core.channels import Pacing, Style

        for palette in palettes.PALETTES:
            style = Style()
            palettes.apply_to_style(style, palette)
            png = caption_preview.render(style, Pacing())
            image = Image.open(io.BytesIO(png)).convert("RGB")

            base_rgb = _rgb(palette.base_color)
            highlight_rgb = _rgb(palette.highlight_color)
            # Count pixels closer to the highlight colour than to the base
            # colour. If the highlight word rendered as intended, this
            # must be a meaningful chunk of the caption, not a handful of
            # anti-aliased edge pixels.
            width, height = image.size
            close_to_highlight = 0
            for y in range(int(height * 0.65), height, 4):
                for x in range(0, width, 4):
                    pixel = image.getpixel((x, y))
                    if (_distance("%02X%02X%02X" % pixel, "%02X%02X%02X" % highlight_rgb)
                            < _distance("%02X%02X%02X" % pixel, "%02X%02X%02X" % base_rgb)):
                        close_to_highlight += 1
            assert close_to_highlight > 20, (
                f"{palette.key}: the highlighted word is not visibly "
                f"distinct from the caption's base colour")
