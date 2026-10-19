"""
Posting Shorts to Instagram as Reels, by themselves (decision 116).

Meta lets an app that's still in development post to the Instagram
accounts of the people who made it, with no review: "Standard Access".
A video on this PC goes up through the Facebook-login side of Instagram's
API, the only side that takes a file rather than fetching a public web
address, so each channel's Instagram is a professional account linked to
a Facebook Page. One Meta app serves every channel.

**Connecting** (`connect`): the owner pastes a user token from Meta's
Graph API Explorer, with the app's ID and secret once. It's swapped for a
long-lived one, and through that each Page's own token, which doesn't
expire, is kept with the Instagram account linked to the Page. Each
channel then picks its account in Settings (`publishing.instagram_account`).

**Posting** (`post_due`, on each scheduler pass): a Short handed off to
Instagram when it went out (core.publish_queue.put_out) goes up as a Reel
with its Instagram caption. It's copied with its index at the front, as
Instagram requires, uploaded into a container, and published once
Instagram has processed it, which can take a pass. It's then marked
posted with its link, exactly as if posted by hand. Only Shorts handed
off in the last two days go by themselves, so connecting doesn't post a
backlog; an older one has a "Post it for me" button (`post_now`). Three
failures leave it in To post with the reason.

Each step's state is kept in the video's publish sidecar, so a restart
part-way carries on. A container is only ever published once, and one
that stalls is given up for a new one, never published.

TikTok can't be done this way: it lets an unaudited app post only
privately, and only to a private account, and its guidelines rule out
auditing a tool for posting to your own accounts. TikTok stays in
core.posting's steps.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from core import gallery
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR, PROJECT_ROOT, write_atomically

log = get_logger(__name__)

VERSION = "v25.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{VERSION}"
EXPLORER_URL = "https://developers.facebook.com/tools/explorer/"
APPS_URL = "https://developers.facebook.com/apps/"
# What the Explorer's token needs: posting, plus finding the Pages and
# the Instagram accounts linked to them (a Page held in a business
# portfolio is only listed with business_management).
PERMISSIONS = ("instagram_basic", "instagram_content_publish", "pages_show_list",
               "pages_read_engagement", "business_management")

# The Meta app and every connected account: real credentials, kept out of
# version control like config/youtube_tokens.
PATH = PROJECT_ROOT / "config" / "instagram.json"
READY_DIR = CACHE_DIR / "instagram"

TIMEOUT = 60
UPLOAD_TIMEOUT = 900
AUTO_WINDOW = timedelta(days=2)      # handed off (or asked for) this recently: posted by itself
STALLED = timedelta(minutes=30)      # a container still processing after this is given up
MAX_TRIES = 3                        # failures before it's left to the owner
WAIT_NOW = 60                        # seconds a pass waits for Instagram to finish processing
POLL_EVERY = 10
NOW_LIMIT = 15 * 60                  # how long "Post it for me" keeps checking in the background

# One Short at a time, whoever asks: the scheduler's pass and a "Post it
# for me" click must never both start a Reel for one video.
_lock = threading.Lock()


class InstagramError(PipelineError):
    """`transient`: worth trying again at the next pass, not counted as a
    failure. `reconnect`: the connection itself is no good (it lapsed, was
    taken away, or lacks a permission), which no retry will fix."""

    def __init__(self, message: str, *, user_message: str = None, transient: bool = False,
                 reconnect: bool = False):
        super().__init__(message, user_message=user_message)
        self.transient = transient
        self.reconnect = reconnect


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


# --- what's saved -------------------------------------------------------------------

def _load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    write_atomically(PATH, json.dumps(data, indent=1))


def app_config() -> dict:
    """{"app_id", "app_secret"} of the Meta app, or {} before it's saved.
    META_APP_ID and META_APP_SECRET in the environment win."""
    app_id = os.getenv("META_APP_ID", "").strip()
    secret = os.getenv("META_APP_SECRET", "").strip()
    if app_id and secret:
        return {"app_id": app_id, "app_secret": secret}
    data = _load()
    if data.get("app_id") and data.get("app_secret"):
        return {"app_id": data["app_id"], "app_secret": data["app_secret"]}
    return {}


def save_app(app_id: str, app_secret: str) -> None:
    app_id, app_secret = (app_id or "").strip(), (app_secret or "").strip()
    if not app_id.isdigit():
        raise InstagramError(f"bad app id {app_id!r}", user_message=(
            "That isn't an app ID: it's the number under the app's name in App settings, Basic."))
    if len(app_secret) < 16 or " " in app_secret:
        raise InstagramError("bad app secret", user_message=(
            "That isn't an app secret: Show it in App settings, Basic, and copy it whole."))
    data = _load()
    data.update(app_id=app_id, app_secret=app_secret)
    _save(data)


def forget() -> None:
    """The app and every account, gone: channels go back to posting by hand."""
    PATH.unlink(missing_ok=True)


def accounts() -> dict:
    """{Instagram account id: {"username", "page_id", "page_name", "token",
    "connected_at"}} for every account the app may post to."""
    return dict(_load().get("accounts") or {})


def problem() -> str:
    """Why posting stopped working, until the next connect: "" when it's fine."""
    return _load().get("problem") or ""


