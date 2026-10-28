"""
Notifications on the owner's phone (decision 141).

The owner, 28 Oct: "it would also be good if i got notified on my phone
whenever a video gets posted, and other updates/breakdowns of things (eg
stuff to review, stuff to post, how the week has gone etc) ... at the
moment there are things like the teasers being published, and i need to
link the main video to the teaser, but there is no notification".

Sent through ntfy (ntfy.sh, or the owner's own server): a free phone app
that shows whatever is posted to a topic it subscribes to. Nothing is sent
until the owner chooses a topic. The topic is the only secret: anyone who
knows it can read it, so it's a long random one.

Four kinds, each on or off:
- out: a video went out on YouTube, or was marked posted on TikTok or
  Instagram; a teaser on a channel that links its film says what to set
  in Studio;
- needs: something new on Today's "Needs you";
- daily: at 08:00, what goes out today, what's waiting, the voice left;
- weekly: on Monday at 08:00, last week against the week before.
"""

from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timedelta, timezone

import requests

from core.logging_setup import get_logger
from core.paths import CACHE_DIR, PROJECT_ROOT, write_atomically

log = get_logger(__name__)

SETTINGS_PATH = PROJECT_ROOT / "config" / "notify.json"
STATE_PATH = CACHE_DIR / "notify_state.json"
KINDS = (("out", "Each video out"), ("needs", "Something needs you"), ("daily", "Morning summary"),
         ("weekly", "Monday: the week"))
SUMMARY_HOUR = 8
TIMEOUT = 10


def settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    kinds = data.get("kinds") or {}
    return {"topic": str(data.get("topic") or ""), "server": str(data.get("server") or "https://ntfy.sh").rstrip("/"),
            "kinds": {k: bool(kinds.get(k, True)) for k, _ in KINDS}}


def save(topic: str, server: str, kinds: dict) -> dict:
    topic = "".join(c for c in (topic or "") if c.isalnum() or c in "-_")[:64]
    server = (server or "https://ntfy.sh").strip().rstrip("/")
    if not server.startswith(("https://", "http://")):
        server = "https://" + server
    data = {"topic": topic, "server": server, "kinds": {k: bool(kinds.get(k)) for k, _ in KINDS}}
    write_atomically(SETTINGS_PATH, json.dumps(data, indent=1))
    return settings()


def new_topic() -> str:
    return "yt-" + secrets.token_urlsafe(12).replace("_", "").replace("-", "")[:16].lower()


