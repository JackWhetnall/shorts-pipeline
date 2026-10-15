"""
One approval for a film's video (decision 104): Review queued it and the
film's page approved its stage, separately. Approving in Review alone
left the film unapproved and its teasers were never made.
"""

from __future__ import annotations

from types import SimpleNamespace as N

import pytest

from core import gallery, production, publish_queue


@pytest.fixture
def film(tmp_path, monkeypatch):
    monkeypatch.setattr(production, "CHANNELS_DIR", tmp_path / "channels")
    out = tmp_path / "out"
    video = out / "longform" / "2026-10-15" / "deep.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    data = production.blank("t3", "Deep")
    for s in ("pitch", "outline", "script", "stills"):
        data["stages"][s]["state"] = "approved"
    data["stages"]["video"]["state"] = "ready"
    data["video"] = {"path": "longform/2026-10-15/deep.mp4"}
    production.save("why", data)
    monkeypatch.setattr(gallery, "_channel_key_for", lambda p: "why")
    monkeypatch.setattr(gallery, "resolve_output_dir", lambda d: out)
    import core.channels as config
    monkeypatch.setattr(config, "load_channels", lambda validate=True: {"why": N(output_dir="why")})
    return video


def test_approving_in_review_approves_the_films_video_and_taking_it_out_undoes_it(film, monkeypatch):
    monkeypatch.setattr(gallery, "save_queue_state", lambda path, **kw: {})
    monkeypatch.setattr(gallery, "load_publish_info", lambda p: {"discarded": False, "queued_at": None,
                                                                "youtube_url": "", "set_aside_for": ""})
    monkeypatch.setattr(gallery, "is_out", lambda info: False)
    publish_queue.enqueue(film, approved_by="you")
    data = production.load("why", "t3")
    assert data["stages"]["video"]["state"] == "approved" and data["history"][-1]["did"] == "approved in Review"
    publish_queue.unqueue(film)
    assert production.load("why", "t3")["stages"]["video"]["state"] == "ready"


def test_a_video_that_isnt_a_films_is_left_alone(film, tmp_path):
    production.video_reviewed(tmp_path / "out" / "2026-10-15" / "quiz.mp4", approved=True)
    assert production.load("why", "t3")["stages"]["video"]["state"] == "ready"
