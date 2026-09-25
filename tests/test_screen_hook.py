"""
The visual hook (the hook's punch as big text over the first seconds) and
the key words that pop in the captions.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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


def test_the_first_scene_waits_for_the_hook_text_to_go():
    from pipeline.scenes import stage
    plan = SimpleNamespace(channel=SimpleNamespace(style=Style()),
                           script=SimpleNamespace(screen_hook="Kill something inside"),
                           voiceover=SimpleNamespace(word_timings=_words("Paul says kill it. More.")))
    end = stage._hook_end(plan)
    assert end == pytest.approx(_words("Paul says kill it. More.")[3].end + 0.35)
    words = [(w.word, w.start) for w in _words("Paul says kill it. More.")]
    assert "starts on word 4" in stage._reserve_note(end, words)
    plan.script.screen_hook = ""
    assert stage._hook_end(plan) == 0.0


def test_anything_early_is_flagged_and_as_a_last_resort_held_back():
    # The owner: the big hook text must never cover a diagram; the picture
    # starts after it.
    from pipeline.scenes import writer
    scene = {"duration": 6.0, "actions": [
        {"target": "tri", "do": "draw", "at": 0.2, "dur": 1.0},
        {"target": "a", "do": "appear", "at": 0.9, "dur": 0.4},
        {"target": "tri", "do": "highlight", "at": 1.0, "dur": 0.5},    # not an entry
        {"target": "b", "do": "appear", "at": 3.0, "dur": 0.4}]}
    notes = writer.early_entries(scene, 2.0)
    assert len(notes) == 2 and "'tri' comes on at 0.2s" in notes[0]
    writer.hold_back(scene, 2.0)
    assert [a["at"] for a in scene["actions"]] == [2.0, 2.15, 1.0, 3.0]
    assert writer.early_entries(scene, 2.0) == []
    assert writer.early_entries(scene, 0.0) == []
