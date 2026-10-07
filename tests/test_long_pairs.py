"""
A long quiz's two versions go out one or the other, never both, and an
element's symbol is spelled out only when the question is about elements
(decision 078).

The owner, 7 Oct: publishing both versions of a long quiz risks being
seen as reused content, "approving both means that it is going to send
both out. and i cant discard one without it counting as a discard for the
analytics." And "Ra", the Egyptian sun god, was read out as the symbol
for radium.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from core import gallery, long_pairs, publish_queue
from core.channels import ChannelConfig
from pipeline import quiz


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi).astimezone()


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    monkeypatch.setattr(publish_queue, "STATE_PATH", tmp_path / "state.json")
    channel = ChannelConfig(key="q", channel_display_name="Quiz", format="quiz",
                            voice="21m00Tcm4TlvDq8ikWAM", style_prompt="x")
    channel.output_dir = str(tmp_path / "out" / "q")
    channel.publishing.enabled = True
    channel.publishing.long_slots = ["19:00"]
    channel.publishing.long_weekdays = [5]
    monkeypatch.setattr(gallery, "_channel_key_for", lambda path: "q")
    uploads = []
    monkeypatch.setattr(publish_queue.youtube, "connection", lambda key: {"connected": True})
    monkeypatch.setattr(publish_queue.youtube, "upload", lambda key, path, title, description, **k:
                        uploads.append(Path(path).name) or {"url": "https://youtu.be/x", "locked_private": False})

    def pair(episode=1):
        folder = Path(channel.output_dir) / "longform" / "2026-10-06"
        folder.mkdir(parents=True, exist_ok=True)
        made = {}
        for variant, stem in (("after_each", f"quiz_night_{episode}"),
                              ("at_end", f"quiz_night_{episode}_answers_at_end")):
            path = folder / f"{stem}.mp4"
            path.write_bytes(b"video")
            quiz.round_sidecar(path).write_text(json.dumps(
                {"longform": True, "variant": variant, "episode": episode}), encoding="utf-8")
            gallery.save_title_and_description(path, stem, "d")
            made[variant] = path
        return made["after_each"], made["at_end"]

    return type("W", (), {"channel": channel, "pair": staticmethod(pair), "uploads": uploads})


def test_approving_one_version_sets_the_other_aside_not_discarded(world):
    as_you_go, at_end = world.pair()
    assert long_pairs.partner(as_you_go) == at_end and long_pairs.partner(at_end) == as_you_go
    publish_queue.enqueue(at_end, approved_by="you")
    other = gallery.load_publish_info(as_you_go)
    assert gallery.is_set_aside(other) and not other["discarded"] and not other["queued_at"]
    counts = gallery.video_state_counts(world.channel.output_dir, long=True)
    assert (counts["queued"], counts["waiting"], counts["discarded"], counts["set_aside"]) == (1, 0, 0, 1)

    # Changing your mind swaps them.
    publish_queue.enqueue(as_you_go, approved_by="you")
    assert gallery.is_queued(gallery.load_publish_info(as_you_go))
    assert gallery.is_set_aside(gallery.load_publish_info(at_end))

    # Taking it out of the queue brings both back to review.
    publish_queue.unqueue(as_you_go)
    counts = gallery.video_state_counts(world.channel.output_dir, long=True)
    assert (counts["waiting"], counts["set_aside"]) == (2, 0)


def test_both_approved_before_pairing_only_one_goes_out(world):
    """The two Quiz Night 1 versions were both queued on 7 Oct, before this
    existed; whichever goes out first, the other never does."""
    as_you_go, at_end = world.pair()
    for path in (as_you_go, at_end):
        gallery.save_queue_state(path, queued_at="2026-10-07T14:51:00+00:00", approved_by="you")
    publish_queue.publish_due({"q": world.channel}, now=local(2026, 10, 10, 19, 1))
    publish_queue.publish_due({"q": world.channel}, now=local(2026, 10, 17, 19, 1))
    assert world.uploads == ["quiz_night_1.mp4"]
    assert gallery.is_set_aside(gallery.load_publish_info(at_end))
    with pytest.raises(Exception) as refused:
        publish_queue.enqueue(at_end, approved_by="you")
    assert "already gone out" in refused.value.user_message


def test_review_hides_a_version_set_aside_and_says_what_approving_does(world, monkeypatch):
    from web.blueprints import review
    as_you_go, at_end = world.pair(episode=2)
    monkeypatch.setattr("web.blueprints.review.load_channels", lambda validate=False: {"q": world.channel})
    note = long_pairs.note(at_end)
    assert "Answers at the end" in note and "sets the other version aside" in note
    assert "Suggested for this episode" in note                    # even episode: at the end
    publish_queue.enqueue(at_end, approved_by="you")
    names = [i["name"] for i in review._queue()]
    assert "quiz_night_2.mp4" not in names


def test_styles_are_compared_on_published_versions_only(world):
    as_you_go, at_end = world.pair()
    gallery.save_publish_info(as_you_go, {"youtube_url": "https://youtu.be/a"})
    gallery.save_stats(as_you_go, {"views": 120, "avg_view_percent": 40.0, "avg_view_seconds": 600})
    rows = {r["variant"]: r for r in long_pairs.compare(
        [{"path": p, "published": gallery.is_published(gallery.load_publish_info(p)),
          "stats": gallery.load_stats(p)} for p in (as_you_go, at_end)])}
    assert rows["after_each"]["videos"] == 1 and rows["after_each"]["avg_view_minutes"] == 10.0
    assert rows["at_end"]["videos"] == 0 and rows["at_end"]["views"] is None


def test_a_short_has_no_partner(world, tmp_path):
    short = Path(world.channel.output_dir) / "2026-10-06" / "science_hard.mp4"
    short.parent.mkdir(parents=True, exist_ok=True)
    short.write_bytes(b"v")
    assert long_pairs.partner(short) is None and long_pairs.note(short) == ""


@pytest.mark.parametrize("question, answer, spelled", [
    ("Which Egyptian god was the sun?", "Ra", {}),
    ("Who was the Egyptian sun god?", "Ra", {}),
    ("What is the chemical symbol for radium?", "Ra", {"Ra": "ar ay"}),
    ("Which element has the symbol Ra?", "Radium", {"Ra": "ar ay"}),
    ("What is the chemical symbol for gold?", "Au", {"Au": "ay you"}),
])
def test_an_answer_is_spelled_as_a_symbol_only_when_the_question_is_about_elements(question, answer, spelled):
    assert quiz.element_respellings([{"question": question, "answer": answer}]) == spelled
