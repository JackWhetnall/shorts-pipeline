"""
fal: one key for the video models (pipeline.animation.models).

A generation is queued, polled until it finishes and then fetched, over
fal's plain HTTP queue API (https://fal.ai/docs/model-apis/model-endpoints/queue).
Their Python client would do the same through httpx and a thread pool of
its own; requests is what the rest of this project already uses. Pictures
go up inline as data URIs, which fal accepts for any file input.
"""

from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path

import requests

from core.errors import ExternalServiceError, MissingCredentialError
from core.logging_setup import get_logger

log = get_logger(__name__)

QUEUE = "https://queue.fal.run"
SERVICE = "The video service (fal)"
POLL_SECONDS = 3.0
# A 10-second shot takes well under a minute; a busy queue can hold one
# for several. Past this it has stuck, and the shot degrades instead.
TIMEOUT_SECONDS = 900
# Transient failures (a dropped connection, a 5xx, a 429) are retried
# this many times with a growing pause. Anything else is ours to fix.
ATTEMPTS = 3


def key() -> str:
    value = os.environ.get("FAL_KEY", "").strip()
    if not value:
        raise MissingCredentialError("FAL_KEY", "generated animation")
    return value


def configured() -> bool:
    return bool(os.environ.get("FAL_KEY", "").strip())


def data_uri(path: Path, max_side: int = 1536) -> str:
    """A picture as a JPEG data URI, no larger than the model needs."""
    from PIL import Image

    image = Image.open(path).convert("RGB")
    image.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=93)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def _error(status: int, body: str, what: str) -> ExternalServiceError:
    text = (body or "")[:400]
    lowered = text.lower()
    if status in (401,) or "invalid key" in lowered or "unauthorized" in lowered:
        message = "FAL_KEY was rejected. Check that it's set correctly and still valid."
    elif "balance" in lowered or "locked" in lowered or status == 402:
        message = "The fal account is out of credit. Top it up at fal.ai/dashboard/billing."
    elif status == 422 and ("content" in lowered or "safety" in lowered or "nsfw" in lowered):
        message = f"fal's safety filter refused {what}."
    elif status == 429:
        message = "fal is limiting how fast requests can be made. Retrying should work."
    elif status >= 500:
        message = "fal is having problems on their end. Retrying should work once it recovers."
    else:
        message = f"fal couldn't make {what}. The details are in the log."
    return ExternalServiceError(SERVICE, f"HTTP {status}: {text}", status=status,
                                user_message=message)


def _request(method: str, url: str, what: str, **kwargs):
    headers = {"Authorization": f"Key {key()}", **kwargs.pop("headers", {})}
    for attempt in range(ATTEMPTS):
        try:
            response = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        except requests.RequestException as exc:
            if attempt == ATTEMPTS - 1:
                raise ExternalServiceError(SERVICE, f"{method} {url}: {exc}",
                                           user_message="Couldn't reach fal. Check the "
                                                        "connection and retry.") from exc
            time.sleep(2 * (attempt + 1))
            continue
        if response.status_code in (429,) or response.status_code >= 500:
            if attempt < ATTEMPTS - 1:
                time.sleep(float(response.headers.get("retry-after") or 3 * (attempt + 1)))
                continue
        if response.status_code >= 400:
            raise _error(response.status_code, response.text, what)
        return response
    raise ExternalServiceError(SERVICE, f"{method} {url}: out of attempts")


def run(endpoint: str, payload: dict, what: str = "a shot",
        timeout: float = TIMEOUT_SECONDS) -> dict:
    """Queue one generation, wait for it and return its result."""
    submitted = _request("POST", f"{QUEUE}/{endpoint}", what, json=payload).json()
    status_url = submitted.get("status_url") or \
        f"{QUEUE}/{endpoint}/requests/{submitted['request_id']}/status"
    response_url = submitted.get("response_url") or \
        f"{QUEUE}/{endpoint}/requests/{submitted['request_id']}"
    started = time.monotonic()
    while True:
        status = _request("GET", status_url, what).json()
        state = status.get("status")
        if state == "COMPLETED":
            if status.get("error"):
                raise ExternalServiceError(
                    SERVICE, f"{endpoint}: {status.get('error_type')}: {status.get('error')}",
                    user_message=f"fal couldn't make {what}: {str(status.get('error'))[:160]}")
            break
        if time.monotonic() - started > timeout:
            try:
                _request("PUT", submitted.get("cancel_url") or f"{response_url}/cancel", what)
            except ExternalServiceError:
                pass
            raise ExternalServiceError(SERVICE, f"{endpoint}: still {state} after {timeout:.0f}s",
                                       user_message=f"fal took too long to make {what}.")
        time.sleep(POLL_SECONDS)
    return _request("GET", response_url, what).json()


def download(url: str, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(ATTEMPTS):
        try:
            with requests.get(url, stream=True, timeout=120) as response:
                response.raise_for_status()
                partial = out_path.with_suffix(out_path.suffix + ".partial")
                with open(partial, "wb") as f:
                    for chunk in response.iter_content(1 << 16):
                        f.write(chunk)
                partial.replace(out_path)
                return out_path
        except requests.RequestException as exc:
            if attempt == ATTEMPTS - 1:
                raise ExternalServiceError(SERVICE, f"download {url}: {exc}",
                                           user_message="A finished shot couldn't be "
                                                        "downloaded from fal.") from exc
            time.sleep(2 * (attempt + 1))
    return out_path
