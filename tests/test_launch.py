"""
`core.launch`: where a channel is between an idea and publishing itself.

Every stage is computed from what's true, so the tests set up a true
state and read the answer: nothing is ever "marked done" except a
deliberate skip, which must show as skipped, never as done.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core import gallery, launch
from core.channels import ChannelConfig


@pytest.fixture
def channel(tmp_path, monkeypatch):
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    monkeypatch.setattr("core.gallery._sync_script_history", lambda *a: None)
    ch = ChannelConfig(key="c", voice="21m00Tcm4TlvDq8ikWAM", style_prompt="x", topics=["t"])
    ch.output_dir = str(tmp_path / "out" / "c")
    state = {"logo": False, "connected": False, "stats": False}
    monkeypatch.setattr(launch.assets, "has_logo", lambda key: state["logo"])
    monkeypatch.setattr(launch.youtube, "connection",
                        lambda key: {"connected": state["connected"], "stats": state["stats"],
                                     "account": "me@example.com", "connected_at": ""})
    return SimpleNamespace(config=ch, state=state)


def _video(channel, name, gate_passed, decision):
    path = Path(channel.output_dir) / "2026-09-24" / f"{name}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    gallery.save_report(path, {"gate": {"passed": gate_passed, "reasons": []}})
    if decision == "published":
        gallery.save_publish_info(path, {"youtube_url": "https://youtu.be/AAAAAAAAAAA"})
    elif decision == "discarded":
        gallery.set_discarded(path, True, "script")
    return path


def _ids(stages, attr):
    return [s.id for s in stages if getattr(s, attr)]


def test_a_new_channel_starts_at_its_first_real_gap(channel):
    ch = channel.config
    ch.style_prompt = ""
    stages, _ = launch.stages(ch)
    assert launch.current(stages).id == "content"
    assert "style prompt" in launch.current(stages).detail

    ch.style_prompt = "x"
    stages, _ = launch.stages(ch)
    assert launch.current(stages).id == "sample"


def test_a_skip_shows_as_skipped_not_done_and_moves_on(channel):
    ch = channel.config
    _video(ch, "a", True, "published")
    ch.manual_checklist_overrides = ["logo"]
    stages, _ = launch.stages(ch)
    logo = next(s for s in stages if s.id == "logo")
    assert logo.skipped and not logo.done
    assert launch.current(stages).id == "youtube"


def test_youtube_needs_the_statistics_permission_too(channel):
    ch = channel.config
    channel.state.update(connected=True, stats=False)
    stages, _ = launch.stages(ch)
    youtube_stage = next(s for s in stages if s.id == "youtube")
    assert not youtube_stage.done and "reconnect" in youtube_stage.detail


def test_the_shadow_run_needs_five_decisions_and_four_agreements(channel):
    ch = channel.config
    channel.state.update(logo=True, connected=True, stats=True)
    ch.publishing.enabled = True
    for i in range(4):
        _video(ch, f"ok{i}", True, "published")
    stages, _ = launch.stages(ch)
    assert launch.current(stages).id == "shadow"
    assert "4 of 5" in launch.current(stages).detail

    _video(ch, "bad", False, "discarded")      # gate held it, you discarded it: agreed
    stages, _ = launch.stages(ch)
    assert launch.current(stages).id == "autopilot"

    ch.autopilot.mode = "when_clean"
    stages, _ = launch.stages(ch)
    assert launch.current(stages) is None


def test_videos_the_checks_approved_themselves_are_not_a_second_opinion(channel):
    ch = channel.config
    for i in range(5):
        path = _video(ch, f"v{i}", True, None)
        gallery.save_queue_state(path, queued_at="2026-09-24T00:00:00", approved_by="checks")
    assert launch.gate_agreement(ch) == (0, 0)


def test_grow_items_include_the_hand_offs(channel):
    ch = channel.config
    ch.publishing.post_tiktok = True
    _, grow = launch.stages(ch)
    assert next(s for s in grow if s.id == "tiktok").done
    assert not next(s for s in grow if s.id == "instagram").done
