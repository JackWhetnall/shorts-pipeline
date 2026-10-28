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
- **The upload page open** in that profile, with the video's full path on
  the clipboard: the platform's "Select video" opens a file picker, and
  pasting a path into its name box and pressing Enter picks that file.
  (An Explorer window to drag from was the first try: it still meant
  finding the file among a dated folder's sidecars.)
- **The video in one plain folder**, `Videos\Shorts to post`, named by
  channel and title, with nothing else in it but videos waiting to be
  posted; each goes once it's posted everywhere (`stage`, `unstage`).
- **A caption for each platform** with its hashtags (`caption`), to copy
  in one click, written for that platform's search (`write_social`,
  decision 085).

The To post page and a published video's own page show these as numbered
steps per platform (`plan`). Decision 059.

Everything is launched on this machine as the signed-in user, which is
what the app is for: the web app is bound to 127.0.0.1 and started at
logon. See decision 033.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from core import gallery
from core.paths import CACHE_DIR
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
    """[(folder, display name)] for a browser's existing profiles. The name
    says which is which: Chrome calls a new profile "Your Chrome" and the
    first one "Person 1", so its own name alone told two apart by nothing.
    The Google account signed in to it is added, and a profile this app
    made for a channel says so."""
    state = Path(BROWSERS.get(browser, {}).get("data", "")) / "Local State"
    try:
        cache = json.loads(state.read_text(encoding="utf-8"))["profile"]["info_cache"]
    except (OSError, ValueError, KeyError):
        return []
    rows = []
    for folder, info in cache.items():
        name = info.get("name") or folder
        if folder.startswith("Shorts "):
            name = f"made for {folder[len('Shorts '):]}"
        elif info.get("user_name"):
            name = f"{name} ({info['user_name']})"
        rows.append((folder, name))
    return sorted(rows, key=lambda row: row[1].lower())


def profile_label(channel) -> str:
    """Where this channel posts from, in words."""
    browser, folder = channel.publishing.posting_browser, channel.publishing.posting_profile
    if not (browser and folder):
        return "your default browser"
    name = dict(profiles(browser)).get(folder, folder)
    return f"{BROWSERS.get(browser, {}).get('label', browser)}, profile \u201c{name}\u201d"


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


# --- hashtags and captions --------------------------------------------------

# Instagram allows five hashtags a post (since December 2025).
TAG_LIMITS = {"youtube": 3, "tiktok": 5, "instagram": 5}
QUIZ_TAGS = ("#quiz", "#trivia", "#pubquiz")


