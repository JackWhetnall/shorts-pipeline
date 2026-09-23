"""
Publishing without a person: the gate, the automatic checks, and what
happens to a finished video on a channel that publishes itself.

What matters most here is the safe direction. A check that didn't run, a
flag the pipeline raised, a failed upload, a channel that isn't connected:
every one of them must leave the video waiting in review, never upload it
and never lose it. No model or YouTube call is made.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import autopilot, publish_gate
from core.channels import Autopilot, ChannelConfig
from core.errors import ExternalServiceError
from pipeline import editor_check, llm


def _checks(script=(), frames=(), script_ran=True, frames_ran=True):
    return {"script": {"ran": script_ran, "problems": list(script)},
            "frames": {"ran": frames_ran, "problems": list(frames)}}


def _clean_report(**overrides):
    report = {"footage_repeated": False, "footage_degraded": False,
              "footage_unconfident": 0, "script_suspect": "",
              "similarity": {"flagged": False}, "checks": _checks(),
              "title_options": ["A Title"]}
    report.update(overrides)
    return report


# --- the gate ----------------------------------------------------------

class TestGate:
    def test_a_clean_report_passes(self):
        assert publish_gate.evaluate(_clean_report()) == {"passed": True, "reasons": []}

    @pytest.mark.parametrize("override", [
        {"footage_degraded": True},
        {"footage_repeated": True},
        {"footage_unconfident": 2},
        {"script_suspect": "A catchy line"},
        {"similarity": {"flagged": True, "closest_title": "earlier"}},
    ])
    def test_every_pipeline_flag_holds_it(self, override):
        result = publish_gate.evaluate(_clean_report(**override))
        assert not result["passed"] and result["reasons"]

    def test_a_blocking_problem_holds_it_and_a_note_does_not(self):
        note = {"where": "Frame 2", "problem": "loosely related", "severity": "note"}
        block = {"where": "LINE 1", "problem": "says Paul, it was Peter", "severity": "block"}
        assert publish_gate.evaluate(_clean_report(checks=_checks(frames=[note])))["passed"]
        held = publish_gate.evaluate(_clean_report(checks=_checks(script=[block])))
        assert not held["passed"]
        assert "it was Peter" in held["reasons"][0]

    def test_a_check_that_did_not_run_is_never_a_pass(self):
        assert not publish_gate.evaluate(_clean_report(checks=_checks(frames_ran=False)))["passed"]
        assert not publish_gate.evaluate(_clean_report(checks=None))["passed"]


# --- after a render ----------------------------------------------------

@pytest.fixture
def channel(tmp_path, monkeypatch):
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path)
    ch = ChannelConfig(key="c", voice="21m00Tcm4TlvDq8ikWAM", style_prompt="x")
    ch.output_dir = str(tmp_path / "c")
    ch.autopilot = Autopilot(mode="when_clean", spot_check_every=0)
    return ch


def _video(channel, name="v.mp4", report=None):
    from core import gallery
    from pathlib import Path
    path = Path(channel.output_dir) / "2026-09-24" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    report = report if report is not None else _clean_report()
    report["gate"] = publish_gate.evaluate(report)
    gallery.save_report(path, report)
    gallery.save_title_and_description(path, "Chosen title", "Chosen description")
    return path


@pytest.fixture
def youtube(monkeypatch):
    calls = []
    state = {"connected": True, "fail": False, "locked": False}

    def upload(key, path, title, description, **kwargs):
        calls.append({"title": title, "description": description, **kwargs})
        if state["fail"]:
            raise ExternalServiceError("YouTube", "boom", user_message="YouTube said no.")
        return {"id": "abc", "url": "https://www.youtube.com/watch?v=abc",
                "privacy_granted": "private" if state["locked"] else "public",
                "locked_private": state["locked"]}

    monkeypatch.setattr(autopilot.youtube, "connection", lambda key: {"connected": state["connected"]})
    monkeypatch.setattr(autopilot.youtube, "upload", upload)
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    return SimpleNamespace(calls=calls, state=state)


class TestAfterRender:
    def test_off_does_nothing(self, channel, youtube):
        channel.autopilot.mode = "off"
        assert autopilot.after_render(channel, _video(channel)).action == autopilot.OFF
        assert not youtube.calls

    def test_a_clean_video_uploads_with_its_edited_title(self, channel, youtube):
        from core import gallery
        path = _video(channel)
        decision = autopilot.after_render(channel, path)
        assert decision.action == autopilot.UPLOADED
        assert youtube.calls[0]["title"] == "Chosen title"
        assert youtube.calls[0]["privacy"] == "public"
        info = gallery.load_publish_info(path)
        assert info["youtube_url"] and info["published_at"]

    def test_a_flagged_video_waits_and_says_why(self, channel, youtube):
        from core import gallery
        path = _video(channel, report=_clean_report(footage_repeated=True))
        decision = autopilot.after_render(channel, path)
        assert decision.action == autopilot.HELD
        assert "appears twice" in decision.message
        assert not youtube.calls
        assert gallery.load_report(path)["autopilot"]["message"] == decision.message

    def test_every_nth_clean_video_is_held_as_a_spot_check(self, channel, youtube):
        channel.autopilot.spot_check_every = 2
        first = autopilot.after_render(channel, _video(channel, "a.mp4"))
        second = autopilot.after_render(channel, _video(channel, "b.mp4"))
        assert first.action == autopilot.UPLOADED
        assert second.action == autopilot.HELD and "spot check" in second.message

    def test_not_connected_waits(self, channel, youtube):
        youtube.state["connected"] = False
        assert autopilot.after_render(channel, _video(channel)).action == autopilot.HELD
        assert not youtube.calls

    def test_a_failed_upload_waits_and_is_not_marked_published(self, channel, youtube):
        from core import gallery
        youtube.state["fail"] = True
        path = _video(channel)
        decision = autopilot.after_render(channel, path)
        assert decision.action == autopilot.HELD
        assert "YouTube said no." in decision.message
        assert not gallery.load_publish_info(path)["published_at"]

    def test_a_private_lock_is_reported(self, channel, youtube):
        youtube.state["locked"] = True
        decision = autopilot.after_render(channel, _video(channel))
        assert decision.action == autopilot.UPLOADED and "private" in decision.message


# --- the checks themselves ---------------------------------------------

class TestEditorChecks:
    def _channel(self):
        return SimpleNamespace(style_prompt="Soft possibilities only.", avoid_imagery=["tarot"])

    def test_the_quote_is_marked_as_someone_elses_words(self, monkeypatch):
        from pipeline.plan import Script, Segment
        seen = {}

        def fake(system, user, schema, **kwargs):
            seen.update(kwargs, user=user)
            return {"problems": []}

        monkeypatch.setattr(llm, "call_json", fake)
        script = Script(segments=[Segment("For God so loved the world."), Segment("Our words.")],
                        citation="John 3:16")
        result = editor_check.check_script(script, self._channel())

        assert result.ran and not result.problems
        assert "[SOURCE] For God so loved" in seen["user"]
        assert "[LINE 1] Our words." in seen["user"]
        # Haiku rejects `effort`; sending it would 400 every check.
        assert seen["model"] == editor_check.CHECK_MODEL and seen["effort"] is None

    def test_a_service_failure_is_not_a_pass(self, monkeypatch):
        from pipeline.plan import Script, Segment

        def down(*a, **k):
            raise ExternalServiceError("Claude", "503", user_message="The AI service is down.")

        monkeypatch.setattr(llm, "call_json", down)
        result = editor_check.check_script(Script(segments=[Segment("x")]), self._channel())
        assert not result.ran and result.error == "The AI service is down."

    def test_video_time_accounts_for_a_title_card(self):
        before = SimpleNamespace(title_card_at=0.0, title_card_seconds=2.0)
        after_intro = SimpleNamespace(title_card_at=5.0, title_card_seconds=2.0)
        none = SimpleNamespace(title_card_at=0.0, title_card_seconds=0.0)
        assert editor_check.video_time(before, 3.0) == 5.0
        assert editor_check.video_time(after_intro, 3.0) == 3.0
        assert editor_check.video_time(after_intro, 6.0) == 8.0
        assert editor_check.video_time(none, 3.0) == 3.0

    def test_frames_are_spread_across_the_video(self):
        assert editor_check._spread(list(range(16)), 6) == [0, 3, 6, 9, 12, 15]
        assert editor_check._spread([1, 2], 6) == [1, 2]
