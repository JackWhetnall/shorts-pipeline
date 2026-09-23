"""
A still background image for a channel's title and outro cards.

Every card in every video currently sits on a flat colour. That is fine
and it is also the most obviously templated thing a viewer sees — the
same rectangle, every video, across every channel. A photograph chosen
once per channel costs nothing per video and does more for how the output
reads than any other single change of this size.

## Where the pictures come from

Pexels and Pixabay, the same two sites the footage library already uses,
under the same licences and with the same keys. Their *photo* endpoints
rather than their video ones. Nothing is downloaded until a picture is
chosen: search returns preview URLs the browser loads directly.

## The edits, and why only these two

Blur and dim, and nothing else.

A background has one job: to be behind text without competing with it.
Blur removes the detail that fights the letterforms; dim buys contrast.
Anything else — crops, filters, overlays — is a photo editor, and this is
not one. Both are applied once, at the moment the picture is saved, and
the original is kept beside the result so the sliders can be moved again
later without re-downloading.

## Licences

Recorded per channel in `background.json`, the same way the footage
library records a clip's licence, because the same question gets asked at
monetization time.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from core.errors import ExternalServiceError, PipelineError
from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR, FRAME_HEIGHT, FRAME_WIDTH, safe_join

log = get_logger(__name__)

PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"
PIXABAY_PHOTO_URL = "https://pixabay.com/api/"

SEARCH_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 60

# Enough to choose from without being a wall. Twelve fits a 3- or 4-wide
# grid without scrolling on a laptop.
RESULTS_PER_SITE = 6

# Blur is in pixels of Gaussian radius at 1080x1920. Above about 30 the
# picture stops being a picture, which is a legitimate thing to want but
# not something to allow by accident.
MAX_BLUR = 30
# Dim is a percentage of black laid over the top.
MAX_DIM = 85

LICENCES = {
    "pexels": "Pexels License - free for commercial use, no attribution required",
    "pixabay": "Pixabay Content License - free for commercial use",
}


class BackgroundError(PipelineError):
    """Something went wrong finding or saving a background."""


# --- where it lives ---------------------------------------------------

def _dir(channel_key: str) -> Path:
    return safe_join(CHANNELS_DIR, channel_key)


def original_path(channel_key: str) -> Path:
    """The picture as downloaded, before blur and dim.

    Kept so the sliders can be moved again without going back to the
    internet — and so a channel is never one bad blur away from having to
    choose a picture all over again.
    """
    return _dir(channel_key) / "background_original.jpg"


def path(channel_key: str) -> Path:
    """The edited picture, which is what the renderer reads."""
    return _dir(channel_key) / "background.jpg"


def meta_path(channel_key: str) -> Path:
    return _dir(channel_key) / "background.json"


def has_background(channel_key: str) -> bool:
    try:
        return path(channel_key).exists()
    except PipelineError:
        return False


def info(channel_key: str) -> dict:
    """Source, licence and current edits, or an empty dict."""
    target = meta_path(channel_key)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def clear(channel_key: str) -> None:
    for target in (path(channel_key), original_path(channel_key),
                   meta_path(channel_key)):
        target.unlink(missing_ok=True)


# --- finding one ------------------------------------------------------

def search(query: str, per_site: int = RESULTS_PER_SITE) -> list:
    """Candidate pictures from both sites, as preview URLs.

    One site being unreachable or unconfigured returns what the other
    found rather than nothing: choosing a background should not depend on
    having both keys.
    """
    results = []
    for finder in (_search_pexels, _search_pixabay):
        try:
            results.extend(finder(query, per_site))
        except Exception as exc:  # noqa: BLE001 - the other site may still work
            log.warning(f"Background search failed ({finder.__name__}): {exc}")
    return results


def _search_pexels(query: str, count: int) -> list:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    response = requests.get(
        PEXELS_PHOTO_URL,
        headers={"Authorization": key},
        # Portrait, because these fill a 9:16 frame. Landscape sources
        # would have to be cropped to a strip of their own middle.
        params={"query": query, "per_page": count, "orientation": "portrait"},
        timeout=SEARCH_TIMEOUT,
    )
    if not response.ok:
        raise ExternalServiceError("Pexels", f"HTTP {response.status_code}",
                                   status=response.status_code)
    return [
        {"source": "pexels",
         "preview": photo["src"]["medium"],
         "full": photo["src"]["portrait"],
         "credit": photo.get("photographer", ""),
         "link": photo.get("url", "")}
        for photo in response.json().get("photos", [])
        if photo.get("src", {}).get("portrait")
    ]


def _search_pixabay(query: str, count: int) -> list:
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    response = requests.get(
        PIXABAY_PHOTO_URL,
        params={"key": key, "q": query, "per_page": max(count, 3),
                "orientation": "vertical", "image_type": "photo",
                "safesearch": "true"},
        timeout=SEARCH_TIMEOUT,
    )
    if not response.ok:
        raise ExternalServiceError("Pixabay", f"HTTP {response.status_code}",
                                   status=response.status_code)
    return [
        {"source": "pixabay",
         "preview": hit.get("webformatURL", ""),
         "full": hit.get("largeImageURL") or hit.get("webformatURL", ""),
         "credit": hit.get("user", ""),
         "link": hit.get("pageURL", "")}
        for hit in response.json().get("hits", [])[:count]
        if hit.get("webformatURL")
    ]


def any_key_configured() -> bool:
    return bool(os.environ.get("PEXELS_API_KEY") or os.environ.get("PIXABAY_API_KEY"))


# --- saving and editing -----------------------------------------------

def choose(channel_key: str, url: str, source: str, credit: str = "",
           link: str = "", blur: int = 0, dim: int = 0) -> dict:
    """Download a picture, crop it to frame, apply the edits, keep both."""
    if not url.startswith(("http://", "https://")):
        raise BackgroundError(f"refusing to fetch {url!r}",
                              user_message="That doesn't look like an image address.")

    try:
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ExternalServiceError(
            source or "the image site", str(exc),
            user_message="Couldn't download that picture. Try another one.")

    directory = _dir(channel_key)
    directory.mkdir(parents=True, exist_ok=True)
    original_path(channel_key).write_bytes(response.content)

    metadata = {
        "source": source,
        "credit": credit,
        "link": link,
        "license": LICENCES.get(source, "Unconfirmed - check before monetizing"),
        "blur": 0,
        "dim": 0,
    }
    meta_path(channel_key).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return apply_edits(channel_key, blur=blur, dim=dim)


def apply_edits(channel_key: str, blur: int = 0, dim: int = 0) -> dict:
    """Re-derive the edited picture from the original, and save it.

    Always from the original, never from the last edited version —
    otherwise moving a slider back would not undo anything, because blur
    applied twice is not the same as more blur applied once.
    """
    source = original_path(channel_key)
    if not source.exists():
        raise BackgroundError(f"{channel_key} has no background to edit",
                              user_message="This channel has no background picture yet.")

    from PIL import Image

    blur = max(0, min(MAX_BLUR, int(blur)))
    dim = max(0, min(MAX_DIM, int(dim)))

    with Image.open(source) as image:
        image = _render_edited(image.convert("RGB"), blur, dim)
        image.save(path(channel_key), quality=88)

    metadata = info(channel_key)
    metadata.update({"blur": blur, "dim": dim})
    meta_path(channel_key).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def _render_edited(image, blur: int, dim: int):
    """Frame-fill, blur, dim — the one transform `apply_edits` and
    `preview_image` both need, so the preview can never drift from what
    Apply would actually save."""
    from PIL import ImageFilter

    image = _fill_frame(image)
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    if dim:
        from PIL import Image as PILImage
        black = PILImage.new("RGB", image.size, (0, 0, 0))
        image = PILImage.blend(image, black, dim / 100)
    return image


def preview_image(channel_key: str, blur: int = 0, dim: int = 0):
    """The background as moving the sliders to `blur`/`dim` would render
    it, without writing anything to disk.

    Read from the original every time, exactly like `apply_edits` —
    otherwise a live preview while dragging would show blur compounding
    on top of whatever was last applied, rather than the same "from
    scratch" result Apply itself would produce. Returns None when there
    is no picture to preview, the same "fall back to the flat colour"
    signal `card_background` already reads from a missing file.
    """
    from PIL import Image

    source = original_path(channel_key)
    if not source.exists():
        return None

    blur = max(0, min(MAX_BLUR, int(blur)))
    dim = max(0, min(MAX_DIM, int(dim)))
    with Image.open(source) as image:
        return _render_edited(image.convert("RGB"), blur, dim)


def _fill_frame(image):
    """Cover a 1080x1920 frame, cropping the overflow from the centre.

    Cover rather than fit: a letterboxed background is worse than a
    cropped one, and the centre is where a photograph's subject almost
    always is.
    """
    from PIL import Image

    scale = max(FRAME_WIDTH / image.width, FRAME_HEIGHT / image.height)
    resized = image.resize((max(1, round(image.width * scale)),
                            max(1, round(image.height * scale))), Image.LANCZOS)
    left = (resized.width - FRAME_WIDTH) // 2
    top = (resized.height - FRAME_HEIGHT) // 2
    return resized.crop((left, top, left + FRAME_WIDTH, top + FRAME_HEIGHT))
