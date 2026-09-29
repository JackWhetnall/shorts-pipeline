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
import time
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
# References are sent no larger than this: the model reads a picture's
# style and identity from far fewer pixels, and pays per pixel read.
REFERENCE_SIDE = 1024


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
    for attempt in range(ATTEMPTS):
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
            if attempt == ATTEMPTS - 1:
                raise ExternalServiceError(SERVICE, str(exc),
                                           user_message="Couldn't reach OpenAI to draw a "
                                                        "picture.") from exc
            time.sleep(3 * (attempt + 1))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            # Image models are limited per minute on smaller accounts; the
            # header says how long to wait.
            if attempt < ATTEMPTS - 1:
                wait = float(response.headers.get("retry-after") or 0) or 12 * (attempt + 1)
                log.info(f"  [animation] image service busy; waiting {wait:.0f}s")
                time.sleep(min(wait, 60))
                continue
        if response.status_code != 200:
            raise _error(response)
        data = response.json()
        costs.record_openai_image_usage(operation, model.model, data.get("usage"),
                                        model.estimate)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(data["data"][0]["b64_json"]))
        return out_path
    raise ExternalServiceError(SERVICE, "out of attempts",
                               user_message="OpenAI stayed busy; the picture couldn't be drawn.")
