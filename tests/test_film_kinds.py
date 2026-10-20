"""
Two more kinds of film (decision 122), so two new channels don't share
Why, Though?'s mystery-and-payoff shape: a working day (a job from the
past, shift by shift) and an exposé (history's naughty bits, the polite
version against the truth: suggestive, never explicit, decision 123).

- every writer's table has both;
- each reaches the plan, script and editor prompts of a channel that
  makes it, and the story and explainer prompts are as they were;
- both are explainers underneath: fact-checked, held to an explainer's
  opening and given its picture rules;
- a channel can be set to either.
"""

from __future__ import annotations

from core.channels import ChannelConfig
from pipeline.documentary import editor, kinds, outline, script

TABLES = ("TOPIC_FIT", "PITCH", "OUTLINE_WANT", "OUTLINE_START", "OUTLINE_SOUND", "SCRIPT_SHAPE",
          "SCRIPT_DIRECTION", "SCRIPT_CARDS", "CRITIC_MOMENTUM")


def _channel(kind):
    channel = ChannelConfig(key="c", channel_display_name="C", format="documentary")
    channel.documentary.kind = kind
    return channel


def test_every_table_has_every_kind():
    for name in TABLES:
        assert set(getattr(kinds, name)) == set(kinds.KINDS), name
    assert set(kinds.LABELS) == set(kinds.KINDS)


def test_each_kind_reaches_its_writers():
    day, expose = _channel("working_day"), _channel("expose")
    assert "time sheet" in outline.system_text(day) and "deadpan guide" in script.system_text(day)
    assert "gossip with receipts" in outline.system_text(expose)
    assert "flirtatious friend" in " ".join(script.system_text(expose).split())
    assert "anything explicit or vulgar scores 1" in " ".join(editor.critic_text("expose").split())
    # The two kinds there were are untouched.
    assert "detective story about an idea" in outline.system_text(_channel("explainer"))
    assert "time sheet" not in outline.system_text(_channel("story"))


def test_both_are_explainers_underneath():
    assert kinds.family("working_day") == kinds.family("expose") == "explainer"
    assert kinds.family("story") == kinds.family("anything else") == "story"
    opening = {"scenes": [{"chapter": 1, "narration": "What did a bath cost in 1500?"}]}
    for kind in ("working_day", "expose"):
        assert any("Open on proof" in p for p in editor.checks(opening, {}, kind=kind).get(1, []))
    assert not any("Open on proof" in p for p in editor.checks(opening, {}, kind="story").get(1, []))


def test_a_channel_can_be_set_to_either():
    from web.forms import apply_channel_form
    channel = _channel("explainer")
    for kind in ("working_day", "expose"):
        apply_channel_form(channel, {"documentary_present": "1", "documentary_kind": kind})
        assert channel.documentary.kind == kind and kinds.of(channel) == kind
    apply_channel_form(channel, {"documentary_present": "1", "documentary_kind": "nonsense"})
    assert channel.documentary.kind == "expose"
    assert kinds.of(_channel("nonsense")) == "story"
