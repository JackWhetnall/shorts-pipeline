"""
Channel logo generation via OpenAI's Images API. No text/branding baked
into what the user edits — they only supply a short "what's this channel
about" fragment; the professional/no-text/logo/merch-suitable framing
lives entirely in build_prompt() below, never shown as raw editable text.

POST https://api.openai.com/v1/images/generations with n=10 generates all
candidates in a single call (unlike per-image-call providers) — see
CLAUDE.md's "Channel logos" section for why this provider was picked.
Plain `requests`, no SDK, matching the ElevenLabs integration's pattern.

Layout under channels/<key>/logo/:
  candidates/<uuid>_<i>.png   — the most recent generation batch
  logo.png                   — the selected primary logo
  variant_minimalist.png     — a second real generation call (genuine
                                restyling, not a mechanical transform)
  variant_monochrome.png     — derived LOCALLY via Pillow (grayscale +
                                threshold) from the chosen logo — a
                                deterministic image-processing step, not
                                a creative one, so it doesn't need a
                                second paid generation call.
"""

import base64
import os
import shutil
import uuid
from pathlib import Path

import requests
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHANNELS_DIR = PROJECT_ROOT / "channels"

OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
OPENAI_MODEL = "gpt-image-1"
IMAGE_SIZE = "1024x1024"

PROMPT_TEMPLATE = (
    "A professional graphic-design logo mark for a YouTube channel about "
    "{topic}. Clean, modern, flat vector-style illustration. No text, no "
    "letters, no words anywhere in the image. Centered composition, "
    "simple and bold enough to be legible small and to print clearly on "
    "a t-shirt or mug. Plain or transparent-style background."
)
MINIMALIST_SUFFIX = " Ultra-minimalist single-line icon version."


def _openai_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY")


def build_prompt(fragment: str, minimalist: bool = False) -> str:
    prompt = PROMPT_TEMPLATE.format(topic=fragment.strip())
    if minimalist:
        prompt += MINIMALIST_SUFFIX
    return prompt


def _logo_dir(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "logo"


def _candidates_dir(channel_key: str) -> Path:
    return _logo_dir(channel_key) / "candidates"


def _call_openai_images(prompt: str, n: int) -> list:
    """Returns a list of raw PNG bytes, one per generated image."""
    api_key = _openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in your environment.")

    response = requests.post(
        OPENAI_IMAGES_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": OPENAI_MODEL, "prompt": prompt, "n": n, "size": IMAGE_SIZE},
        timeout=120,
    )
    if not response.ok:
        try:
            message = response.json().get("error", {}).get("message")
        except ValueError:
            message = response.text
        raise RuntimeError(f"OpenAI image request failed ({response.status_code}): "
                            f"{message or 'no further detail returned'}")

    data = response.json()
    return [base64.b64decode(item["b64_json"]) for item in data["data"]]


def generate_candidates(channel_key: str, fragment: str, n: int = 10) -> list:
    """One OpenAI call for n candidates. Clears any previous candidates
    batch first (only the most recent batch is kept — old unselected
    candidates aren't worth holding onto)."""
    candidates_dir = _candidates_dir(channel_key)
    if candidates_dir.exists():
        shutil.rmtree(candidates_dir)
    candidates_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(fragment)
    images = _call_openai_images(prompt, n)

    batch_id = uuid.uuid4().hex[:8]
    paths = []
    for i, image_bytes in enumerate(images):
        path = candidates_dir / f"{batch_id}_{i}.png"
        path.write_bytes(image_bytes)
        paths.append(path)
    return paths


def _make_monochrome_variant(logo_path: Path, out_path: Path, ink_color=(20, 20, 20)):
    """Grayscale + threshold to a single ink color on a transparent
    background — a flat single-color version suitable for one-color
    screen printing. Purely local Pillow work, no API call."""
    img = Image.open(logo_path).convert("RGBA")
    gray = img.convert("L")
    # Anything reasonably dark becomes solid ink; light/background stays
    # transparent — works for logos generated on a plain light background.
    mask = gray.point(lambda p: 255 if p < 200 else 0)
    solid = Image.new("RGBA", img.size, (*ink_color, 255))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(solid, mask=mask)
    out.save(out_path)


def select_logo(channel_key: str, candidate_path: Path, fragment: str) -> dict:
    """Finalizes one candidate as the channel's logo and generates both
    variants. fragment is the same text used to generate the candidate
    batch, reused for the minimalist variant's prompt."""
    logo_dir = _logo_dir(channel_key)
    logo_dir.mkdir(parents=True, exist_ok=True)

    logo_path = logo_dir / "logo.png"
    shutil.copy2(candidate_path, logo_path)

    minimalist_path = logo_dir / "variant_minimalist.png"
    minimalist_prompt = build_prompt(fragment, minimalist=True)
    minimalist_bytes = _call_openai_images(minimalist_prompt, 1)[0]
    minimalist_path.write_bytes(minimalist_bytes)

    monochrome_path = logo_dir / "variant_monochrome.png"
    _make_monochrome_variant(logo_path, monochrome_path)

    return {"logo": logo_path, "minimalist": minimalist_path, "monochrome": monochrome_path}


def get_logo_path(channel_key: str) -> Path:
    return _logo_dir(channel_key) / "logo.png"


def has_logo(channel_key: str) -> bool:
    return get_logo_path(channel_key).exists()
