"""
The videos to post sit in OneDrive when it's set up (decision 136), so the
phone's OneDrive app has them without a cable. The owner, 27 Oct: "i dont
want to have to transfer them manually every time". A synced folder gets a
copy: OneDrive doesn't upload a hard link's changes reliably.
"""

from __future__ import annotations

import os

from core import gallery, posting


class _Channel:
    key = "why"
    channel_display_name = "Why, Though?"


def _video(tmp_path, name="a.mp4"):
    video = tmp_path / "out" / name
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video")
    gallery.save_publish_info(video, {"title": "Why Is the Sky Blue"})
    return video


def test_the_folder_is_in_onedrive_when_there_is_one(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path))
    assert posting._ready_dir() == tmp_path / "Shorts to post"
    monkeypatch.setenv("OneDrive", str(tmp_path / "missing"))
    assert posting._ready_dir().parent.name == "Videos"


def test_a_synced_folder_gets_a_copy_and_old_ones_move_in(tmp_path, monkeypatch):
    old = tmp_path / "Videos"
    monkeypatch.setattr(posting, "READY_DIR", old)
    first = posting.stage(_Channel(), _video(tmp_path))
    cloud = tmp_path / "OneDrive"
    monkeypatch.setenv("OneDrive", str(cloud))
    monkeypatch.setattr(posting, "READY_DIR", cloud / "Shorts to post")
    assert posting.move_staged() == 1 and not first.exists()
    moved = cloud / "Shorts to post" / first.name
    assert posting.stage(_Channel(), tmp_path / "out" / "a.mp4") == moved
    second = posting.stage(_Channel(), _video(tmp_path, "b.mp4"))
    assert second.parent == cloud / "Shorts to post"
    assert os.stat(second).st_nlink == 1                          # a copy, not a link
