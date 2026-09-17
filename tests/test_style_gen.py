"""
`pipeline.style_gen`: the AI palette/font suggestion, and its web route.

Every model call is stubbed. The two properties worth testing are the
ones that keep a bad or wrong answer from ever reaching a channel's
actual look: a nonexistent palette key falls back safely, and a font key
from the wrong palette is corrected rather than trusted.
"""

from __future__ import annotations

import pytest

from core import palettes
from core.errors import PipelineError
from pipeline import style_gen


class _Channel:
    key = "c"
    channel_display_name = "Test Channel"
    style_prompt = "A calm channel about houseplants."


class TestSuggestPalette:
    def test_a_valid_answer_is_used_as_is(self, monkeypatch):
        monkeypatch.setattr(style_gen, "call_json", lambda *a, **k: {
            "palette_key": "forest", "font_key": "verdana_bold",
            "reason": "Plants, so green."})
        result = style_gen.suggest_palette(_Channel())
        assert result == {"palette_key": "forest", "font_key": "verdana_bold",
                          "reason": "Plants, so green.", "source": "ai"}

    def test_a_font_from_the_wrong_palette_is_corrected(self, monkeypatch):
        """core.palettes exists specifically so no caller can pair a
        palette with a face it wasn't checked against. A model naming the
        wrong one is a prompt-following slip, not grounds to fail."""
        monkeypatch.setattr(style_gen, "call_json", lambda *a, **k: {
            "palette_key": "forest", "font_key": "impact",  # not a Forest face
            "reason": "x"})
        result = style_gen.suggest_palette(_Channel())
        forest = palettes.get("forest")
        assert result["font_key"] in forest.font_faces
        assert result["font_key"] == forest.font_faces[0]

    def test_an_unknown_palette_key_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setattr(style_gen, "call_json", lambda *a, **k: {
            "palette_key": "not_a_real_palette", "font_key": "arial_bold",
            "reason": "x"})
        result = style_gen.suggest_palette(_Channel())
        assert result["palette_key"] == palettes.DEFAULT_PALETTE

    def test_a_failed_call_falls_back_to_a_random_pick_not_an_error(self, monkeypatch):
        """A suggestion is a convenience. A channel's look must never be
        blocked on an API call succeeding."""
        def explode(*a, **k):
            raise PipelineError("boom", user_message="down")

        monkeypatch.setattr(style_gen, "call_json", explode)
        result = style_gen.suggest_palette(_Channel())
        assert result["source"] == "random"
        assert result["palette_key"] in palettes.PALETTES_BY_KEY

    def test_the_schema_offers_only_real_palette_keys(self):
        schema = style_gen._palette_schema()
        offered = set(schema["properties"]["palette_key"]["enum"])
        assert offered == set(palettes.PALETTES_BY_KEY)

    def test_no_schema_uses_array_bounds(self):
        """The API rejects minItems/maxItems other than 0 and 1."""
        schema = style_gen._palette_schema()
        assert "minItems" not in str(schema) and "maxItems" not in str(schema)


class TestSuggestLookRoute:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from core.channels import ChannelConfig, channel_to_sparse_dict, write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        channel = ChannelConfig(key="c", channel_display_name="C",
                                content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM",
                                style_prompt="p", topics=["x"])
        write_raw({"c": channel_to_sparse_dict(channel)}, path)
        app = create_app()
        app.config.update(TESTING=True)
        with app.test_client() as test_client:
            yield test_client

    def _csrf(self, client):
        html = client.get("/").get_data(as_text=True)
        marker = 'name="csrf-token" content="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_requires_csrf(self, client):
        assert client.post("/api/channels/c/suggest-look").status_code == 400

    def test_returns_real_colour_values(self, client, monkeypatch):
        monkeypatch.setattr(style_gen, "call_json", lambda *a, **k: {
            "palette_key": "ice_blue", "font_key": "segoe_bold", "reason": "x"})
        response = client.post("/api/channels/c/suggest-look",
                               headers={"X-CSRF-Token": self._csrf(client)})
        assert response.status_code == 200
        data = response.get_json()
        assert data["colors"]["highlight_color"] == "#5AC8FA"
        assert data["font_key"] == "segoe_bold"

    def test_every_colour_a_palette_sets_comes_back(self, client, monkeypatch):
        """The regression this guards: the palette gained title-card
        colours, `apply_to_style` set them, and this route's response
        didn't list them — so a suggestion visibly changed the captions
        and the outro and left the title card alone. Asserting against
        `apply_to_style` rather than a hardcoded list means the next field
        added to a palette can't slip through the same gap."""
        monkeypatch.setattr(style_gen, "call_json", lambda *a, **k: {
            "palette_key": "ice_blue", "font_key": "segoe_bold", "reason": "x"})
        response = client.post("/api/channels/c/suggest-look",
                               headers={"X-CSRF-Token": self._csrf(client)})

        class _Spy:
            def __setattr__(self, name, value):
                object.__setattr__(self, name, value)

        spy = _Spy()
        palettes.apply_to_style(spy, palettes.get("ice_blue"))
        written = {n for n in vars(spy) if n != "font_face"}
        assert written <= set(response.get_json()["colors"])

    def test_never_writes_to_the_channel(self, client, monkeypatch):
        """Suggesting is not saving. The route must be a pure read."""
        from core.channels import load_channels

        monkeypatch.setattr(style_gen, "call_json", lambda *a, **k: {
            "palette_key": "crimson", "font_key": "impact", "reason": "x"})
        before = load_channels(validate=False)["c"].style.highlight_color
        client.post("/api/channels/c/suggest-look",
                    headers={"X-CSRF-Token": self._csrf(client)})
        after = load_channels(validate=False)["c"].style.highlight_color
        assert before == after


class TestNewChannelGetsARandomLook:
    """A fresh channel used to always start on the same warm-gold default.
    A random pick from the curated set is safe by construction and stops
    every new channel looking identical from the moment it's created."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from core.channels import write_raw
        from web import create_app

        path = tmp_path / "channels.json"
        monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", path)
        monkeypatch.setattr("core.channel_admin.PROJECT_ROOT", tmp_path)
        write_raw({}, path)
        app = create_app()
        app.config.update(TESTING=True)
        with app.test_client() as test_client:
            yield test_client

    def _csrf(self, client):
        html = client.get("/").get_data(as_text=True)
        marker = 'name="csrf-token" content="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_the_style_comes_from_the_curated_set(self, client):
        from core.channels import load_channels

        client.post("/channels/new", data={"channel_display_name": "Mine",
                                           "csrf_token": self._csrf(client)})
        style = load_channels(validate=False)["mine"].style
        matches = [p for p in palettes.PALETTES if p.highlight_color == style.highlight_color]
        assert len(matches) == 1
        assert style.font_face in matches[0].font_faces

    def test_two_channels_are_not_guaranteed_the_same_look(self, monkeypatch):
        """Not a strict assertion on any one pair (a random draw can
        coincide), but across enough channels the set must vary."""
        import random

        from core import palettes as palettes_module

        seen = set()
        for seed in range(20):
            palette, face = palettes_module.random_choice(random.Random(seed))
            seen.add(palette.key)
        assert len(seen) > 1