def _note_problem(message: str) -> None:
    data = _load()
    if data.get("problem") != message:
        data["problem"] = message
        _save(data)


def choices() -> list:
    """[{"value": account id, "label": "@username"}] for a channel's settings."""
    rows = [{"value": key, "label": f"@{a['username']}" if a.get("username") else a.get("page_name") or key}
            for key, a in accounts().items()]
    return sorted(rows, key=lambda r: r["label"].lower())


def account_for(channel):
    """The Instagram account this channel posts to by itself, with its id,
    or None (none chosen, or not connected)."""
    chosen = getattr(channel.publishing, "instagram_account", "") or ""
    found = accounts().get(chosen) if chosen else None
    return {"id": chosen, **found} if found else None


def posts_by_itself(channel) -> bool:
    return bool(channel.publishing.post_instagram and account_for(channel))


# --- talking to Meta ----------------------------------------------------------------

def _error(status: int, error: dict, what: str) -> InstagramError:
    code, sub = error.get("code"), error.get("error_subcode")
    detail = f"{what}: HTTP {status}, code {code}/{sub}: {error.get('message')}"
    if code == 190 or sub in (458, 459, 460, 463, 464, 467):
        return InstagramError(detail, reconnect=True, user_message=(
            "Instagram's connection has lapsed: connect again on Instagram setup."))
    if code in (4, 17, 32, 613) or status == 429 or status >= 500 or error.get("is_transient"):
        return InstagramError(detail, transient=True, user_message="Instagram is busy; it tries again shortly.")
    if code == 9007 or sub == 2207027:
        # "The media is not ready for publishing": finished, but not quite.
        return InstagramError(detail, transient=True, user_message="Instagram is still processing it.")
    if code in (10, 200) or (isinstance(code, int) and 200 < code < 300):
        return InstagramError(detail, reconnect=True, user_message=(
            "Instagram refused a permission: connect again on Instagram setup, with every permission ticked."))
    # Meta's error_user_msg is written for people; its message isn't.
    said = (error.get("error_user_msg") or "").strip()
    return InstagramError(detail, user_message=f"Instagram wouldn't {what}" + (f": {said}" if said else "."))


_SECRETS = re.compile(r"((?:access_token|client_secret|fb_exchange_token)=)[^&\s'\"]+")


def _redacted(text: str) -> str:
    """A message safe for the log: a failed request's message carries its
    URL, and a paging link or the token swap has secrets in it."""
    return _SECRETS.sub(r"\1…", str(text))


