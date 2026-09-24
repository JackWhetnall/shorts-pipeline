"""
Posting to TikTok and Instagram from this PC, in as few moves as the
platforms allow.

Neither platform lets an unreviewed app post for you. Posting publicly
through their APIs needs an audited app of our own or a paid service
that has one. Filling their upload forms by script is automation both
platforms' terms forbid, and it can get an account restricted, which is
the wrong risk to take with a channel meant to earn. So this does
everything around the one step that has to be yours:

- **The right account, already logged in.** Each channel can have its own
  browser profile: Chrome keeps a profile's logins, so you sign in to
  that channel's TikTok and Instagram once, in it, and never again. (A
  private window would log you out every time.) Launching Chrome with a
  profile folder that doesn't exist yet creates it, so setting one up is
  one click here.
- **The upload page open** in that profile.
- **The video selected** in an Explorer window, ready to drag in.
- **The caption on the clipboard** (copied by the page you clicked in,
  which is where clipboard access lives).

Everything is launched on this machine as the signed-in user, which is
what the app is for: the web app is bound to 127.0.0.1 and started at
logon. See decision 033.
"""

from __future__ import annotations

import json
import os
import subprocess
import webbrowser
from pathlib import Path

from core import gallery
from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

PLATFORMS = ("tiktok", "instagram")
LABELS = {"tiktok": "TikTok", "instagram": "Instagram"}
UPLOAD_URLS = {
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
    # Instagram's web app has no upload URL; its Create button is on the
    # home page, and it takes a dragged-in video.
    "instagram": "https://www.instagram.com/",
}
LOGIN_URLS = {
    "tiktok": "https://www.tiktok.com/login",
    "instagram": "https://www.instagram.com/accounts/login/",
}

_LOCAL = os.environ.get("LOCALAPPDATA", "")
BROWSERS = {
    "chrome": {
        "label": "Chrome",
        "exe": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.join(_LOCAL, r"Google\Chrome\Application\chrome.exe")],
        "data": os.path.join(_LOCAL, r"Google\Chrome\User Data"),
    },
    "edge": {
        "label": "Edge",
        "exe": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
        "data": os.path.join(_LOCAL, r"Microsoft\Edge\User Data"),
    },
}


def _exe(browser: str):
    for candidate in BROWSERS.get(browser, {}).get("exe", []):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def installed_browsers() -> list:
    return [key for key in BROWSERS if _exe(key)]


def profiles(browser: str) -> list:
    """[(folder, display name)] for a browser's existing profiles."""
    state = Path(BROWSERS.get(browser, {}).get("data", "")) / "Local State"
    try:
        cache = json.loads(state.read_text(encoding="utf-8"))["profile"]["info_cache"]
    except (OSError, ValueError, KeyError):
        return []
    return sorted(((folder, info.get("name") or folder) for folder, info in cache.items()),
                  key=lambda row: row[1].lower())


def profile_choices() -> list:
    """Every browser profile on this machine, for the settings select:
    [{"value": "chrome|Profile 2", "label": "Chrome: Minute Pastor"}]."""
    out = []
    for browser in installed_browsers():
        for folder, name in profiles(browser):
            out.append({"value": f"{browser}|{folder}",
                        "label": f"{BROWSERS[browser]['label']}: {name}"})
    return out


def suggested_profile_folder(channel) -> str:
    return f"Shorts {channel.key}"


def open_pages(channel, urls: list) -> str:
    """Open `urls` in the channel's browser profile, or the default
    browser if it has none. Returns a description of where."""
    browser, folder = channel.publishing.posting_browser, channel.publishing.posting_profile
    exe = _exe(browser) if browser else None
    if exe and folder:
        # A list, never a shell string: the folder name is config, the URLs
        # are constants, and none of it is interpreted by a shell.
        subprocess.Popen([exe, f"--profile-directory={folder}", *urls])
        return f"{BROWSERS[browser]['label']} ({folder})"
    for url in urls:
        webbrowser.open(url)
    return "your default browser"


def reveal(video_path: Path) -> None:
    """An Explorer window with the video selected, ready to drag."""
    subprocess.Popen(["explorer", f"/select,{Path(video_path).resolve()}"])


def caption(video_path: Path) -> str:
    info = gallery.load_publish_info(video_path)
    title = info["title"] or Path(video_path).stem.replace("_", " ")
    return f"{title}\n\n{info['description']}".strip()


def start_post(channel, video_path: Path, platform: str) -> dict:
    """Everything around posting one video to one platform, bar the post."""
    if platform not in PLATFORMS:
        raise PipelineError(f"unknown platform {platform}", user_message="Unknown platform.")
    reveal(video_path)
    where = open_pages(channel, [UPLOAD_URLS[platform]])
    log.info(f"{channel.key}: opened {LABELS[platform]} upload in {where} for {Path(video_path).name}")
    return {"caption": caption(video_path), "where": where, "platform": LABELS[platform]}


def set_up_profile(channel) -> str:
    """Give the channel its own Chrome profile (created on first launch)
    and open both platforms' login pages in it. Returns the folder."""
    browser = channel.publishing.posting_browser or ("chrome" if _exe("chrome") else "edge")
    if not _exe(browser):
        raise PipelineError("no browser", user_message=(
            "Couldn't find Chrome or Edge on this PC to make a profile in."))
    folder = channel.publishing.posting_profile or suggested_profile_folder(channel)
    channel.publishing.posting_browser, channel.publishing.posting_profile = browser, folder
    open_pages(channel, [LOGIN_URLS["tiktok"], LOGIN_URLS["instagram"]])
    return folder
