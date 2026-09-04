"""
A real render, end to end, with the paid services stubbed out.

This exists for one reason: the caption rewrite is the riskiest change in
the codebase. Captions went from "redraw the whole group once per word"
to "draw the group once, then overlay just the active word", which means
every word's highlight now depends on a computed box position rather than
on being redrawn in place. A position that's off by a few pixels, or an
overlay that lands on the wrong line, is invisible to a unit test and
obvious to a viewer.

So this drives the real assembler over real footage and a real encode,
then checks the output is a genuine video of the right shape and
duration. It needs the footage library, and skips itself when there isn't
one, because it should never be the reason a checkout can't run its
tests.

Marked slow: it encodes video. Run with `-m "not slow"` to skip it.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.channels import ChannelConfig
from pipeline.plan import RenderPlan, Script, Seed, Segment, Voiceover, WordTiming

pytestmark = pytest.mark.slow

FPS = 44100


def _library_available() -> bool:
    from core.paths import LIBRARY_DB_PATH
    if not LIBRARY_DB_PATH.exists():
        return False
    from pipeline.footage import store
    from core.paths import LIBRARY_DIR
    return sum(1 for c in store.all_clips() if (LIBRARY_DIR / c.filename).exists()) >= 4


needs_library = pytest.mark.skipif(
    not _library_available(),
    reason="needs at least 4 clips in the footage library",
)


def _word_timings(sentences, start=0.0):
    """Evenly spaced words with realistic small gaps between them."""
    timings, t = [], start
    for sentence in sentences:
        for word in sentence.split():
            timings.append(WordTiming(word, t, t + 0.28))
            t += 0.34
        t += 0.4        # a real pause between segments
    return timings


@pytest.fixture
def plan(tmp_path):
    channel = ChannelConfig(
        key="render_test", channel_display_name="Render Test",
        content_mode="topic", voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p", topics=["x"],
    )
    channel.pacing.outro_seconds = 1.0
    channel.pacing.max_shot_seconds = 2.0

    sentences = ["The quiet moments matter more than we think.",
                 "Even a small pause changes how a sentence lands."]
    segments = [Segment(text=sentences[0], keywords=["quiet"], start=0.0, end=2.6),
                Segment(text=sentences[1], keywords=["pause"], start=2.6, end=5.4)]

    duration = 5.4
    samples = np.zeros((int(duration * FPS), 2), dtype=np.float32)

    plan = RenderPlan(channel=channel, seed=Seed(type="topic", topic="render test"),
                      interactive=False)
    plan.out_dir = tmp_path
    plan.stem = "render_test"
    plan.script = Script(segments=segments, citation=None)
    plan.voiceover = Voiceover(audio_path=tmp_path / "a.mp3",
                               word_timings=_word_timings(sentences),
                               samples=samples, fps=FPS)
    return plan


class TestCaptionLayout:
    """The overlay has to land exactly on the word it replaces."""

    def _style(self):
        from core.channels import Style
        return Style()

    def test_every_word_gets_a_box(self):
        from pipeline.assemble import layout_caption
        words = ["The", "quiet", "moments", "matter"]
        layout = layout_caption(words, self._style())
        assert len(layout.boxes) == len(words)

    def test_boxes_advance_left_to_right_within_a_line(self):
        from pipeline.assemble import layout_caption
        layout = layout_caption(["one", "two", "three"], self._style())
        xs = [box[0] for box in layout.boxes]
        assert xs == sorted(xs), "words on one line must not overlap or reverse"

    def test_wrapping_starts_a_new_line_lower_down(self):
        from pipeline.assemble import layout_caption
        # Long enough to wrap at the caption width.
        words = ["extraordinarily"] * 6
        layout = layout_caption(words, self._style())
        ys = sorted({box[1] for box in layout.boxes})
        assert len(ys) > 1, "this should have wrapped onto more than one line"
        assert ys == sorted(ys)

    def test_boxes_stay_inside_the_caption_width(self):
        from pipeline.assemble import layout_caption
        from pipeline.assemble import CAPTION_MAX_WIDTH
        layout = layout_caption("the quick brown fox jumps".split(), self._style())
        for x, _, width, _ in layout.boxes:
            assert x >= 0
            assert x + width <= CAPTION_MAX_WIDTH + 1

    def test_overlay_matches_its_box_size(self):
        from pipeline.assemble import layout_caption, render_word_overlay
        style = self._style()
        layout = layout_caption(["shepherd"], style)
        overlay = render_word_overlay("shepherd", layout.boxes[0], style)
        # Box width plus stroke padding on both sides.
        assert overlay.shape[1] >= int(layout.boxes[0][2])
        assert overlay.shape[2] == 4, "must be RGBA so it composites over the base"


class TestCaptionClips:
    def test_one_base_clip_per_group_plus_one_overlay_per_word(self):
        from core.channels import Pacing, Style
        from pipeline.assemble import build_caption_clips, group_words

        timings = _word_timings(["one two three four five six"])
        pacing, style = Pacing(), Style()
        groups = group_words(timings, pacing)
        clips = build_caption_clips(timings, style, pacing)
        assert len(clips) == len(groups) + len(timings)

    def test_a_words_highlight_holds_until_the_next_word_starts(self):
        """The gap between spoken words otherwise leaves no clip active,
        which reads as the caption flashing off with every word."""
        from core.channels import Pacing, Style
        from pipeline.assemble import build_caption_clips

        # Gaps of 0.1s, below the 0.25s pause threshold, so all three
        # words stay in one caption group. (Gaps above the threshold
        # would legitimately split them into separate groups, and every
        # word would then be its own group's last.)
        timings = [WordTiming("one", 0.0, 0.2),
                   WordTiming("two", 0.3, 0.5),
                   WordTiming("three", 0.6, 0.8)]
        clips = build_caption_clips(timings, Style(), Pacing())
        assert len(clips) == 4, "expected one group base plus three overlays"
        overlays = clips[1:]        # clips[0] is the group base
        assert overlays[0].end == pytest.approx(0.3)   # not 0.2 — holds into the gap
        assert overlays[1].end == pytest.approx(0.6)
        assert overlays[2].end == pytest.approx(0.8)   # last word ends at its own end

    def test_a_real_pause_still_ends_the_caption(self):
        """The caption is supposed to disappear at a real pause — that's
        what splits groups in the first place."""
        from core.channels import Pacing, Style
        from pipeline.assemble import build_caption_clips

        timings = [WordTiming("one", 0.0, 0.2),
                   WordTiming("two", 1.5, 1.7)]      # 1.3s gap, well past the threshold
        clips = build_caption_clips(timings, Style(), Pacing())
        assert len(clips) == 4, "two groups, each with a base and one overlay"
        assert clips[0].end == pytest.approx(0.2), "first caption must end at the pause"


@needs_library
class TestFullRender:
    def test_produces_a_real_video(self, plan, monkeypatch):
        from pathlib import Path
        from core.paths import LIBRARY_DIR
        from pipeline import assemble
        from pipeline.footage import library, store

        clips = [c for c in store.all_clips() if (LIBRARY_DIR / c.filename).exists()][:6]

        def fake_assign(segments, shot_counts, avoid_imagery=None):
            names, i = [], 0
            for count in shot_counts:
                names.append([clips[(i + n) % len(clips)].filename for n in range(count)])
                i += count
            return library.MatchOutcome(picks=names)

        monkeypatch.setattr(library, "assign_clips", fake_assign)
        monkeypatch.setattr(library, "mark_used", lambda *a, **k: None)

        assemble.run(plan)

        out = plan.video_path
        assert out.exists(), "no video was written"
        assert out.stat().st_size > 10_000, "the video is suspiciously small"

        from moviepy.editor import VideoFileClip
        rendered = VideoFileClip(str(out))
        try:
            assert (rendered.w, rendered.h) == (1080, 1920)
            # Narration plus the outro card.
            assert rendered.duration == pytest.approx(5.4 + 1.0, abs=0.3)
            assert rendered.audio is not None, "audio was not muxed in"
            # A frame from the middle should be real footage, not black.
            frame = rendered.get_frame(3.0)
            assert frame.mean() > 5, "the frame is black — footage didn't composite"
        finally:
            rendered.close()

    def test_no_temp_files_are_left_behind(self, plan, monkeypatch):
        from core.paths import LIBRARY_DIR
        from pipeline import assemble
        from pipeline.footage import library, store

        clips = [c for c in store.all_clips() if (LIBRARY_DIR / c.filename).exists()][:6]
        monkeypatch.setattr(library, "assign_clips", lambda s, counts, a=None:
                            library.MatchOutcome(picks=[[clips[i].filename for i in range(c)]
                                                        for c in counts]))
        monkeypatch.setattr(library, "mark_used", lambda *a, **k: None)

        assemble.run(plan)
        leftovers = list(plan.out_dir.glob("*_TEMP_*"))
        assert not leftovers, f"temp files left behind: {leftovers}"