def _call(method: str, url: str, what: str, token: str = "", timeout: float = TIMEOUT, **kwargs) -> dict:
    """One Graph API request, the token in a header (never the URL, which
    a failure's message would carry into the log)."""
    if token:
        kwargs["headers"] = {"Authorization": f"Bearer {token}", **(kwargs.get("headers") or {})}
    try:
        response = requests.request(method, url, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise InstagramError(f"{what}: {_redacted(exc)}", transient=True,
                             user_message=f"Couldn't reach Instagram to {what}.") from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    error = data.get("error") if isinstance(data, dict) else None
    if response.ok and not error:
        return data if isinstance(data, dict) else {}
    error = error if isinstance(error, dict) else {"message": _redacted(response.text[:200])}
    raise _error(response.status_code, error, what)


def _pages(token: str) -> list:
    url, params, pages = f"{GRAPH}/me/accounts", {
        "fields": "id,name,access_token,instagram_business_account{id,username}", "limit": 100}, []
    while url:
        page = _call("GET", url, "list your Facebook Pages", token=token, params=params)
        pages += page.get("data") or []
        url, params = (page.get("paging") or {}).get("next"), None
    return pages


def connect(user_token: str) -> list:
    """Swap a user token from the Graph API Explorer for each Page's lasting
    token, and keep every Instagram account they can post to (added to
    any already connected). Returns the accounts, without their tokens."""
    app = app_config()
    if not app:
        raise InstagramError("no Meta app", user_message="Save the Meta app's ID and secret first.")
    token = "".join((user_token or "").split())
    if not token:
        raise InstagramError("no token", user_message="Paste the token from the Graph API Explorer.")
    try:
        # As Meta documents it, a GET; _call keeps its secrets out of the log.
        swapped = _call("GET", f"{GRAPH}/oauth/access_token", "accept that token", params={
            "grant_type": "fb_exchange_token", "client_id": app["app_id"],
            "client_secret": app["app_secret"], "fb_exchange_token": token})
    except InstagramError as exc:
        if exc.reconnect:
            raise InstagramError(str(exc), user_message=(
                "That token didn't work: generate a new one in the Explorer and paste it straight away.")) from exc
        if not exc.transient:
            raise InstagramError(str(exc), user_message=(
                "Meta didn't accept the app's ID and secret with that token: check both in App "
                "settings, Basic, and that the Explorer had this app chosen.")) from exc
        raise
    lasting = swapped.get("access_token")
    if not lasting:
        raise InstagramError(f"no token in {sorted(swapped)}", user_message="Meta didn't send a token back. Try again.")
    found, now = {}, _now().isoformat(timespec="seconds")
    for page in _pages(lasting):
        linked = page.get("instagram_business_account") or {}
        if linked.get("id") and page.get("access_token"):
            found[linked["id"]] = {"username": linked.get("username") or "", "page_id": page.get("id") or "",
                                   "page_name": page.get("name") or "", "token": page["access_token"],
                                   "connected_at": now}
    if not found:
        raise InstagramError("no Instagram accounts on any Page", user_message=(
            "No Instagram account came with that token. Each must be a professional account linked "
            "to a Facebook Page, and both must be ticked when the Explorer asks."))
    data = _load()
    data["accounts"] = {**(data.get("accounts") or {}), **found}
    data.pop("problem", None)
    _save(data)
    log.info("Instagram connected: " + ", ".join(f"@{a['username']}" for a in found.values()))
    return [{"id": key, **{k: v for k, v in a.items() if k != "token"}} for key, a in found.items()]


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def ready_copy(video_path: Path) -> Path:
    """The video as Instagram's Reels rules ask: its index at the front
    and its sound at 128 kbps. The picture is copied as it is."""
    video_path = Path(video_path)
    out = READY_DIR / f"{video_path.parent.name}_{video_path.stem}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([_ffmpeg(), "-v", "error", "-y", "-i", str(video_path), "-map", "0:v:0", "-map", "0:a:0?",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)],
                       check=True, capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstagramError(f"couldn't prepare {video_path.name}: {exc}", user_message=(
            "Couldn't prepare the video for Instagram on this PC.")) from exc
    return out


def _start(account: dict, video_path: Path, caption: str, on_container) -> str:
    """A container with the video uploaded into it. `on_container(id)` is
    told the container before the upload, so a restart part-way knows it."""
    ready = ready_copy(video_path)
    made = _call("POST", f"{GRAPH}/{account['id']}/media", "make the Reel", token=account["token"], data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200], "share_to_feed": "true"})
    container = made.get("id")
    if not container:
        raise InstagramError(f"no container in {sorted(made)}", user_message="Instagram didn't make the Reel.")
    on_container(container)
    with open(ready, "rb") as f:
        sent = _call("POST", made.get("uri") or f"{RUPLOAD}/{container}", "upload the video",
                     timeout=UPLOAD_TIMEOUT, data=f, headers={
                         "Authorization": f"OAuth {account['token']}", "offset": "0",
                         "file_size": str(ready.stat().st_size)})
    if sent.get("success") is False:
        raise InstagramError(f"upload refused: {sent}", user_message="Instagram didn't take the video's upload.")
    return container


def _status(account: dict, container: str) -> tuple:
    data = _call("GET", f"{GRAPH}/{container}", "check the Reel", token=account["token"],
                 params={"fields": "status_code,status"})
    return data.get("status_code") or "", data.get("status") or ""


