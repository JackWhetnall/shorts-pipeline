"""
Long quizzes kept ready by making shorts ahead, and banners in each
channel's own look (decision 084).

The owner: with random shorts "we dont actually have enough complete sets
to make long form videos yet ... if we want to have, say 3 long form
quizzes ready to go in advance, then we should have an option to generate
shorts until those quizzes are available", without picking "the most
efficient shorts" (the publishing order should stay natural). And "the
youtube banners seem to be identical between channels".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import scheduler
from pipeline import longform


def _rows(spec):
    return [{"stem": f"{c}_{d}_{i}", "category": c, "difficulty": d, "level": 1, "rank": (0, i),
             "video": SimpleNamespace(), "questions": [{"question": f"q{i}", "answer": f"a{c}{d}{i}"}]}
            for i, (c, d) in enumerate(spec)]


@pytest.fixture
def quizzes(monkeypatch):
    channel = SimpleNamespace(key="pqb", format="quiz",
                              quiz=SimpleNamespace(longform_rounds=3, longform_ready=3, longform_mixed_when_ready=True,
                                                   longform_category_when_ready=True),
                              publishing=SimpleNamespace(long_weekdays=[5], long_slots=["19:00"], weekdays=list(range(7)),
                                                         slots=["18:00"]))
    monkeypatch.setattr(longform.quiz, "labels", lambda ch: ["Easy", "Hard"])
    monkeypatch.setattr(longform.random, "shuffle", lambda x: None)
    return channel


def test_the_projection_counts_every_quiz_the_rounds_could_make(quizzes, monkeypatch):
    approved = _rows([(c, "Easy") for c in "ABCDEF"] + [(c, "Hard") for c in "AB"])
    review = _rows([("C", "Hard")])
    monkeypatch.setattr(longform, "available_rounds", lambda ch, series=None: [dict(r) for r in approved])
    monkeypatch.setattr(longform, "review_rounds", lambda ch: [dict(r) for r in review])
    monkeypatch.setattr(longform, "waiting_count", lambda ch, series=None: 1)
    p = longform.projection(quizzes)
    # Easy: two nights of three (A-F); Hard: A, B and C (in review) make a third.
    assert p["nights"] == 3
    # Categories: A, B and C have both levels.
    assert p["ladders"] == 3 and p["waiting"] == 1 and p["weeks"] == 7.0


def test_shorts_are_made_ahead_only_while_the_target_isnt_met(quizzes, monkeypatch):
    monkeypatch.setattr(longform, "projection", lambda ch: {"waiting": 1, "makeable": 1})
    assert scheduler._shorts_for_long_quizzes(quizzes, {"queued": 10})
    monkeypatch.setattr(longform, "projection", lambda ch: {"waiting": 1, "makeable": 2})
    assert not scheduler._shorts_for_long_quizzes(quizzes, {"queued": 10})
    monkeypatch.setattr(longform, "projection", lambda ch: {"waiting": 0, "makeable": 0})
    assert not scheduler._shorts_for_long_quizzes(quizzes, {"queued": 70})           # ten weeks ahead: enough
    quizzes.quiz.longform_ready = 0
    assert not scheduler._shorts_for_long_quizzes(quizzes, {"queued": 10})           # as before


def test_up_to_the_target_wait_at_once(quizzes, monkeypatch):
    monkeypatch.setattr(longform, "waiting_count", lambda ch, series=None: 2)
    assert scheduler._long_room(quizzes, longform.MIXED)
    monkeypatch.setattr(longform, "waiting_count", lambda ch, series=None: 3)
    assert not scheduler._long_room(quizzes, longform.MIXED)
    quizzes.quiz.longform_ready = 0
    monkeypatch.setattr(longform, "waiting", lambda ch, series: series == longform.MIXED)
    assert not scheduler._long_room(quizzes, longform.MIXED) and scheduler._long_room(quizzes, longform.CATEGORY)


def test_banners_are_drawn_in_each_channels_own_look(monkeypatch, tmp_path):
    from core import banner
    monkeypatch.setattr(banner, "CHANNELS_DIR", tmp_path)
    monkeypatch.setattr(banner, "channel_logo_dir", lambda key: tmp_path / key / "logo")
    monkeypatch.setattr(banner, "_words", lambda ch: ["Science", "Sport"])
    from core.channels import ChannelConfig
    quiz = ChannelConfig(key="q", channel_display_name="Pub Quiz Buzz", format="quiz")
    quiz.scenes.art = {"font_display": "Georgia", "background": "#F6EEDD"}
    talk = ChannelConfig(key="t", channel_display_name="Minute Pastor")
    a, b = banner.page_html(quiz, "Rounds any time", "brand"), banner.page_html(talk, "Daily verse", "brand")
    assert "class='stamp'" in a and "class='stamp'" not in b              # a quiz carries its stamp
    assert "Pub Quiz Buzz" in a and "Science" not in a and "Science" in b
    assert banner.picture(quiz) is None                                     # its board is its look


def test_a_banner_the_page_renderer_cant_draw_is_drawn_plainly(monkeypatch, tmp_path):
    from PIL import Image
    from core import banner
    from core.channels import ChannelConfig
    monkeypatch.setattr(banner, "CHANNELS_DIR", tmp_path)
    monkeypatch.setattr(banner, "channel_logo_dir", lambda key: tmp_path / key / "logo")

    def broken(*a, **k):
        raise RuntimeError("no browser")
    monkeypatch.setattr("pipeline.scenes.render.page_frame", broken)
    made = banner.make(ChannelConfig(key="c", channel_display_name="C"), "Tag")
    assert set(made) == set(banner.VARIANTS) and Image.open(made["picture"]).size == banner.SIZE
