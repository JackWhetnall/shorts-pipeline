"""
`core.posting`: opening the right account's upload page from this PC.

Nothing is launched: `subprocess.Popen` and `webbrowser.open` are
recorded instead. What matters is that the channel's own profile is the
one opened (so the right accounts are signed in), that arguments go as a
list rather than through a shell, and that a channel with no profile
still works through the default browser.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import gallery, posting
from core.channels import ChannelConfig


@pytest.fixture
def launched(monkeypatch):
    calls = {"popen": [], "web": []}
    monkeypatch.setattr(posting.subprocess, "Popen", lambda args: calls["popen"].append(args))
    monkeypatch.setattr(posting.webbrowser, "open", lambda url: calls["web"].append(url))
    monkeypatch.setattr(posting, "_exe", lambda browser: f"C:/{browser}.exe" if browser else None)
    return calls


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "2026-09-24" / "clip.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    gallery.save_title_and_description(path, "A Title", "The description #tags")
    return path


def _channel(**plan):
    channel = ChannelConfig(key="minute_pastor", voice="21m00Tcm4TlvDq8ikWAM", style_prompt="x")
    for name, value in plan.items():
        setattr(channel.publishing, name, value)
    return channel


def test_opens_the_channels_own_profile_and_reveals_the_video(launched, video):
    channel = _channel(posting_browser="chrome", posting_profile="Shorts minute_pastor")
    result = posting.start_post(channel, video, "tiktok")

    explorer, browser = launched["popen"]
    assert explorer[0] == "explorer" and explorer[1].startswith("/select,")
    assert explorer[1].endswith("clip.mp4")
    assert browser == ["C:/chrome.exe", "--profile-directory=Shorts minute_pastor",
                       posting.UPLOAD_URLS["tiktok"]]
    assert result["caption"] == "A Title\n\nThe description #tags"


def test_without_a_profile_it_uses_the_default_browser(launched, video):
    posting.start_post(_channel(), video, "instagram")
    assert launched["web"] == [posting.UPLOAD_URLS["instagram"]]


def test_an_unknown_platform_is_refused(launched, video):
    from core.errors import PipelineError
    with pytest.raises(PipelineError):
        posting.start_post(_channel(), video, "myspace")
    assert launched["popen"] == []


def test_setting_up_a_profile_names_it_for_the_channel_and_opens_both_logins(launched):
    channel = _channel()
    folder = posting.set_up_profile(channel)
    assert folder == "Shorts minute_pastor"
    assert channel.publishing.posting_browser == "chrome"
    args = launched["popen"][0]
    assert f"--profile-directory={folder}" in args
    assert posting.LOGIN_URLS["tiktok"] in args and posting.LOGIN_URLS["instagram"] in args


def test_profiles_are_read_from_the_browsers_own_list(tmp_path, monkeypatch):
    data = tmp_path / "User Data"
    data.mkdir()
    (data / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Person 1"}, "Shorts minute_pastor": {"name": "Minute Pastor"}}}}))
    monkeypatch.setitem(posting.BROWSERS, "chrome", {**posting.BROWSERS["chrome"], "data": str(data)})
    assert posting.profiles("chrome") == [("Shorts minute_pastor", "Minute Pastor"),
                                          ("Default", "Person 1")]
