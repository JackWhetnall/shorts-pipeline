"""
A topic plan the owner shapes (decision 074).

The owner, making a history channel: the draft "came up with topics (a
fixed number and fixed number of subtopics - with topic titles
uneditable)" and was "still focussed on shorts". "American presidents may
have 15 people who are worth talking about, but Famous scientists may
have 50": a base number of videos per topic, and the room to give any one
topic more.
"""

from __future__ import annotations

import pytest

from core import curriculum, drafts
from core.channels import ChannelConfig


@pytest.fixture
def plan(tmp_path, monkeypatch):
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    curriculum.start("c", "People", [{"title": "Presidents", "summary": "US", "level": "foundation",
                                      "target_subtopics": 10}])
    curriculum.add_subtopics("c", "u01", [{"title": "Washington"}, {"title": "Adams"}])
    return ChannelConfig(key="c", channel_display_name="C", content_mode="topic", voice="v",
                         style_prompt="p")


def test_the_drafted_topics_can_be_rewritten_reordered_and_added_to():
    drafted = [{"title": "Presidents", "summary": "US", "level": "foundation", "target_subtopics": 15},
               {"title": "Scientists", "summary": "", "level": "intermediate", "target_subtopics": 40}]
    edited = drafts.outline_from_text(
        "Scientists: physics and chemistry\n\n- Prime ministers\nPresidents\nscientists: again", drafted)
    assert [t["title"] for t in edited] == ["Scientists", "Prime ministers", "Presidents"]
    assert edited[0]["summary"] == "physics and chemistry" and edited[0]["level"] == "intermediate"
    assert edited[2]["summary"] == "US" and edited[1]["level"] == "intermediate"
    assert drafts.outline_from_text(None, drafted) is drafted


def test_every_topic_starts_with_the_base_and_grows_on_its_own(plan, monkeypatch):
    from pipeline import curriculum_gen
    asked = []

    def fake(channel, data, topic, count=None):
        asked.append(count)
        have = len(curriculum.subtopics("c", topic_id=topic["id"]))
        return [{"title": f"Person {have + i}"} for i in range(count)]
    monkeypatch.setattr(curriculum_gen, "write_subtopics", fake)
    written = curriculum_gen.more_for_topic(plan, curriculum.find_topic("c", "u01"), 35)
    assert len(written) == 35 and asked == [30, 5]               # in calls the writer can manage
    assert len(curriculum.subtopics("c", topic_id="u01")) == 37
    curriculum.set_topic_target("c", "u01", 37)
    assert curriculum.find_topic("c", "u01")["target_subtopics"] == 37


def test_a_documentary_draft_becomes_a_long_form_channel(tmp_path, monkeypatch):
    from core.channels import Documentary
    channel = ChannelConfig(key="h", content_mode="topic", voice="v", style_prompt="p")
    drafts._set_up_documentary(channel, {"minutes": 10, "teasers": 3}, {"minutes": "12", "teasers": "2"})
    assert channel.format == "documentary" and channel.animation.enabled
    assert (channel.documentary.minutes, channel.documentary.teasers) == (12, 2)
    assert Documentary().minutes == 10 and Documentary().teasers == 3


def test_a_documentary_must_be_a_sensible_length(plan):
    from core.errors import ConfigError
    channel = ChannelConfig(key="c", content_mode="topic", format="documentary",
                            voice="21m00Tcm4TlvDq8ikWAM", style_prompt="p")
    channel.validate()
    channel.documentary.minutes = 90
    with pytest.raises(ConfigError):
        channel.validate()


def test_the_plan_page_writes_more_for_one_topic(plan, monkeypatch):
    from pipeline import curriculum_gen
    from web import create_app
    monkeypatch.setattr("web.blueprints.curriculum.channel_or_404", lambda key: plan)
    monkeypatch.setattr(curriculum_gen, "write_subtopics",
                        lambda channel, data, topic, count=None: [{"title": f"Extra {i}"} for i in range(count)])
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    html = client.get("/").get_data(as_text=True)
    marker = 'name="csrf-token" content="'
    token = html[html.index(marker) + len(marker):html.index('"', html.index(marker) + len(marker))]
    response = client.post("/api/channels/c/curriculum/u01/more", json={"count": 4},
                           headers={"X-CSRF-Token": token})
    assert response.get_json() == {"ok": True, "added": 4}
    assert curriculum.find_topic("c", "u01")["target_subtopics"] == 10   # 6 now, base 10 kept
