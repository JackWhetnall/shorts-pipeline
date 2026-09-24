"""
The prop library: illustrated objects for scenes, drawn once in a
channel's art style and reused.

A scene asks for "piggy bank"; if the channel's library already has one
it's used as is, so the channel's piggy bank is the same piggy bank in
every video. If not, it's generated once, in the art direction's
`prop_style`, on a transparent background (OpenAI's image model, the
same one logos use), and saved. That's what holds a channel's look
steady across videos, and why the cost of props falls as a channel runs.
See docs/specs/animated-scenes.md §3.4.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import requests

from core import costs
from core.errors import ExternalServiceError, MissingCredentialError
from core.logging_setup import get_logger

log = get_logger(__name__)

IMAGES_URL = "https://api.openai.com/v1/images/generations"
MODEL = "gpt-image-1"
SIZE = "1024x1024"
QUALITY = "medium"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "prop"


def prompt_for(name: str, prop_style: str, detail: str = "") -> str:
    return (f"A single {name}{', ' + detail if detail else ''}. {prop_style}. "
            f"One object only, centred, filling most of the frame, fully visible with "
            f"nothing cropped, isolated on a transparent background, no ground shadow, "
            f"no text, no lettering, no border.")


def get(library: Path, name: str, prop_style: str, detail: str = "") -> Path:
    """The prop's PNG, generating it the first time it's asked for."""
    library = Path(library)
    path = library / f"{slug(name)}.png"
    if path.exists():
        return path
    library.mkdir(parents=True, exist_ok=True)
    path.write_bytes(clean(_generate(prompt_for(name, prop_style, detail))))
    log.info(f"  [scene] new prop: {name} -> {path.name}")
    return path


# Generated "transparent" backgrounds carry faint stray alpha, and
# sometimes a hairline frame round the very edge of the canvas; either
# shows as a ghostly box around the prop. Anything below the floor, and
# anything in the outermost band (the prompt keeps the object off the
# edge), is made fully transparent.
ALPHA_FLOOR = 24
EDGE_BAND = 4
MAX_SIDE = 640          # plenty for a prop that fills at most half the frame's width


def clean(png: bytes) -> bytes:
    """Zero stray alpha and any edge frame, trim to the object, and downsize."""
    import io
    from PIL import Image, ImageDraw

    image = Image.open(io.BytesIO(png)).convert("RGBA")
    alpha = image.getchannel("A").point(lambda a: 0 if a < ALPHA_FLOOR else a)
    w, h = alpha.size
    if w > 4 * EDGE_BAND and h > 4 * EDGE_BAND:
        ImageDraw.Draw(alpha).rectangle((0, 0, w - 1, h - 1), outline=0, width=EDGE_BAND)
    image.putalpha(alpha)
    box = alpha.getbbox()
    if box:
        pad = 8
        image = image.crop((max(0, box[0] - pad), max(0, box[1] - pad),
                            min(image.width, box[2] + pad), min(image.height, box[3] + pad)))
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _generate(prompt: str) -> bytes:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise MissingCredentialError("OPENAI_API_KEY", "illustrated scene props")
    response = requests.post(
        IMAGES_URL, headers={"Authorization": f"Bearer {key}"}, timeout=180,
        json={"model": MODEL, "prompt": prompt, "n": 1, "size": SIZE, "quality": QUALITY,
              "background": "transparent", "output_format": "png"})
    if response.status_code != 200:
        raise ExternalServiceError("The image service (OpenAI)",
                                   f"HTTP {response.status_code}: {response.text[:300]}",
                                   status=response.status_code,
                                   user_message="Couldn't draw a prop for an animated scene.")
    costs.record_openai_images("scene_prop", MODEL, 1, QUALITY)
    return base64.b64decode(response.json()["data"][0]["b64_json"])
