"""
How often each video's thumbnail is shown, and how often it's clicked
(decision 083).

The Analytics API has no thumbnail figures; the bulk Reporting API does,
per video per day: the `channel_reach_basic_a1` report, with
`video_thumbnail_impressions` and `video_thumbnail_impressions_ctr`. A
reporting job is created once per channel, and YouTube then writes a
report a day, about two days behind. Each is fetched once and kept as
{video id: {date: [impressions, ctr]}} in channels/<key>/reach.json.

It reads with the analytics scope the channel already granted
(core.youtube). The YouTube Reporting API has to be switched on in the
Google Cloud project once; until it is, fetching says so and nothing else
is affected.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import requests

from core.errors import ExternalServiceError
from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR

log = get_logger(__name__)

API = "https://youtubereporting.googleapis.com/v1"
REPORT_TYPE = "channel_reach_basic_a1"
TIMEOUT = 30


def _path(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "reach.json"


def load(channel_key: str) -> dict:
    try:
        data = json.loads(_path(channel_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("videos", {})
    data.setdefault("fetched", [])
    return data


def _save(channel_key: str, data: dict) -> None:
    path = _path(channel_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _get(token: str, url: str, **params):
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=TIMEOUT)
    if response.status_code >= 400:
        raise _error(response)
    return response


def _error(response) -> ExternalServiceError:
    text = response.text[:300]
    if response.status_code == 403 and ("disabled" in text or "not been used" in text):
        message = ("The YouTube Reporting API isn't switched on for this app's Google Cloud project: "
                   "turn it on there (APIs and services, Library), then it fills in by itself.")
    else:
        message = f"YouTube's reporting service said no ({response.status_code})."
    return ExternalServiceError(f"reporting {response.status_code}: {text}", user_message=message)


def ensure_job(channel_key: str) -> str:
    """The channel's reach reporting job, created on first use."""
    from core import youtube
    data = load(channel_key)
    if data.get("job_id"):
        return data["job_id"]
    token = youtube.access_token(channel_key)
    jobs = _get(token, f"{API}/jobs").json().get("jobs") or []
    job = next((j for j in jobs if j.get("reportTypeId") == REPORT_TYPE), None)
    if job is None:
        response = requests.post(f"{API}/jobs", headers={"Authorization": f"Bearer {token}"},
                                 json={"reportTypeId": REPORT_TYPE, "name": "Thumbnail reach"}, timeout=TIMEOUT)
        if response.status_code >= 400:
            raise _error(response)
        job = response.json()
        log.info(f"{channel_key}: thumbnail reach reporting started; the first report comes in a day or two")
    data["job_id"] = job["id"]
    _save(channel_key, data)
    return job["id"]


def fetch(channel_key: str) -> int:
    """Every new daily report, read and kept. Returns how many were new."""
    from core import youtube
    job_id = ensure_job(channel_key)
    token = youtube.access_token(channel_key)
    data = load(channel_key)
    reports = _get(token, f"{API}/jobs/{job_id}/reports").json().get("reports") or []
    new = [r for r in reports if r["id"] not in data["fetched"]]
    for report in new:
        body = _get(token, report["downloadUrl"]).content.decode("utf-8", errors="replace")
        for row in csv.DictReader(io.StringIO(body)):
            video, day = row.get("video_id"), row.get("date")
            if not video or not day:
                continue
            try:
                shown = int(float(row.get("video_thumbnail_impressions") or 0))
                ctr = float(row.get("video_thumbnail_impressions_ctr") or 0)
            except ValueError:
                continue
            day = f"{day[:4]}-{day[4:6]}-{day[6:8]}" if len(day) == 8 else day
            data["videos"].setdefault(video, {})[day] = [shown, ctr]
        data["fetched"].append(report["id"])
    if new:
        _save(channel_key, data)
    return len(new)


def note_error(channel_key: str, message: str) -> None:
    data = load(channel_key)
    data["error"] = message
    _save(channel_key, data)


def clear_error(channel_key: str) -> None:
    data = load(channel_key)
    if data.pop("error", None) is not None:
        _save(channel_key, data)


def days(channel_key: str, video_id: str) -> dict:
    """{"YYYY-MM-DD": (impressions, click-through)} for one video."""
    return {d: tuple(v) for d, v in load(channel_key)["videos"].get(video_id, {}).items()}