def _link(account: dict, media_id: str) -> str:
    try:
        return _call("GET", f"{GRAPH}/{media_id}", "find the Reel's link", token=account["token"],
                     params={"fields": "permalink"}).get("permalink") or ""
    except InstagramError as exc:
        # The Reel is out either way: only the To post page's link to it is missing.
        log.warning(f"Instagram Reel {media_id} posted, but its link wasn't found: {exc}")
        return ""


def _link_by_caption(account: dict, caption: str) -> str:
    """The link of a recent Reel with this caption: for one a pass
    published but didn't live to record."""
    try:
        recent = _call("GET", f"{GRAPH}/{account['id']}/media", "find the Reel's link", token=account["token"],
                       params={"fields": "permalink,caption", "limit": 10})
    except InstagramError as exc:
        # As in _link: it's out; the link is a nicety.
        log.warning(f"Instagram: a posted Reel's link wasn't found: {exc}")
        return ""
    start = " ".join(caption.split())[:60]
    for item in recent.get("data") or []:
        if start and " ".join((item.get("caption") or "").split()).startswith(start):
            return item.get("permalink") or ""
    return ""


# --- one Short, a step at a time ----------------------------------------------------

def _entry(video_path: Path) -> dict:
    return dict((gallery.load_publish_info(video_path)["handoff"] or {}).get("instagram") or {})


def _set_auto(video_path: Path, **changes) -> None:
    """Change this Short's posting state; a None removes that field."""
    info = gallery.load_publish_info(video_path)
    handoff = dict(info["handoff"] or {})
    entry = dict(handoff.get("instagram") or {"at": None, "posted_at": None})
    auto = {**(entry.get("auto") or {}), **changes}
    entry["auto"] = {k: v for k, v in auto.items() if v is not None}
    handoff["instagram"] = entry
    gallery.save_queue_state(video_path, handoff=handoff)


def _caption(channel, video_path: Path) -> str:
    from core import posting
    return posting.caption(video_path, "instagram", channel)


def _finish(channel, video_path: Path, account: dict, container: str, published: bool) -> str:
    from core import publish_queue
    caption = _caption(channel, video_path)
    if published:
        link = _link_by_caption(account, caption)
    else:
        media = _call("POST", f"{GRAPH}/{account['id']}/media_publish", "publish the Reel",
                      token=account["token"], data={"creation_id": container}).get("id")
        link = _link(account, media) if media else ""
    publish_queue.mark_posted(video_path, "instagram", link)
    _set_auto(video_path, container=None, started_at=None, error=None)
    (READY_DIR / f"{Path(video_path).parent.name}_{Path(video_path).stem}.mp4").unlink(missing_ok=True)
    log.info(f"{channel.key}: {Path(video_path).stem} posted to Instagram as @{account.get('username')}"
             + (f": {link}" if link else ""))
    return "posted"


def advance(channel, video_path: Path, account: dict, wait: float = None) -> str:
    """One step for one Short: start its Reel, see how Instagram is getting
    on with it (for up to `wait` seconds, WAIT_NOW by default), or publish
    it. Returns "posted", "processing", "failed", or "waiting" (a temporary
    problem or a lapsed connection: it's tried again later)."""
    video_path = Path(video_path)
    wait = WAIT_NOW if wait is None else wait
    with _lock:
        entry = _entry(video_path)
        if entry.get("posted_at"):
            return "posted"
        auto = entry.get("auto") or {}
        if auto.get("failed"):
            return "failed"
        try:
            container = auto.get("container")
            if not container:
                container = _start(account, video_path, _caption(channel, video_path),
                                   lambda made: _set_auto(video_path, container=made,
                                                          started_at=_now().isoformat(timespec="seconds")))
            deadline = time.monotonic() + wait
            while True:
                code, detail = _status(account, container)
                if code in ("FINISHED", "PUBLISHED"):
                    return _finish(channel, video_path, account, container, published=code == "PUBLISHED")
                stalled = _now() - (_parse(_entry(video_path).get("auto", {}).get("started_at")) or _now()) > STALLED
                if code not in ("IN_PROGRESS", "") or stalled:
                    # Given up and never published, so it can't go out twice.
                    raise InstagramError(f"container {container}: {code} {detail}", user_message=(
                        "Instagram couldn't process the video" + (f" ({detail})." if detail else ".")))
                if time.monotonic() >= deadline:
                    return "processing"
                time.sleep(POLL_EVERY)
        except InstagramError as exc:
            log.warning(f"{channel.key}: Instagram post of {video_path.stem}: {exc}")
            if exc.reconnect:
                _note_problem(exc.user_message)
                _set_auto(video_path, error=exc.user_message)
                return "waiting"
            if exc.transient:
                _set_auto(video_path, error=exc.user_message)
                return "waiting"
            tries = int(auto.get("tries") or 0) + 1
            _set_auto(video_path, container=None, started_at=None, tries=tries, error=exc.user_message,
                      failed=exc.user_message if tries >= MAX_TRIES else None)
            return "failed" if tries >= MAX_TRIES else "waiting"


