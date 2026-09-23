"""
`core.backgrounds`: blur/dim, and the live preview that reads the same
transform without writing anything to disk.

The Look settings page used to have no way to see what dragging Blur or
Dim would do short of clicking Apply and reloading the plain background
image — the sliders moved, nothing on screen changed until you committed.
`preview_image()` exists to answer "what would Apply save" for a value
that hasn't been applied yet, so `pipeline.assemble.card_background` can
composite it into the live title/outro card preview as the slider moves.

The one property worth pinning down is that a preview and a real Apply at
the same blur/dim produce the SAME pixels — both go through
`_render_edited`, so there is no way for the preview to promise something
Apply doesn't deliver.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from core import backgrounds


@pytest.fixture
def channels_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("core.backgrounds.CHANNELS_DIR", tmp_path)
    return tmp_path


def _write_original(channel_key: str, size=(600, 900)):
    """A real, decodable picture — not a downloaded one, since nothing
    here should depend on the network. A checkerboard rather than a flat
    fill: a Gaussian blur does nothing visible to a uniform colour, which
    would make every blur test pass by accident."""
    path = backgrounds.original_path(channel_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    pixels = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    pixels[::20, :, :] = 255
    pixels[:, ::20, :] = 255
    Image.fromarray(pixels).save(path, format="JPEG", quality=95)
    return path


class TestPreviewImage:
    def test_none_when_there_is_no_original_yet(self, channels_dir):
        assert backgrounds.preview_image("nope") is None

    def test_matches_what_apply_would_compute(self, channels_dir):
        """The whole point: the preview and the transform Apply saves are
        pixel-identical for the same blur/dim, because both are built by
        the one shared `_render_edited`. Compared in memory, not against
        the file Apply writes — that round-trips through a lossy JPEG
        save, which would make this a test of JPEG quantization noise
        instead of a test of the two code paths agreeing."""
        source = _write_original("c")
        preview = backgrounds.preview_image("c", blur=5, dim=20)
        with Image.open(source) as original:
            expected = backgrounds._render_edited(original.convert("RGB"), 5, 20)
        assert np.array_equal(np.array(preview), np.array(expected))

    def test_apply_edits_saves_the_same_transform(self, channels_dir):
        """Loosely, because the saved file is a lossy JPEG: the preview
        and what got saved should still be close enough that nobody would
        call them different pictures."""
        _write_original("c")
        preview = np.array(backgrounds.preview_image("c", blur=5, dim=20).convert("RGB"),
                           dtype=np.int16)
        backgrounds.apply_edits("c", blur=5, dim=20)
        with Image.open(backgrounds.path("c")) as saved:
            saved_arr = np.array(saved.convert("RGB"), dtype=np.int16)
        assert np.abs(preview - saved_arr).mean() < 2

    def test_always_reads_from_the_original_not_the_last_preview(self, channels_dir):
        """A preview must never compound: asking for blur=0 after already
        having asked for blur=20 must come back exactly as blurry as a
        fresh blur=0 request, not "20 then undone", which for a Gaussian
        blur is not the same image at all."""
        _write_original("c")
        first = np.array(backgrounds.preview_image("c", blur=20, dim=0).convert("RGB"))
        back_to_zero = np.array(backgrounds.preview_image("c", blur=0, dim=0).convert("RGB"))
        fresh_zero = np.array(backgrounds.preview_image("c", blur=0, dim=0).convert("RGB"))
        assert not np.array_equal(first, back_to_zero)
        assert np.array_equal(back_to_zero, fresh_zero)

    def test_writes_nothing_to_disk(self, channels_dir):
        _write_original("c")
        backgrounds.preview_image("c", blur=15, dim=40)
        assert not backgrounds.path("c").exists()
        assert not backgrounds.meta_path("c").exists()

    def test_does_not_disturb_an_already_applied_picture(self, channels_dir):
        """Dragging the slider while a channel already has a saved
        background must not touch the file the real render actually
        reads, until Apply is pressed again."""
        _write_original("c")
        backgrounds.apply_edits("c", blur=3, dim=10)
        before = backgrounds.path("c").read_bytes()
        backgrounds.preview_image("c", blur=25, dim=80)
        assert backgrounds.path("c").read_bytes() == before

    @pytest.mark.parametrize("blur,dim", [(-5, -5), (999, 999)])
    def test_out_of_range_values_are_clamped_like_apply_edits(self, channels_dir, blur, dim):
        source = _write_original("c")
        preview = backgrounds.preview_image("c", blur=blur, dim=dim)
        applied = backgrounds.apply_edits("c", blur=blur, dim=dim)
        assert applied["blur"] == max(0, min(backgrounds.MAX_BLUR, blur))
        assert applied["dim"] == max(0, min(backgrounds.MAX_DIM, dim))
        with Image.open(source) as original:
            expected = backgrounds._render_edited(
                original.convert("RGB"), applied["blur"], applied["dim"])
        assert np.array_equal(np.array(preview), np.array(expected))

    def test_the_frame_is_filled_to_the_video_aspect_ratio(self, channels_dir):
        from core.paths import FRAME_HEIGHT, FRAME_WIDTH

        _write_original("c", size=(300, 300))  # a square source, cropped to 9:16
        preview = backgrounds.preview_image("c")
        assert preview.size == (FRAME_WIDTH, FRAME_HEIGHT)
