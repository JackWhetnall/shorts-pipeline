"""
Channel logo generation via OpenAI's Images API. No text/branding baked
into what the user edits — they only supply a short "what's this channel
about" fragment; the framing lives entirely in build_prompt() below,
never shown as raw editable text. The channel this builds a brand for
isn't YouTube-exclusive (also posted to TikTok/Instagram), so
PROMPT_TEMPLATE deliberately says "content channel", never "YouTube
channel", and explicitly excludes platform logos/app icons — an earlier
version that said "YouTube channel" was coming back with YouTube
play-button imagery baked into the mark, which is wrong for a logo meant
to represent the channel itself across every platform it's posted to.

POST https://api.openai.com/v1/images/generations with n=CANDIDATE_COUNT
generates all candidates in a single call (unlike per-image-call
providers) — see CLAUDE.md's "Channel logos" section for why this
provider was picked. Plain `requests`, no SDK, matching the ElevenLabs
integration's pattern.

Cost: gpt-image-1 is not cheap (a real batch of 20 images cost ~$3), so
two levers control it here. First, CANDIDATE_COUNT (5, was 10) — fewer
directions to browse per attempt, at the user's request. Second, quality:
candidates use IMAGE_QUALITY_CANDIDATES ("medium") since they only need
to be good enough to pick a direction from, not the final asset, while
the handful of merch variants generated later use IMAGE_QUALITY_FINAL
("high") since there are only a few of them and they ARE the final,
printable assets — spending more per-image there is worth it precisely
because there's so few of them.

The single full-n call is only the fast path: a live 429 ("Limit 5,
Requested 10" against this account's per-minute image-generation quota)
showed some OpenAI accounts cap how many images gpt-image-1 can generate
per minute well below what a batch might request. _generate_images()
tries the full request first — if the account's quota covers it, nothing
else happens — and only on that specific 429 falls back to generating
MAX_IMAGES_PER_MINUTE at a time, waiting a minute between batches so each
lands in a fresh window.

Two different jobs, two different prompt shapes — deliberately NOT one
"minimalist, merch-ready" prompt for everything: the candidates need to
be a bold, striking logo/profile picture people actually notice, so
PROMPT_TEMPLATE explicitly asks for depth/detail/color, not simplicity.
Picking a candidate (select_logo) only finalizes it as logo.png — it does
NOT generate merch variants. That used to happen automatically and
silently kicked off 1-3 more slow, paid API calls with zero UI feedback
right when the user thought they were done, which looked exactly like
"picking a logo does nothing" — the request was just sitting there
generating in the background, unannounced. Merch variants are now a
separate, explicit action (generate_merch_variants) triggered from the
merch step of the monetization wizard, once the user has actually decided
they want them — several DIFFERENT minimalist treatments (line art, flat
geometric, badge/emblem), not the same "make it minimal" style repeated,
so there's real stylistic variety to choose from for print.

Merch variants use OpenAI's images/EDITS endpoint, not generations: an
earlier version generated them from text alone (topic fragment + "redraw
the same subject as..."), which doesn't work — the model was never shown
the actual chosen logo, so "the same subject" was just an unfulfillable
instruction and every variant came back as an unrelated fresh
interpretation of the topic. The edits endpoint takes the real logo.png
bytes as input, so the restyle is actually grounded in the specific,
already-chosen image, not reconstructed from a text description of it.
This also means merch variants no longer need the topic fragment at all
— the source image supplies the subject.

Layout under channels/<key>/logo/:
  candidates/<uuid>_<i>.png   — the most recent generation batch
  logo.png                   — the selected primary logo: bold and
                                detailed, meant to read well as a channel
                                profile picture, not merch-flattened
  variant_<style.key>.png    — one real image-EDIT call per VARIANT_STYLES
                                entry, using logo.png as the input image
                                (genuine restyling of the actual logo, not
                                a fresh unrelated generation) — currently
                                line/geometric/badge
  variant_monochrome.png     — derived LOCALLY via Pillow (grayscale +
                                threshold) from the flat-geometric variant
                                (its bold solid shapes threshold to one
                                ink color far more cleanly than the
                                detailed primary logo would) — a
                                deterministic image-processing step, not
                                a creative one, so it doesn't need its own
                                paid generation call.
"""

import base64
import os
import shutil
import time
import uuid
from pathlib import Path

import requests
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHANNELS_DIR = PROJECT_ROOT / "channels"

OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
OPENAI_EDITS_URL = "https://api.openai.com/v1/images/edits"
OPENAI_MODEL = "gpt-image-1"
IMAGE_SIZE = "1024x1024"

PROMPT_TEMPLATE = (
    "A striking, professional graphic-design logo mark for a content "
    "creator's channel about {topic}, meant to be used as-is across "
    "several different social media platforms. Bold, memorable, and "
    "visually rich — real depth and polish (shading, gradients, and "
    "layered detail are all welcome, use a full, vivid color palette), "
    "the kind of logo that grabs attention and reads clearly even as a "
    "small profile-picture thumbnail. No text, no letters, no words, and "
    "no social-media app icons, play-button icons, camera icons, or any "
    "other brand or platform symbols anywhere in the image — just an "
    "original mark representing the subject itself, generic enough to "
    "work as a profile picture anywhere. Centered composition, plain or "
    "transparent-style background."
)

