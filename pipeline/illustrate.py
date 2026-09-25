"""
Illustrations: one image in the channel's own style for something
footage can't show (inside a brain, a moment in history, a metaphor),
slowly pushed in under the narration.

gpt-image-1 at the portrait size (1024x1536, "medium": about 6 cents),
with the channel's art direction as its style so every illustration on a
channel looks like the same artist's. The image is drawn full-bleed with
nothing important in its bottom third, where the captions go, and never
with words in it (image models misspell them). See decision 040.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import requests

from core import costs
from core.errors import ExternalServiceError, MissingCredentialError
from core.logging_setup import get_logger

log = get_logger(__name__)

URL = "https://api.openai.com/v1/images/generations"
MODEL = "gpt-image-1"
SIZE = "1024x1536"
QUALITY = "medium"


def prompt_for(subject: str, style: dict) -> str:
    colours = ", ".join(style["colors"][k] for k in ("accent1", "accent2", "accent3", "accent4"))
    return (f"{subject}. Illustrated in this style: {style['prop_style']}. Palette built around "
            f"{colours} with background {style['background']['color']}. A full-bleed vertical "
            f"illustration, one clear focal point in the upper two thirds, calm and uncluttered "
            f"in the bottom third. Absolutely no text, letters, numbers, labels, captions or "
            f"logos anywhere in the image.")


def generate(subject: str, style: dict, out_path: Path) -> Path:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise MissingCredentialError("OPENAI_API_KEY", "illustrations")
    response = requests.post(URL, headers={"Authorization": f"Bearer {key}"}, timeout=240, json={
        "model": MODEL, "prompt": prompt_for(subject, style), "n": 1, "size": SIZE,
        "quality": QUALITY, "output_format": "png"})
    if response.status_code != 200:
        raise ExternalServiceError("The image service (OpenAI)",
                                   f"HTTP {response.status_code}: {response.text[:300]}",
                                   status=response.status_code,
                                   user_message="Couldn't draw an illustration.")
    costs.record_openai_images("illustration", MODEL, 1, QUALITY, portrait=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(base64.b64decode(response.json()["data"][0]["b64_json"]))
    return out_path


def make(subject: str, style: dict, seconds: float, out_stem: Path) -> Path:
    """An illustration of `subject`, drawn and slowly pushed in, as a clip."""
    from PIL import Image

    from pipeline.artwork import ken_burns

    image_path = generate(subject, style, out_stem.with_suffix(".png"))
    image = Image.open(io.BytesIO(image_path.read_bytes())).convert("RGB")
    log.info(f"  [illustration] {subject[:80]}")
    return ken_burns(image, seconds, out_stem.with_suffix(".mp4"))
