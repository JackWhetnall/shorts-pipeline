"""
`web.forms.apply_channel_form`: the settings form's own sparse-write
contract — a field the form doesn't carry must never be touched, and a
value it can't validate must never be written raw. Direct against the
function rather than the HTTP route: it only needs something with
`.get`/`in`, and a plain dict satisfies both, so no Flask app is needed
to exercise it.
"""

from __future__ import annotations

from core.channels import ChannelConfig
from web.forms import apply_channel_form


def _channel(**overrides):
    channel = ChannelConfig(key="c", content_mode="topic",
                            voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p")
    for key, value in overrides.items():
        setattr(channel, key, value)
    return channel


class TestOrdering:
    def test_the_marker_gates_every_field(self):
        """Without ordering_present, stray ordering_* keys (a form from a
        page that doesn't carry this section, say) must not touch it."""
        channel = _channel()
        apply_channel_form(channel, {"ordering_mode": "natural"})
        assert channel.ordering.mode == "structured"

    def test_valid_values_are_applied(self):
        channel = _channel()
        apply_channel_form(channel, {
            "ordering_present": "1",
            "ordering_mode": "natural",
            "ordering_topic_order": "random",
            "ordering_subtopic_order": "random",
            "ordering_grouping": "round_robin",
            "ordering_stickiness": "0.3",
        })
        assert channel.ordering.mode == "natural"
        assert channel.ordering.topic_order == "random"
        assert channel.ordering.subtopic_order == "random"
        assert channel.ordering.grouping == "round_robin"
        assert channel.ordering.stickiness == 0.3

    def test_an_unrecognised_value_leaves_the_field_alone(self):
        channel = _channel()
        apply_channel_form(channel, {
            "ordering_present": "1", "ordering_mode": "not_a_real_mode"})
        assert channel.ordering.mode == "structured"

    def test_a_missing_field_leaves_it_at_whatever_it_already_was(self):
        channel = _channel(ordering=_channel().ordering)
        channel.ordering.grouping = "round_robin"
        apply_channel_form(channel, {"ordering_present": "1", "ordering_mode": "natural"})
        assert channel.ordering.grouping == "round_robin"


class TestTitleCardPlacementAndTopic:
    def test_a_valid_placement_is_applied(self):
        channel = _channel()
        apply_channel_form(channel, {"style_title_card_placement": "after_intro"})
        assert channel.style.title_card_placement == "after_intro"

    def test_an_unrecognised_placement_leaves_the_default(self):
        channel = _channel()
        apply_channel_form(channel, {"style_title_card_placement": "midway"})
        assert channel.style.title_card_placement == "start"

    def test_show_topic_is_applied_through_the_flags_marker(self):
        channel = _channel()
        apply_channel_form(channel, {
            "style_flags_present": "1", "style_title_card_show_topic": "on"})
        assert channel.style.title_card_show_topic is True

    def test_unchecking_show_topic_turns_it_off(self):
        channel = _channel()
        channel.style.title_card_show_topic = True
        apply_channel_form(channel, {"style_flags_present": "1"})
        assert channel.style.title_card_show_topic is False

    def test_without_the_flags_marker_show_topic_is_untouched(self):
        channel = _channel()
        channel.style.title_card_show_topic = True
        apply_channel_form(channel, {})
        assert channel.style.title_card_show_topic is True


class TestContextDepth:
    def test_scope_and_count_apply_through_the_continuity_marker(self):
        channel = _channel()
        apply_channel_form(channel, {
            "continuity_present": "1", "build_on_previous": "on",
            "context_scope": "recent_topics", "context_topics": "5"})
        assert channel.build_on_previous is True
        assert channel.context_scope == "recent_topics"
        assert channel.context_topics == 5

    def test_an_unrecognised_scope_is_ignored(self):
        channel = _channel()
        apply_channel_form(channel, {
            "continuity_present": "1", "context_scope": "everything_ever"})
        assert channel.context_scope == "topic"

    def test_without_the_marker_nothing_here_is_touched(self):
        channel = _channel(context_scope="all", context_topics=9)
        apply_channel_form(channel, {})
        assert channel.context_scope == "all"
        assert channel.context_topics == 9
