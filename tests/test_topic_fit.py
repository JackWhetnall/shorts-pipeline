"""
Films the channel can make well (decision 118). The owner, on 19 Oct: a
film about how mirrors flip an image "relies on visually accurate
representations, which cannot be guaranteed by the image generation";
the stop sign's stages and the pen cap lodged sideways were drawn wrong;
"visual errors like this kill the validity and trustworthiness of the
whole channel, so ideally we need to stop them from occurring at all".
And: "we need to make the overseer create new topics and subtopics when
the topic bank is running low".

- whoever writes a documentary channel's plan is told what it can make
  well; any other channel's plan writer isn't;
- every stage that makes a film is told the words carry it and the
  pictures can't be trusted with exact detail, and the picture check
  looks for a stated detail drawn wrong;
- the overseer sees the bank, prunes it and tops it up through one tool,
  only on a documentary channel, only skipping what's still waiting;
- its status says when a bank is running low.
"""

from __future__ import annotations

import json

import pytest

from core import curriculum, gallery, overseer
from core.channels import ChannelConfig
from pipeline.documentary import kinds


def _documentary(key="why", out=""):
    channel = ChannelConfig(key=key, channel_display_name="Why, Though?", format="documentary",
                            content_mode="topic", output_dir=out)
    channel.documentary.kind = "explainer"
    channel.documentary.overseen = True
    return channel


# --- the plan's writer ------------------------------------------------------------

def test_a_documentary_plans_writer_is_told_what_the_channel_can_make_well(monkeypatch):
    from pipeline import curriculum_gen
    asked = []

    def fake(system, user, schema, **kwargs):
        asked.append(" ".join(block.text for block in system))
        return {"subtopics": [], "topics": []}
    monkeypatch.setattr(curriculum_gen, "call_json", fake)
    plan = {"topics": [{"id": "u01", "title": "Your Strange Body", "level": "foundation", "summary": ""}],
            "subtopics": []}
    curriculum_gen.write_subtopics(_documentary(), plan, plan["topics"][0], 5)
    curriculum_gen.extend_outline(_documentary(), plan, 1)
    assert all("how a mirror flips" in prompt and "works by ear" in prompt for prompt in asked)
    asked.clear()
    shorts = ChannelConfig(key="mp", channel_display_name="Minute Pastor", style_prompt="Bible verses.")
    curriculum_gen.write_subtopics(shorts, plan, plan["topics"][0], 5)
    assert "how a mirror flips" not in asked[0]                    # another kind of channel: as before


# --- every stage of a film --------------------------------------------------------

def test_every_stage_of_a_film_is_told_the_words_carry_it():
    from pipeline.documentary import outline, pictures, pitch, script, stills
    assert "eyes shut" in script.SYSTEM and "can't be trusted with exact detail" in script.SYSTEM
    assert "Show, don't\n    caption" not in outline.SYSTEM and "can't be trusted" in outline.SYSTEM
    assert "5. A picture stays right however it's drawn" in pictures.SYSTEM
    assert "a detail its description states, drawn differently" in stills.FLAWS
    assert "contradicts or walks back" in pitch.SYSTEM
    assert "works by ear" in kinds.PITCH["explainer"]
    assert "side by side at their real scale" not in kinds.SCRIPT_SHAPE["explainer"]
    assert "side by side at scale" not in kinds.SCRIPT_DIRECTION["explainer"]
    assert "shown, not asked about" not in kinds.OUTLINE_WANT["explainer"]


# --- the overseer's topic bank ----------------------------------------------------

@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path / "out")
    channel = _documentary(out=str(tmp_path / "out" / "why"))
    quiz = ChannelConfig(key="buzz", channel_display_name="Pub Quiz Buzz", format="quiz", content_mode="topic")
    monkeypatch.setattr(overseer.channel_config, "load_channels", lambda *a, **k: {"why": channel, "buzz": quiz})
    curriculum.start("why", "Curious questions", [{"title": "Your Strange Body", "summary": "Bodies.",
                                                    "level": "foundation", "target_subtopics": 10}])
    curriculum.add_subtopics("why", "u01", [{"title": "Why Do We Get Hiccups?", "angle": "A fish reflex."},
                                            {"title": "Why Do Mirrors Flip Left-Right?", "angle": "A letter."},
                                            {"title": "Why Do We Yawn?", "angle": "Brain cooling."}])
    film = tmp_path / "out" / "why" / "longform" / "2026-10-17" / "why_hiccups.mp4"
    film.parent.mkdir(parents=True)
    film.write_bytes(b"film")
    gallery.save_stats(film, {"views": 29, "avg_view_percent": 9.4})
    curriculum._set("why", "t0001", status=curriculum.PUBLISHED, video_stem="why_hiccups")
    return channel


def test_the_overseer_sees_the_bank_with_the_channels_rules(bank):
    sheet = overseer.topics_sheet("why")
    assert kinds.TOPIC_FIT["explainer"] in sheet and "RUNNING LOW" in sheet
    assert "t0002 [u01] Why Do Mirrors Flip Left-Right? :: A letter." in sheet
    assert "t0001 Why Do We Get Hiccups?: 29 views, 9% of it watched on average" in sheet


def test_the_overseer_prunes_and_tops_up_the_bank_through_one_tool(bank):
    overseer.skip_subtopic("why", "t0002", "needs exact pictures")
    assert curriculum.find("why", "t0002")["status"] == curriculum.SKIPPED
    assert "(overseer: needs exact pictures)" in overseer.topics_sheet("why")
    with pytest.raises(SystemExit):
        overseer.skip_subtopic("why", "t0001", "made already")          # only a waiting one
    topic = overseer.add_topic("why", "Kitchen Mysteries", "Why food behaves the way it does.")
    assert topic["id"] == "u02" and topic["level"] == "foundation"
    added = overseer.add_subtopics("why", "u02", ["Why Does Bread Go Stale? :: Starch turns back into crystals.",
                                                  "Why Do We Yawn? :: Again.",           # already in the plan
                                                  "Why Does Popcorn Pop?"])
    assert [(s["title"], s["angle"]) for s in added] == [
        ("Why Does Bread Go Stale?", "Starch turns back into crystals."), ("Why Does Popcorn Pop?", "")]
    assert curriculum.find_topic("why", "u02")["filled"]               # the app won't write its own for it


def test_the_overseer_never_touches_another_kind_of_channels_plan(bank):
    with pytest.raises(SystemExit):
        overseer.add_topic("buzz", "Flags", "Flags of the world.")


def test_status_says_when_a_bank_is_running_low(bank, capsys, monkeypatch):
    monkeypatch.setattr(overseer, "status", lambda: [])
    overseer.main(["status"])
    assert "why topic bank: 2 films waiting to be made; RUNNING LOW" in capsys.readouterr().out
    overseer.main(["add-subtopics", "why", "u01", "Why Do We Blush? :: A signal we can't hide."])
    assert "added t0004: Why Do We Blush?" in capsys.readouterr().out


def test_the_checklist_and_the_nightly_task_cover_the_bank():
    guide = open("docs/overseer.md", encoding="utf-8").read()
    assert "## The topic bank (when it's running low)" in guide and "skip-subtopic" in guide
    assert "10. **Nothing depends on a picture being exact**" in guide
    assert json.dumps("change plans only with\n  the topic bank's commands")[1:-1] in json.dumps(guide)
