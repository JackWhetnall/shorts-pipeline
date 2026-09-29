"""
Pictures with references: keyframes, style frames and cast sheets.

Consistency comes from here. Every keyframe is drawn with the channel's
style frame as a reference, and with the model sheet of every character
and place in it, so a character is the same character in every shot and
every video, and every frame is the same hand (decision 051). OpenAI's
image models take several reference pictures on their edits endpoint and
are billed by the token, which they report, so the cost recorded is the
real one.
"""

from __future__ import annotations

import base64
import io
import os
import re
import threading
import time
from collections import deque
from pathlib import Path

import requests

from core import costs
from core.errors import ExternalServiceError, MissingCredentialError
from core.logging_setup import get_logger
from pipeline.animation.models import ImageModel

log = get_logger(__name__)

GENERATIONS = "https://api.openai.com/v1/images/generations"
EDITS = "https://api.openai.com/v1/images/edits"
SERVICE = "The image service (OpenAI)"
PORTRAIT = (864, 1536)          # 9:16, both sides multiples of 16
LANDSCAPE = (1536, 1024)        # model sheets: a character three times across
ATTEMPTS = 4
# A rate limit is waited out, not failed on: this many tries.
RATE_LIMITED_ATTEMPTS = 8
# References are sent no larger than this: the model reads a picture's
# style and identity from far fewer pixels, and pays per pixel read.
REFERENCE_SIDE = 1024

# OpenAI limits its image models per minute by the account's usage tier,
# counted in input images. This account's is 5 (29 Sep 2026): drawing the
# looks' examples four at a time lost ten of forty to 429s, and a video's
# keyframes, drawn in parallel with two to four references each, would
# have lost frames the same way. So every call waits its turn here, a
# call with references counting each one, and a 429 that states the limit
# resets it (a higher tier raises it by itself).
per_minute = 5
_sent = deque()                 # (monotonic time, weight)
_turn = threading.Lock()


def _wait_turn(weight: int) -> None:
    weight = max(1, min(weight, per_minute))
    while True:
        with _turn:
            now = time.monotonic()
            while _sent and now - _sent[0][0] >= 60:
                _sent.popleft()
            if not _sent or sum(w for _, w in _sent) + weight <= per_minute:
                _sent.append((now, weight))
                return
            wait = 60.5 - (now - _sent[0][0])
        time.sleep(max(0.5, wait))


def _rate_limited(response) -> float:
    """Seconds to wait after a 429, learning the stated limit on the way."""
    global per_minute
    text = response.text or ""
    limit = re.search(r"Limit (\d+)", text)
    if limit and "per min" in text:
        per_minute = max(1, int(limit.group(1)))
    again = re.search(r"try again in ([\d.]+)\s*(ms|s)", text)
    if again:
        seconds = float(again.group(1)) / (1000 if again.group(2) == "ms" else 1)
    else:
        seconds = float(response.headers.get("retry-after") or 15)
    return min(90.0, seconds + 1.0)


def _key() -> str:
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value:
        raise MissingCredentialError("OPENAI_API_KEY", "animation keyframes")
    return value


def _reference_bytes(path: Path) -> bytes:
    from PIL import Image

    image = Image.open(path).convert("RGB")
    image.thumbnail((REFERENCE_SIDE, REFERENCE_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _error(response) -> ExternalServiceError:
    text = response.text[:500]
    status = response.status_code
    lowered = text.lower()
    if "moderation" in lowered or "safety" in lowered:
        message = "OpenAI's safety system refused a picture this video needed."
    elif status == 429 and "rate limit" in lowered:
        message = (f"OpenAI kept this account at its image limit ({per_minute} a minute) for "
                   f"too long. Retrying later works; a higher usage tier raises the limit.")
    elif status in (401, 403):
        message = ("OPENAI_API_KEY was rejected, or this organisation isn't verified for "
                   "the image models. Check platform.openai.com.")
    elif "billing" in lowered or "quota" in lowered:
        message = "The OpenAI account is out of credit. Top it up on its billing page."
    elif status == 404 or "model" in lowered and status == 400:
        message = "This OpenAI key can't use the chosen image model. Pick another in the channel's animation settings."
    else:
        message = "Couldn't draw a picture for the animation. The details are in the log."
    return ExternalServiceError(SERVICE, f"HTTP {status}: {text}", status=status,
                                user_message=message)


def draw(prompt: str, out_path: Path, model: ImageModel, *, references=(),
         size: tuple = PORTRAIT, operation: str = "animation_keyframe",
         quality: str = None) -> Path:
    """One picture from `prompt`, drawn with `references` (paths, in the
    order the prompt names them) when there are any. Saved at out_path;
    the format follows its suffix (.png or .jpg)."""
    out_path = Path(out_path)
    fmt = "png" if out_path.suffix.lower() == ".png" else "jpeg"
    fields = {"model": model.model, "prompt": prompt, "n": "1",
              "size": f"{size[0]}x{size[1]}", "quality": quality or model.quality,
              "output_format": fmt}
    if fmt == "jpeg":
        fields["output_compression"] = "92"
    refs = [Path(p) for p in references if p]
    headers = {"Authorization": f"Bearer {_key()}"}
    attempt = limited = 0
    while True:
        _wait_turn(len(refs))
        try:
            if refs:
                files = [("image[]", (f"ref{i}.png", _reference_bytes(p), "image/png"))
                         for i, p in enumerate(refs)]
                response = requests.post(EDITS, headers=headers, data=fields, files=files,
                                         timeout=300)
            else:
                body = dict(fields, n=1)
                if fmt == "jpeg":
                    body["output_compression"] = 92
                response = requests.post(GENERATIONS, headers=headers, json=body, timeout=300)
        except requests.RequestException as exc:
            attempt += 1
            if attempt >= ATTEMPTS:
                raise ExternalServiceError(SERVICE, str(exc),
                                           user_message="Couldn't reach OpenAI to draw a "
                                                        "picture.") from exc
            time.sleep(3 * attempt)
            continue
        text = response.text or ""
        if response.status_code == 429 and "rate limit" in text.lower():
            # Waited out, however long it takes: the limiter above should
            # make this rare, and a lost frame costs more than a minute.
            limited += 1
            if limited < RATE_LIMITED_ATTEMPTS:
                wait = _rate_limited(response)
                log.info(f"  [animation] image service at its limit ({per_minute} a minute); "
                         f"waiting {wait:.0f}s")
                time.sleep(wait)
                continue
        elif response.status_code >= 500:
            attempt += 1
            if attempt < ATTEMPTS:
                time.sleep(10 * attempt)
                continue
        if response.status_code != 200:
            raise _error(response)
        data = response.json()
        costs.record_openai_image_usage(operation, model.model, data.get("usage"),
                                        model.estimate)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(data["data"][0]["b64_json"]))
        return out_path
