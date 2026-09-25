"""
The visual hook (the hook's punch as big text over the first seconds) and
the key words that pop in the captions.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.channels import Pacing, Style
from pipeline import assemble, script_gen
from pipeline.plan import Script, Segment, WordTiming


def _words(text, gap=0.3):
    return [WordTiming(w, i * gap, i * gap + 0.25) for i, w in enumerate(text.split())]


def test_the_hook_text_stays_while_the_opening_sentence_is_spoken():
    words = _words("A penny doubled daily beats a million. Then it keeps going for days.")
    start, end = assemble.screen_hook_window(words)
    assert start < 0.1
    assert end == words[6].end + 0.35          # "million." ends the first sentence


def test_the_hook_text_never_outstays_its_welcome():
    words = _words(" ".join(["word"] * 40))      # no sentence end at all
    assert assemble.screen_hook_window(words)[1] == assemble.SCREEN_HOOK_MAX_SECONDS


def test_no_hook_text_means_no_overlay():
    assert assemble.build_screen_hook("", _words("One two three."), Style()) == []


def test_the_hook_text_is_rendered_big_and_wraps_inside_the_frame():
    image = assemble.render_screen_hook("the length you can't measure", Style())
    assert image.shape[1] <= assemble.W and image.shape[0] > assemble.SCREEN_HOOK_SIZE


def test_only_the_marked_words_pop():
    words = _words("Square each short side then add them.")
    clips = assemble.build_caption_clips(words, Style(), Pacing(), emphasis=["square", "Side"])
    # [group base, Square, each, short, side, group base, then, add, them.]
    words_only = [c for i, c in enumerate(clips) if i not in (0, 5)]
    moving = [i for i, c in enumerate(words_only) if c.pos(0) != c.pos(1)]
    assert moving == [0, 3]                      # "Square" and "side", not the rest


def test_the_script_carries_the_screen_hook_and_emphasis_through_a_checkpoint():
    script = Script(segments=[Segment("a")], screen_hook="Kill something inside",
                    emphasis=["kill", "church"])
    back = Script.from_jsonable(script.to_jsonable())
    assert back.screen_hook == "Kill something inside" and back.emphasis == ["kill", "church"]
    assert Script.from_jsonable({"segments": [{"text": "a"}]}).emphasis == []


def test_the_writer_is_asked_for_both():
    props = script_gen._segments_schema()["properties"]
    assert {"screen_hook", "emphasis"} <= set(props)
    item = script_gen._batch_schema()["properties"]["scripts"]["items"]
    assert {"screen_hook", "emphasis"} <= set(item["required"])


def test_the_first_scene_is_told_to_keep_the_hooks_band_clear():
    from pipeline.scenes import stage
    plan = SimpleNamespace(channel=SimpleNamespace(style=Style()),
                           script=SimpleNamespace(screen_hook="Kill something inside"),
                           voiceover=SimpleNamespace(word_timings=_words("Paul says kill it. More.")))
    note = stage._opening_reserve(plan)
    assert "until 1.6s" in note or "until 1." in note
    plan.script.screen_hook = ""
    assert stage._opening_reserve(plan) == ""
