"""
The videos to post stay in Videos\Shorts to post, linked (decision 059);
one goes to OneDrive only when asked, with "Send to phone" (decision 140,
which undoes 136). The owner, 28 Oct: "i dont need every video ever to be
in my onedrive ... if i want to post something from my phone then i should
be able to do that OPTIONALLY from the video posting page".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import gallery, posting
from core.errors import PipelineError


class _Channel:
    key = "why"
    channel_display_name = "Why, Though?"


def _video(tmp_path, name="a.mp4"):
    video = tmp_path / "out" / name
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video")
    gallery.save_publish_info(video, {"title": "Why Is the Sky Blue"})
    return video


def test_the_folder_to_post_from_is_in_videos_not_onedrive():
    import inspect
    assert 'READY_DIR = Path.home() / "Videos" / "Shorts to post"' in inspect.getsource(posting)


def test_one_video_goes_to_the_phone_only_when_asked(tmp_path, monkeypatch):
    monkeypatch.setattr(posting, "PHONE_DIR", tmp_path / "OneDrive" / "Shorts to post")
    monkeypatch.setattr(posting, "PHONE_INDEX", tmp_path / "phone.json")
    video = _video(tmp_path)
    staged = posting.stage(_Channel(), video)
    assert staged.parent == posting.READY_DIR and not posting.on_phone(video)
    copy = posting.to_phone(_Channel(), video)
    assert copy.parent == tmp_path / "OneDrive" / "Shorts to post" and copy.read_bytes() == b"video"
    assert posting.to_phone(_Channel(), video) == copy and posting.on_phone(video) == str(copy)
    posting.unstage(video)                                      # posted everywhere: both copies go
    assert not copy.exists() and not staged.exists()


def test_without_onedrive_it_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(posting, "PHONE_DIR", None)
    with pytest.raises(PipelineError):
        posting.to_phone(_Channel(), _video(tmp_path))