# Fewer directions to browse per attempt (was 10) and cheaper per-image
# quality for them (see module docstring) — both a direct response to
# real cost: a batch of 20 images at the old count/quality cost ~$3.
CANDIDATE_COUNT = 5
IMAGE_QUALITY_CANDIDATES = "medium"
IMAGE_QUALITY_FINAL = "high"

# Distinct merch-ready simplifications generated AFTER a primary logo is
# picked (select_logo) — deliberately several different minimalist
# treatments, not the same "make it minimal" style three times, so there's
# real stylistic choice for print. Each is its own genuine image-EDIT of
# the chosen logo.png (see build_edit_prompt / EDIT_PROMPT_TEMPLATE), not
# a fresh text-only generation and not a mechanical transform.
VARIANT_STYLES = [
    {
        "key": "line",
        "label": "Line art",
        "description": (
            "an ultra-minimalist single continuous-line icon: one thin, "
            "uniform-weight outline, no fill, no shading, no color"
        ),
    },
    {
        "key": "geometric",
        "label": "Flat geometric",
        "description": (
            "a minimalist flat geometric icon: built from a few bold solid "
            "shapes, at most two flat colors, no gradients, no fine "
            "detail, no outlines"
        ),
    },
    {
        "key": "badge",
        "label": "Badge / emblem",
        "description": (
            "a minimalist badge emblem: the subject simplified to a bold "
            "solid silhouette centered inside a simple circular or "
            "shield-shaped badge outline, at most two flat colors"
        ),
    },
]

EDIT_PROMPT_TEMPLATE = (
    "Restyle this exact logo image as {style_description}. Keep the same "
    "subject and composition as the source image — only change the "
    "rendering style, not what it depicts. No text, no letters, no words, "
    "and no social-media app icons, play-button icons, camera icons, or "
    "other platform/brand symbols anywhere in the image."
)


def build_edit_prompt(style_description: str) -> str:
    return EDIT_PROMPT_TEMPLATE.format(style_description=style_description)

# Fallback batch size when the full request gets rate-limited — matches the
# actual per-minute image-generation quota seen on this account (a real 429:
# "Limit 5, Requested 10"). Only used if the full request 429s; an account
# with a higher quota never hits this path at all.
MAX_IMAGES_PER_MINUTE = 5


class _RateLimitError(RuntimeError):
    pass


def _openai_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY")


def build_prompt(fragment: str, style_suffix: str = "") -> str:
    return PROMPT_TEMPLATE.format(topic=fragment.strip()) + style_suffix