def _tag(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", (text or "").replace("&", " and "))
    tag = "".join(w.lower() for w in words)
    return f"#{tag}" if 2 < len(tag) <= 30 else ""


def hashtags(channel, video_path: Path, platform: str) -> list:
    """Hashtags for one video on one platform: what this video is about
    first (a quiz's category), then what the channel is about (its profile
    keywords), then the channel's own name. YouTube shows three above the
    title; TikTok works best with a handful; Instagram allows more."""
    from core import channel_profile
    tags = []
    round_info = {}
    sidecar = Path(video_path).with_name(f"{Path(video_path).stem}_quiz.json")
    if sidecar.exists():
        try:
            round_info = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            round_info = {}
    category = round_info.get("category", "")
    if category:
        tags += [_tag(f"{category} quiz"), _tag(category)]
    keywords = channel_profile.load(channel.key).get("keywords") or []
    tags += [_tag(k) for k in keywords]
    if channel.format == "quiz":
        tags += list(QUIZ_TAGS)
    tags.append(_tag(channel.channel_display_name or channel.key))
    out = []
    for tag in tags:
        if tag and tag not in out:
            out.append(tag)
    limit = TAG_LIMITS.get(platform, 5)
    # The channel's own tag always makes the cut.
    brand = _tag(channel.channel_display_name or channel.key)
    picked = out[:limit]
    if brand and brand not in picked and limit > 2:
        picked = picked[:limit - 1] + [brand]
    return picked


_CREDIT = re.compile(r"^(music|artwork|image|picture|footage|some questions)\b.*|.*\b(cc by|cc0|public domain|"
                     r"licen[cs]ed?|wikimedia|opentdb)\b.*", re.IGNORECASE)


def _sidecar_json(video_path: Path, suffix: str) -> dict:
    path = Path(video_path).with_name(f"{Path(video_path).stem}_{suffix}.json")
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def credits(video_path: Path) -> list:
    """The licence lines a video's music or pictures need (CC BY asks for
    one wherever the work is shown): from its render report, or failing
    that its description's credit lines."""
    found = list(_sidecar_json(video_path, "report").get("artwork") or [])
    if not found:
        description = gallery.load_publish_info(video_path)["description"] or ""
        found = [line.strip() for line in description.splitlines() if _CREDIT.match(line.strip())]
    return [c for i, c in enumerate(found) if c and c not in found[:i]]


def _about(description: str) -> str:
    """The description's words about the video: without its hashtags,
    reference, links and credits."""
    keep = []
    for line in (description or "").splitlines():
        line = line.strip()
        if (not line or line.startswith("#") or line.lower().startswith("reference:")
                or "http" in line or _CREDIT.match(line)):
            continue
        keep.append(re.sub(r"\s#\w+", "", line).strip())
    return " ".join(keep)


def social_path(video_path: Path) -> Path:
    return Path(video_path).with_name(f"{Path(video_path).stem}_social.json")


def social(video_path: Path) -> dict:
    """The search-written captions for this video, if they were written
    for its title as it is now ({} otherwise)."""
    data = _sidecar_json(video_path, "social")
    title = gallery.load_publish_info(video_path)["title"] or ""
    return data if data and data.get("title", "") == title else {}


def write_social(channel, video_path: Path) -> dict:
    """Write and keep this video's TikTok and Instagram captions (one cheap
    call, about $0.003; pipeline.social_caption). Raises PipelineError if
    the call fails: the caller falls back to the plain caption."""
    from core import channel_profile
    from pipeline import social_caption
    info = gallery.load_publish_info(video_path)
    title = info["title"] or Path(video_path).stem.replace("_", " ")
    profile = channel_profile.load(channel.key)
    script = _sidecar_json(video_path, "script")
    quiz = _sidecar_json(video_path, "quiz") or (script.get("quiz") or {})
    answers = [q.get(k) for q in quiz.get("questions") or [] for k in ("answer", "spoken_answer") if q.get(k)]
    prompt = social_caption.brief(
        channel_name=channel.channel_display_name or channel.key,
        about=(profile.get("about") or "").split("\n\n")[0],
        keywords=profile.get("keywords") or [], title=title,
        description=_about(info["description"]), reference=script.get("citation") or "",
        # A quiz's lines say its answers, so a quiz is told only its questions.
        spoken=[] if quiz else [s.get("text", "") for s in script.get("segments") or [] if s.get("text")],
        quiz=quiz or None)
    from pipeline import llm
    with llm.for_channel(channel.key):
        written = social_caption.write(prompt, answers)
    data = {"title": info["title"] or "", "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **written}
    social_path(video_path).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def caption(video_path: Path, platform: str = "", channel=None) -> str:
    """What to paste with the video: its search-written caption (decision
    085), then its hashtags, then any licence line its music or pictures
    need. Without one written, its title and what the description says
    about it. Without a platform, the title and description."""
    info = gallery.load_publish_info(video_path)
    title = info["title"] or Path(video_path).stem.replace("_", " ")
    description = (info["description"] or "").strip()
    if not platform or channel is None:
        return f"{title}\n\n{description}".strip()
    written = social(video_path).get(platform)
    plain = hashtags(channel, video_path, platform)
    if written:
        text = written["caption"]
        brand = _tag(channel.channel_display_name or channel.key)
        tags = [t for t in written.get("hashtags") or [] if t != brand][:TAG_LIMITS.get(platform, 5) - 1]
        tags = (tags or plain[:-1]) + ([brand] if brand else [])
    else:
        # TikTok's is read in the time the video starts: one sentence.
        about = _about(description)
        if platform == "tiktok" and about:
            about = re.split(r"(?<=[.!?])\s", about)[0]
        text = "\n\n".join(p for p in (title, about) if p)
        tags = plain
    licence = " ".join(credits(video_path))
    return "\n\n".join(p for p in (text, full_video_line(channel, video_path), " ".join(tags), licence) if p)


def full_video_line(channel, video_path: Path) -> str:
    """Where a teaser's film is (decision 116): its spoken ending sends
    viewers to "our channel", and on TikTok or Instagram that's YouTube.
    "" for anything that isn't a teaser."""
    if not (gallery.load_report(video_path) or {}).get("teaser"):
        return ""
    return f"Full video on YouTube: {channel.channel_display_name or channel.key}"


def with_youtube_hashtags(channel, video_path: Path, description: str) -> str:
    """A YouTube description with its hashtags at the end, unless it has
    some already (YouTube shows the first three above the title)."""
    if "#" in (description or ""):
        return description
    tags = " ".join(hashtags(channel, video_path, "youtube"))
    return f"{(description or '').rstrip()}\n\n{tags}".strip() if tags else description


# --- one plain folder of videos to post -------------------------------------

READY_DIR = Path.home() / "Videos" / "Shorts to post"


def _phone_dir():
    """OneDrive's own folder for videos to post from the phone, or None
    without OneDrive (decision 140)."""
    cloud = os.environ.get("OneDrive", "").strip()
    return Path(cloud) / "Shorts to post" if cloud and Path(cloud).is_dir() else None


PHONE_DIR = _phone_dir()
PHONE_INDEX = CACHE_DIR / "phone_posts.json"
STAGED_INDEX = CACHE_DIR / "staged_posts.json"


def _index() -> dict:
    try:
        return json.loads(STAGED_INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_index(index: dict) -> None:
    STAGED_INDEX.parent.mkdir(parents=True, exist_ok=True)
    STAGED_INDEX.write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")


def _safe_name(text: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text or "").strip(" .")
    return " ".join(name.split())[:90] or "video"


def stage(channel, video_path: Path) -> Path:
    """The video in the ready-to-post folder, named by channel and title,
    linked rather than copied where the disk allows (no extra space).
    Made once; the same path afterwards."""
    video_path = Path(video_path)
    index = _index()
    known = index.get(str(video_path.resolve()))
    if known and Path(known).exists():
        return Path(known)
    info = gallery.load_publish_info(video_path)
    title = info["title"] or video_path.stem.replace("_", " ")
    READY_DIR.mkdir(parents=True, exist_ok=True)
    base = _safe_name(f"{channel.channel_display_name or channel.key} - {title}")
    target, n = READY_DIR / f"{base}{video_path.suffix}", 2
    taken = set(index.values())
    while target.exists() or str(target) in taken:
        target, n = READY_DIR / f"{base} ({n}){video_path.suffix}", n + 1
    try:
        os.link(video_path, target)
    except OSError:
        shutil.copyfile(video_path, target)
    index[str(video_path.resolve())] = str(target)
    _save_index(index)
    return target


def _phone_index() -> dict:
    try:
        return json.loads(PHONE_INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def on_phone(video_path: Path) -> str:
    """Where this video's phone copy is, or ""."""
    found = _phone_index().get(str(Path(video_path).resolve()), "")
    return found if found and Path(found).exists() else ""


def to_phone(channel, video_path: Path) -> Path:
    """A copy of this one video in OneDrive's Shorts to post, for posting
    from the phone's OneDrive app (decision 140). Only when asked: the
    owner, 28 Oct, "if i want to post something from my phone then i should
    be able to do that OPTIONALLY". A copy, not a link: OneDrive doesn't
    upload a linked file reliably."""
    if PHONE_DIR is None:
        raise PipelineError("no OneDrive folder", user_message="OneDrive isn't set up on this PC.")
    known = on_phone(video_path)
    if known:
        return Path(known)
    info = gallery.load_publish_info(video_path)
    title = info["title"] or Path(video_path).stem.replace("_", " ")
    PHONE_DIR.mkdir(parents=True, exist_ok=True)
    base = _safe_name(f"{channel.channel_display_name or channel.key} - {title}")
    target, n = PHONE_DIR / f"{base}{Path(video_path).suffix}", 2
    while target.exists():
        target, n = PHONE_DIR / f"{base} ({n}){Path(video_path).suffix}", n + 1
    shutil.copyfile(video_path, target)
    index = _phone_index()
    index[str(Path(video_path).resolve())] = str(target)
    PHONE_INDEX.parent.mkdir(parents=True, exist_ok=True)
    PHONE_INDEX.write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    return target


def off_phone(video_path: Path) -> None:
    """The phone copy taken away; the PC's copy stays."""
    _off_phone(video_path)


def _off_phone(video_path: Path) -> None:
    index = _phone_index()
    copy = index.pop(str(Path(video_path).resolve()), None)
    if copy:
        Path(copy).unlink(missing_ok=True)
        PHONE_INDEX.write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")


def unstage(video_path: Path) -> None:
    """Take a video's copy out of the ready-to-post folder (posted
    everywhere, or discarded). Only a file this app put there."""
    index = _index()
    staged = index.pop(str(Path(video_path).resolve()), None)
    if staged:
        Path(staged).unlink(missing_ok=True)
        _save_index(index)
    _off_phone(video_path)


# --- the steps, per platform ------------------------------------------------

# The To post page's buttons (decision 119): open the platform once, at
# the top; then per video, its location, its thumbnail's, its caption.
STEPS = {
    "tiktok": ["<strong>Select video</strong> → <strong>Ctrl+V</strong>, <strong>Enter</strong>",
               "Cover: <strong>Edit cover</strong> → <strong>Upload</strong> → <strong>Ctrl+V</strong>, "
               "<strong>Enter</strong>",
               "Caption: paste into the description",
               # AI voice and pictures unlabelled: a likely cause of zero views (decision 135).
               "<strong>More options</strong> → <strong>AI-generated content</strong> on",
               "<strong>Post</strong>, then <strong>I've posted it</strong>"],
    "instagram": ["<strong>Create</strong> → <strong>Post</strong> → <strong>Select from computer</strong> → "
                  "<strong>Ctrl+V</strong>, <strong>Enter</strong>",
                  "Cover: <strong>Cover photo</strong> → <strong>Select from computer</strong> → "
                  "<strong>Ctrl+V</strong>, <strong>Enter</strong>",
                  "Caption: paste into the caption box",
                  "<strong>Share</strong>, then <strong>I've posted it</strong>"],
}
# Instagram first: it's the one posted first (the owner, 19 Oct).
ORDER = ("instagram", "tiktok")


def thumbnail_of(video_path: Path) -> str:
    """The picture to give the platform as the cover: a quiz short's cover,
    else the video's thumbnail. "" when it has neither."""
    video_path = Path(video_path)
    for suffix in ("_cover.jpg", "_thumb.jpg"):
        path = video_path.with_name(f"{video_path.stem}{suffix}")
        if path.exists():
            return str(path.resolve())
    return ""


def plan(channel, video_path: Path) -> dict:
    """Everything the posting steps show for one video: the file to pick,
    where it opens, and per platform its caption, steps and whether it's
    done."""
    from core import instagram
    info = gallery.load_publish_info(video_path)
    handoff = info["handoff"] or {}
    pending = [p for p in PLATFORMS if p in handoff and not handoff[p].get("posted_at")]
    file = str(stage(channel, video_path)) if pending else ""
    auto = instagram.state(channel, video_path) if "instagram" in handoff else {"auto": False}
    return {
        "file": file,
        "thumb": thumbnail_of(video_path) if pending else "",
        "where": profile_label(channel),
        "has_profile": bool(channel.publishing.posting_browser and channel.publishing.posting_profile),
        "youtube_url": info["youtube_url"],
        "phone": on_phone(video_path), "phone_ok": PHONE_DIR is not None,
        "platforms": [{"key": p, "label": LABELS[p], "caption": caption(video_path, p, channel),
                       "for_search": bool(social(video_path).get(p)),
                       "steps": STEPS[p], "posted": bool(handoff[p].get("posted_at")),
                       "url": info.get(f"{p}_url") or "",
                       "auto": auto if p == "instagram" else {"auto": False}}
                      for p in ORDER if p in handoff],
    }


def start_post(channel, video_path: Path, platform: str) -> dict:
    """Open one platform's upload page in the channel's browser profile.
    The page that called this has put the video's path on the clipboard."""
    if platform not in PLATFORMS:
        raise PipelineError(f"unknown platform {platform}", user_message="Unknown platform.")
    where = open_pages(channel, [UPLOAD_URLS[platform]])
    log.info(f"{channel.key}: opened {LABELS[platform]} upload in {where} for {Path(video_path).name}")
    return {"where": where, "platform": LABELS[platform], "file": str(stage(channel, video_path))}


def open_upload(channel, platform: str) -> str:
    """One platform's upload page in the channel's browser profile, for
    the top of To post (not per video). Returns where it opened."""
    if platform not in PLATFORMS:
        raise PipelineError(f"unknown platform {platform}", user_message="Unknown platform.")
    where = open_pages(channel, [UPLOAD_URLS[platform]])
    log.info(f"{channel.key}: opened {LABELS[platform]} upload in {where}")
    return where


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