def send(title: str, message: str, kind: str = "", click: str = "", tags: str = "", priority: int = 3,
         force: bool = False) -> bool:
    """One notification, if a topic is chosen and this kind is on (`force`:
    whatever the kinds, for the test button). True when ntfy took it."""
    s = settings()
    if not s["topic"] or (kind and not s["kinds"].get(kind) and not force):
        return False
    headers = {"Title": title.encode("utf-8"), "Priority": str(priority)}
    if click:
        headers["Click"] = click
    if tags:
        headers["Tags"] = tags
    try:
        response = requests.post(f"{s['server']}/{s['topic']}", data=message.encode("utf-8"),
                                 headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        log.warning(f"Notification not sent: {exc}")
        return False
    if not response.ok:
        log.warning(f"Notification not sent: HTTP {response.status_code}")
    return response.ok


# --- what to say ------------------------------------------------------------------------

def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    write_atomically(STATE_PATH, json.dumps(state))


def _video_id(url: str) -> str:
    for marker in ("watch?v=", "youtu.be/", "/shorts/"):
        if marker in (url or ""):
            return url.split(marker, 1)[1].split("&")[0].split("?")[0]
    return ""


def _app_link(path: str = "/m") -> str:
    """The app on the phone, when phone access is on."""
    from core import phone_access
    if not phone_access.settings()["enabled"]:
        return ""
    found = phone_access.addresses()
    return f"http://{found[0]}:5000{path}" if found else ""


def out_message(channel, row: dict) -> tuple:
    """(title, message, click) for a video that went out (core.digest row)."""
    from pathlib import Path

    from core import gallery, publish_queue
    where = " and ".join(label for label, _ in row["places"])
    title = f"{row['name']}: out on {where}"
    message = row["title"]
    click = next((url for _, url in row["places"] if url), "")
    youtube = next((url for label, url in row["places"] if label == "YouTube"), "")
    if row["kind"] == "teaser" and youtube and getattr(channel.documentary, "teasers_linked", False):
        film = publish_queue.film_of_teaser(channel, gallery.OUTPUT_DIR / Path(row["relpath"]))
        film_info = gallery.load_publish_info(film) if film is not None and film.exists() else {}
        film_title = film_info.get("title") or (film.stem.replace("_", " ") if film is not None else "its film")
        vid = _video_id(youtube)
        message += f"\nTo do: in Studio, set its Related video to \"{film_title}\"."
        if film_info and not film_info.get("youtube_url"):
            message += " (The film isn't on YouTube yet: do it once it is.)"
        if vid:
            click = f"https://studio.youtube.com/video/{vid}/edit"
        title = f"{row['name']}: teaser out, link its film"
    return title, message, click


def daily_message(channels: dict) -> str:
    from core import digest, gallery, voice_quota
    coming = digest.going_out(channels, days=1)
    lines = [f"Going out today: {len(coming)}" + (" (" + ", ".join(f"{r['when']:%H:%M} {r['name']}"
                                                                    for r in coming[:4]) + ")" if coming else "")]
    waiting = queued = 0
    for c in channels.values():
        counts = gallery.video_state_counts(c.output_dir)
        waiting += counts["waiting"]
        queued += counts["queued"]
    lines.append(f"To review: {waiting} · queued: {queued}")
    try:
        from core import publish_queue
        to_post = len(publish_queue.awaiting_posts(channels))
        lines.append(f"To post on TikTok/Instagram: {to_post}")
    except Exception as exc:  # noqa: BLE001 - the summary goes without that line
        log.warning(f"Morning summary: couldn't count what's to post: {exc}")
    quota = voice_quota.current()
    if quota is not None:
        lines.append(f"Voice left: {quota.remaining:,} of {quota.limit:,}")
    return "\n".join(lines)


def weekly_message(channels: dict) -> str:
    from core import insights
    w = insights.weekly(channels)["total"]
    full = [r for r in w["weeks"] if not r["partial"]]
    if len(full) < 2:
        return ""
    last, before = full[-1], full[-2]

    def line(label, key, unit=""):
        change = last["change"][key]
        arrow = "" if change is None else (f" (+{change}%)" if change > 0 else f" ({change}%)")
        value = f"{last[key]:.1f}" if unit == "h" else f"{last[key]:,}"
        return f"{label}: {value}{unit}{arrow}"
    return "\n".join([f"Week of {last['label']} against {before['label']}:",
                      line("Shorts views", "short_views"), line("Views per Short", "per_short"),
                      line("Long views", "long_views"), line("Watch hours", "hours", "h"),
                      line("Subscribers", "subs")])


def tick(channels: dict, now: datetime = None) -> list:
    """Whatever is due, sent. Returns the titles sent. The first run only
    marks what's already there as seen, so nothing old arrives at once."""
    s = settings()
    if not s["topic"]:
        return []
    from core import digest, today
    channels = {k: c for k, c in channels.items() if not c.archived and c.publishing.enabled}
    now = now or datetime.now().astimezone()
    state = _state()
    first = not state
    sent = []

    # Videos out since the last look.
    after = datetime.fromtimestamp(state.get("out_checked", now.timestamp()), tz=timezone.utc)
    seen = set(state.get("out_seen") or [])
    for row in reversed(digest.went_out(channels, after - timedelta(minutes=10))):
        key = f"{row['relpath']}|{'+'.join(label for label, _ in row['places'])}"
        if key in seen:
            continue
        seen.add(key)
        if not first:
            title, message, click = out_message(channels[row["channel"]], row)
            if send(title, message, kind="out", click=click, tags="movie_camera"):
                sent.append(title)
    state["out_checked"] = now.timestamp()
    state["out_seen"] = sorted(seen)[-400:]

    # New things needing the owner.
    try:
        items = today.needs_you(channels, lambda *a, **k: "")
    except Exception as exc:  # noqa: BLE001 - the other notifications still go
        log.warning(f"Notifications: couldn't read what needs you: {exc}")
        items = None
    if items is not None:
        known = set(state.get("needs_seen") or [])
        current = {i.title for i in items}
        for item in items:
            if item.title not in known and not first:
                if send("Needs you: " + item.title, item.detail or item.title, kind="needs",
                        click=_app_link(), tags="warning" if item.severity == "bad" else "bell"):
                    sent.append(item.title)
        state["needs_seen"] = sorted(current)

    # The morning summary, and on Monday the week.
    stamp = now.strftime("%Y-%m-%d")
    if now.hour >= SUMMARY_HOUR and state.get("daily_sent") != stamp:
        if not first and send(f"Today, {now:%a %d %b}", daily_message(channels), kind="daily",
                              click=_app_link(), tags="sunrise"):
            sent.append("daily")
        state["daily_sent"] = stamp
        if now.weekday() == 0 and state.get("weekly_sent") != stamp:
            message = weekly_message(channels)
            if message and not first and send("How last week went", message, kind="weekly",
                                               click=_app_link(), tags="chart_with_upwards_trend"):
                sent.append("weekly")
            state["weekly_sent"] = stamp
    _save_state(state)
    return sent
