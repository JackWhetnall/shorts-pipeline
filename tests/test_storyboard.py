"""
Storyboards: the next few videos written ahead to look at before they're
made (core.storyboard, decision 073).

The owner (6 Oct): "the next ~3 unmade videos can be pre-approved or
edited ... any storyboard not pre-reviewed is deemed a pass and therefore
can be made, so as not to introduce a bottleneck". What's tested: the
next three are the three that will be made, and stay put however the
channel orders; a storyboard is the script the video is made from, so
edits carry through; approval is a mark, never a gate; and they're
written ahead only for channels that publish, and not for one being made.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import curriculum, ordering, storyboard
from core.channels import ChannelConfig


@pytest.fixture
def plan(tmp_path, monkeypatch):
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    curriculum.start("c", "Testing things", [
        {"title": "Basics", "summary": "The obvious ground.", "level": "foundation", "target_subtopics": 3},
        {"title": "Middle", "summary": "Builds on it.", "level": "intermediate", "target_subtopics": 2}])
    curriculum.add_subtopics("c", "u01", [{"title": "First thing", "angle": "a"},
                                          {"title": "Second thing", "angle": "b"},
                                          {"title": "Third thing", "angle": "c"}])
    curriculum.add_subtopics("c", "u02", [{"title": "Fourth thing", "angle": "d"},
                                          {"title": "Fifth thing", "angle": "e"}])
    monkeypatch.setattr("core.jobs.active_in_order", lambda: [])
    return ChannelConfig(key="c", channel_display_name="C", content_mode="topic",
                         voice="v", style_prompt="p")


def _script(*lines):
    return {"citation": None, "title_options": ["A title"], "description_body": "",
            "segments": [{"text": t, "shot_brief": f"brief {i}", "keywords": ["k"], "start": 0.0, "end": 0.0}
                         for i, t in enumerate(lines)]}


def test_the_next_three_are_the_ones_that_will_be_made(plan):
    assert [r["title"] for r in storyboard.upcoming(plan)] == ["First thing", "Second thing", "Third thing"]
    assert ordering.choose_next_subtopic(plan)["title"] == "First thing"


def test_a_random_channel_shows_the_same_three_and_makes_them_in_that_order(plan):
    import random
    plan.ordering.topic_order = "random"
    plan.ordering.subtopic_order = "random"
    first = [r["id"] for r in storyboard.upcoming(plan)]
    for seed in range(5):
        random.seed(seed)
        assert [r["id"] for r in storyboard.upcoming(plan)] == first
        assert ordering.choose_next_subtopic(plan)["id"] == first[0]


def test_make_next_goes_to_the_front(plan):
    storyboard.upcoming(plan)
    fifth = next(s for s in curriculum.subtopics("c") if s["title"] == "Fifth thing")
    curriculum.move_to_front("c", fifth["id"])
    assert storyboard.upcoming(plan)[0]["title"] == "Fifth thing"


def test_once_one_is_made_the_next_moves_up(plan):
    first, second, third = storyboard.upcoming(plan)
    curriculum.claim("c", first["id"])
    assert [r["id"] for r in storyboard.upcoming(plan)][:2] == [second["id"], third["id"]]


def test_approval_is_a_mark_not_a_gate(plan):
    row = storyboard.upcoming(plan)[0]
    curriculum.set_script("c", row["id"], _script("One.", "Two."))
    assert not storyboard.approved(curriculum.find("c", row["id"]))
    curriculum.mark_storyboard("c", row["id"])
    assert storyboard.approved(curriculum.find("c", row["id"]))
    # Whether looked at or not, it's what's made next.
    assert ordering.choose_next_subtopic(plan)["id"] == row["id"]
    # New words haven't been looked at.
    curriculum.set_script("c", row["id"], _script("Three."))
    assert not storyboard.approved(curriculum.find("c", row["id"]))


def test_a_quiz_storyboard_is_approved_when_every_question_is(plan):
    row = {"script": {"quiz": {"questions": [{"approved": True}, {"approved": False}]}}}
    assert not storyboard.approved(row)
    row["script"]["quiz"]["questions"][1]["approved"] = True
    assert storyboard.approved(row)


def test_edits_are_kept_in_the_script_the_video_is_made_from(plan):
    row = storyboard.upcoming(plan)[0]
    curriculum.set_script("c", row["id"], _script("One.", "Two."))
    storyboard.edit(plan, row["id"], ["One, better.", "Two."], ["brief 0", "a candle on a sill"])
    script = curriculum.find("c", row["id"])["script"]
    assert [s["text"] for s in script["segments"]] == ["One, better.", "Two."]
    assert script["segments"][1]["shot_brief"] == "a candle on a sill"
    assert script["segments"][1]["keywords"] == [] and script["segments"][0]["keywords"] == ["k"]
    assert script["title_options"] == ["A title"]
    assert storyboard.approved(curriculum.find("c", row["id"]))
    # The pipeline's own reader takes it.
    from pipeline import script_gen
    seed = SimpleNamespace(topic_id=row["id"])
    stored = script_gen._stored_script(SimpleNamespace(channel=plan, seed=seed))
    assert stored.segments[0].text == "One, better."


def test_an_edit_that_empties_a_line_is_refused(plan):
    from core.errors import PipelineError
    row = storyboard.upcoming(plan)[0]
    curriculum.set_script("c", row["id"], _script("One.", "Two."))
    with pytest.raises(PipelineError):
        storyboard.edit(plan, row["id"], ["", "Two."], ["a", "b"])


def test_missing_ones_are_written_and_one_being_made_is_left(plan, monkeypatch):
    from pipeline import script_gen
    rows = storyboard.upcoming(plan)
    monkeypatch.setattr("core.jobs.active_in_order",
                        lambda: [{"channel_key": "c", "seed": {"topic_id": rows[0]["id"]}}])
    asked = []

    def fake_write(channel, topic, subtopics):
        asked.extend(s["id"] for s in subtopics)
        return [{"subtopic_id": s["id"], "script": _script(f"For {s['title']}.")} for s in subtopics]
    monkeypatch.setattr(script_gen, "write_scripts", fake_write)
    assert storyboard.prepare(plan) == 2
    assert asked == [rows[1]["id"], rows[2]["id"]]
    assert curriculum.find("c", rows[1]["id"])["script"]["segments"][0]["text"] == "For Second thing."
    assert storyboard.prepare(plan) == 0


def test_written_again_with_a_note(plan, monkeypatch):
    from pipeline import script_gen
    row = storyboard.upcoming(plan)[0]
    curriculum.set_script("c", row["id"], _script("Old."))
    curriculum.mark_storyboard("c", row["id"])
    seen = {}

    def fake_regenerate(channel, topic, subtopic, siblings, instruction=""):
        seen["note"] = instruction
        return _script("New.")
    monkeypatch.setattr(script_gen, "regenerate_script", fake_regenerate)
    storyboard.write(plan, curriculum.find("c", row["id"]), "a stronger opening")
    assert seen["note"] == "a stronger opening"
    fresh = curriculum.find("c", row["id"])
    assert fresh["script"]["segments"][0]["text"] == "New." and not storyboard.approved(fresh)


def test_written_ahead_only_for_channels_that_publish_and_at_most_hourly(plan, monkeypatch):
    started = []
    monkeypatch.setattr(storyboard, "start", lambda channels, batch=True: started.append(
        ([c.key for c in channels], batch)) or True)
    monkeypatch.setattr(storyboard, "_last_auto", 0.0)
    plan.publishing.enabled = False
    assert not storyboard.keep_up({"c": plan})
    plan.publishing.enabled = True
    monkeypatch.setattr(storyboard, "_last_auto", 0.0)
    assert storyboard.keep_up({"c": plan})
    assert started == [(["c"], True)]                        # at batch prices
    assert not storyboard.keep_up({"c": plan})               # not again within the hour


class TestPage:
    @pytest.fixture
    def client(self, plan, monkeypatch):
        from web import create_app
        monkeypatch.setattr("web.blueprints.storyboard.channel_or_404", lambda key: plan)
        monkeypatch.setattr("web.blueprints.storyboard.storyboard.writing", lambda key: False)
        app = create_app()
        app.config.update(TESTING=True)
        return app.test_client()

    def _token(self, html: str) -> str:
        marker = 'name="csrf-token" content="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_the_page_shows_lines_and_shot_briefs_and_approves(self, client, plan):
        row = storyboard.upcoming(plan)[0]
        curriculum.set_script("c", row["id"], _script("Spoken words here."))
        page = client.get("/channels/c/coming-up")
        html = page.get_data(as_text=True)
        assert page.status_code == 200
        assert "Spoken words here." in html and "brief 0" in html and "Not written yet" in html
        headers = {"X-CSRF-Token": self._token(html)}
        response = client.post(f"/channels/c/coming-up/{row['id']}/approve", headers=headers)
        assert response.status_code == 302
        assert storyboard.approved(curriculum.find("c", row["id"]))
        response = client.post(f"/channels/c/coming-up/{row['id']}/edit", headers=headers,
                               data={"text": ["Changed words."], "shot_brief": ["brief 0"]})
        assert response.status_code == 302
        assert curriculum.find("c", row["id"])["script"]["segments"][0]["text"] == "Changed words."