def _logo_dir(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "logo"


def _candidates_dir(channel_key: str) -> Path:
    return _logo_dir(channel_key) / "candidates"


def _call_openai_images(prompt: str, n: int, quality: str = "auto") -> list:
    """Returns a list of raw PNG bytes, one per generated image."""
    api_key = _openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in your environment.")

    response = requests.post(
        OPENAI_IMAGES_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": OPENAI_MODEL, "prompt": prompt, "n": n, "size": IMAGE_SIZE, "quality": quality},
        timeout=120,
    )
    if not response.ok:
        try:
            message = response.json().get("error", {}).get("message")
        except ValueError:
            message = response.text
        error_cls = _RateLimitError if response.status_code == 429 else RuntimeError
        raise error_cls(f"OpenAI image request failed ({response.status_code}): "
                         f"{message or 'no further detail returned'}")

    data = response.json()
    return [base64.b64decode(item["b64_json"]) for item in data["data"]]


def _generate_images(prompt: str, n: int, quality: str = "auto") -> list:
    """Requests all n images in one call first — the fast path, and the
    only path for an account whose quota covers n. Only on a 429 from
    OpenAI's per-minute image-generation quota does this fall back to
    generating MAX_IMAGES_PER_MINUTE at a time, waiting a full minute
    between batches so each lands in a fresh quota window. A single
    mid-batch failure (network error, a non-rate-limit error from OpenAI)
    still propagates immediately rather than being retried — this fallback
    exists for the one specific, observed failure mode, not as a general
    retry loop."""
    try:
        return _call_openai_images(prompt, n, quality=quality)
    except _RateLimitError:
        pass

    print(f"  [logo] hit OpenAI's per-minute image-generation quota - "
          f"generating {n} image(s) in batches of {MAX_IMAGES_PER_MINUTE} instead "
          f"(this will take a bit longer)...")
    images = []
    remaining = n
    first = True
    while remaining > 0:
        batch_n = min(MAX_IMAGES_PER_MINUTE, remaining)
        if not first:
            time.sleep(61)
        images += _call_openai_images(prompt, batch_n, quality=quality)
        remaining -= batch_n
        first = False
    return images


def _call_openai_image_edit(prompt: str, image_bytes: bytes, quality: str = "auto") -> bytes:
    """Uses OpenAI's images/EDITS endpoint (multipart/form-data, unlike the
    JSON-only generations endpoint) so the source image is actually used
    as a reference for the restyle — this is what makes a merch variant a
    restyle of the SPECIFIC chosen logo, not an unrelated fresh
    interpretation of the topic text (see module docstring). Always n=1:
    every caller wants exactly one restyle per style per call."""
    api_key = _openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in your environment.")

    response = requests.post(
        OPENAI_EDITS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        data={"model": OPENAI_MODEL, "prompt": prompt, "n": "1", "size": IMAGE_SIZE, "quality": quality},
        files={"image": ("logo.png", image_bytes, "image/png")},
        timeout=120,
    )
    if not response.ok:
        try:
            message = response.json().get("error", {}).get("message")
        except ValueError:
            message = response.text
        error_cls = _RateLimitError if response.status_code == 429 else RuntimeError
        raise error_cls(f"OpenAI image edit request failed ({response.status_code}): "
                         f"{message or 'no further detail returned'}")

    data = response.json()
    return base64.b64decode(data["data"][0]["b64_json"])


def _generate_image_edit(prompt: str, image_bytes: bytes, quality: str = "auto") -> bytes:
    """Single-image edit with one wait-and-retry on the per-minute image
    quota (same real limit _generate_images works around on the
    generations path) — a single edit call can't be split into smaller
    batches the way a multi-image generation request can, so the only
    lever here is waiting for the quota to reset before the one retry."""
    try:
        return _call_openai_image_edit(prompt, image_bytes, quality=quality)
    except _RateLimitError:
        print("  [logo] hit OpenAI's per-minute image quota - waiting a minute before retrying...")
        time.sleep(61)
        return _call_openai_image_edit(prompt, image_bytes, quality=quality)


def generate_candidates(channel_key: str, fragment: str, n: int = CANDIDATE_COUNT) -> list:
    """One OpenAI call for n candidates, at IMAGE_QUALITY_CANDIDATES (cheaper
    — these are for picking a direction, not the final asset). Clears any
    previous candidates batch first (only the most recent batch is kept —
    old unselected candidates aren't worth holding onto)."""
    candidates_dir = _candidates_dir(channel_key)
    if candidates_dir.exists():
        shutil.rmtree(candidates_dir)
    candidates_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(fragment)
    images = _generate_images(prompt, n, quality=IMAGE_QUALITY_CANDIDATES)

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


def select_logo(channel_key: str, candidate_path: Path) -> dict:
    """Finalizes one candidate as the channel's primary logo. Just a file
    copy — no API calls, no merch variants generated here (see module
    docstring for why that used to be a problem). Should return
    near-instantly."""
    logo_dir = _logo_dir(channel_key)
    logo_dir.mkdir(parents=True, exist_ok=True)

    logo_path = logo_dir / "logo.png"
    shutil.copy2(candidate_path, logo_path)

    return {"logo": logo_path}


def generate_merch_variants(channel_key: str) -> dict:
    """Generates each VARIANT_STYLES entry as its own real image-EDIT of
    the channel's already-selected logo.png (see module docstring — this
    is what actually grounds each variant in the specific chosen logo,
    rather than reinterpreting the topic from scratch), at
    IMAGE_QUALITY_FINAL since there are only a few of these and they're
    the actual printable assets, plus one monochrome derived locally from
    the flat-geometric variant. Explicit and user-triggered (the merch
    step of the monetization wizard) — never called automatically. No
    topic fragment needed: the source image supplies the subject."""
    logo_dir = _logo_dir(channel_key)
    logo_path = logo_dir / "logo.png"
    if not logo_path.exists():
        raise RuntimeError("Pick a primary logo first.")
    logo_bytes = logo_path.read_bytes()

    variant_paths = {}
    for style in VARIANT_STYLES:
        variant_prompt = build_edit_prompt(style["description"])
        variant_bytes = _generate_image_edit(variant_prompt, logo_bytes, quality=IMAGE_QUALITY_FINAL)
        variant_path = logo_dir / f"variant_{style['key']}.png"
        variant_path.write_bytes(variant_bytes)
        variant_paths[style["key"]] = variant_path

    monochrome_source = variant_paths.get("geometric", logo_path)
    monochrome_path = logo_dir / "variant_monochrome.png"
    _make_monochrome_variant(monochrome_source, monochrome_path)
    variant_paths["monochrome"] = monochrome_path

    return variant_paths


def get_logo_path(channel_key: str) -> Path:
    return _logo_dir(channel_key) / "logo.png"


def has_logo(channel_key: str) -> bool:
    return get_logo_path(channel_key).exists()


def has_merch_variants(channel_key: str) -> bool:
    logo_dir = _logo_dir(channel_key)
    return all((logo_dir / f"variant_{s['key']}.png").exists() for s in VARIANT_STYLES)