def _due(entry: dict, now: datetime) -> bool:
    """Whether a Short waiting for Instagram goes by itself now: handed off,
    asked for, or started within AUTO_WINDOW, and not given up on."""
    auto = entry.get("auto") or {}
    if entry.get("posted_at") or auto.get("failed"):
        return False
    times = [t for t in (_parse(entry.get("at")), _parse(auto.get("requested_at")), _parse(auto.get("started_at")))
             if t is not None]
    return bool(times) and now - max(times) <= AUTO_WINDOW


def on_its_way(entry: dict, now: datetime = None) -> bool:
    """Whether a Short's Instagram post is in the app's hands (started, or
    due to start), on a channel that posts there by itself: nothing for
    the owner to do."""
    auto = (entry or {}).get("auto") or {}
    return bool(entry) and not entry.get("posted_at") and not auto.get("failed") and (
        bool(auto.get("container")) or _due(entry, now or _now()))


def post_due(channels: dict, now: datetime = None) -> list:
    """Each scheduler pass: every Short waiting for Instagram, on a channel
    that posts there by itself, moved on a step. A line per Short posted
    or given up on."""
    if not accounts():
        return []
    now = now or _now()
    lines = []
    for key, channel in channels.items():
        if channel.archived or not channel.publishing.post_instagram:
            continue
        account = account_for(channel)
        directory = gallery.resolve_output_dir(channel.output_dir)
        if account is None or not directory.exists():
            continue
        for video in gallery.videos_in(directory, long=False):
            info = gallery.load_publish_info(video)
            entry = (info["handoff"] or {}).get("instagram")
            if not entry or info["discarded"] or not _due(entry, now):
                continue
            state = advance(channel, video, account)
            if state in ("posted", "failed"):
                lines.append(f"{channel.channel_display_name}: {info['title'] or video.stem} {state} on Instagram")
    return lines


def post_now(channel, video_path: Path) -> None:
    """"Post it for me": a Short past its two days, or one that failed,
    taken up now, in the background."""
    account = account_for(channel)
    if account is None:
        raise InstagramError("no account", user_message="Choose this channel's Instagram account in its Settings first.")
    entry = _entry(video_path)
    if "instagram" not in (gallery.load_publish_info(video_path)["handoff"] or {}):
        raise InstagramError("not handed off", user_message="This video isn't waiting for Instagram.")
    if entry.get("posted_at"):
        return
    _set_auto(video_path, requested_at=_now().isoformat(timespec="seconds"), failed=None, tries=None, error=None)

    def run():
        ends = time.monotonic() + NOW_LIMIT
        try:
            while advance(channel, video_path, account) == "processing" and time.monotonic() < ends:
                pass
        except Exception:  # noqa: BLE001 - a background thread's failure must reach the log
            log.exception(f"{channel.key}: posting {Path(video_path).stem} to Instagram failed")

    _in_background(run)


def _in_background(run) -> None:
    threading.Thread(target=run, daemon=True, name="instagram-post").start()


def busy() -> bool:
    """Whether a Reel is being started or published right now: a restart
    waits for it, as for an upload."""
    return _lock.locked()


def state(channel, video_path: Path) -> dict:
    """What the posting steps show for Instagram. {"auto": False} for a
    channel that posts there by hand; otherwise its account and one of
    "posted", "processing", "queued", "failed" or "older" (past its two
    days: "Post it for me"), with any error."""
    account = account_for(channel) if channel.publishing.post_instagram else None
    if account is None:
        return {"auto": False}
    entry = _entry(video_path)
    auto = entry.get("auto") or {}
    if entry.get("posted_at"):
        status = "posted"
    elif auto.get("failed"):
        status = "failed"
    elif auto.get("container"):
        status = "processing"
    elif on_its_way(entry):
        status = "queued"
    else:
        status = "older"
    return {"auto": True, "account": f"@{account.get('username')}" if account.get("username") else "",
            "status": status, "error": auto.get("failed") or auto.get("error") or ""}
