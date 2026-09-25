"""
Public-domain paintings and engravings as a segment's picture.

One of the visual director's media (pipeline.director), offered when a
channel allows it (`artwork.mode` "allowed"): for a segment about
something great art has shown (a battle, a myth, a scene from scripture
or a novel, a historical figure, a painting itself), a real work from a
museum collection, slowly panned, instead of stock footage. It is a real
picture, like footage, so the graphics slider doesn't limit it; it looks
like nothing else in a feed, which matters for the reused-content rules.

Where it comes from: the Art Institute of Chicago's and the Met's open
access collections (public-domain works, free APIs, no key). The
director writes a short museum search ("Samson Delilah"); candidates are
found in both, paintings first; a quick look by a vision model picks the
one that actually shows what's being said, or none, and then the
segment keeps its footage. The work is credited in the video's
description. See decisions 038 and 042.
"""

from __future__ import annotations

import base64
import io
import subprocess
from pathlib import Path

import numpy as np
import requests

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import FRAME_HEIGHT as H, FRAME_WIDTH as W

log = get_logger(__name__)

TIMEOUT = 25
MAX_CANDIDATES = 6
PICK_MODEL = "claude-haiku-4-5"
AIC_SEARCH = "https://api.artic.edu/api/v1/artworks/search"
AIC_IMAGE = "https://www.artic.edu/iiif/2/{id}/full/{w},/0/default.jpg"
MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{id}"
# Paintings first; engravings and drawings are often excellent too.
KIND_RANK = {"painting": 0, "print": 1, "drawing": 1, "drawing and watercolor": 1}
FPS = 30
# The Art Institute asks API users to identify themselves, and its image
# server refuses anonymous clients.
HEADERS = {"User-Agent": "ShortsPipeline/1.0 (personal video project)",
           "AIC-User-Agent": "ShortsPipeline/1.0 (personal video project)"}


# --- finding ----------------------------------------------------------------

def _aic(query: str) -> list:
    response = requests.get(AIC_SEARCH, timeout=TIMEOUT, headers=HEADERS, params={
        "q": query, "query[term][is_public_domain]": "true", "limit": 12,
        "fields": "id,title,artist_display,date_display,image_id,artwork_type_title"})
    out = []
    for a in response.json().get("data", []) if response.status_code == 200 else []:
        if not a.get("image_id"):
            continue
        out.append({"title": a.get("title") or "Untitled",
                    "artist": (a.get("artist_display") or "").split("\n")[0],
                    "date": a.get("date_display") or "",
                    "kind": (a.get("artwork_type_title") or "").lower(),
                    "museum": "Art Institute of Chicago",
                    "image": AIC_IMAGE.format(id=a["image_id"], w=843),   # its public maximum
                    "fallback": AIC_IMAGE.format(id=a["image_id"], w=843),
                    "thumb": AIC_IMAGE.format(id=a["image_id"], w=400),
                    "url": f"https://www.artic.edu/artworks/{a['id']}"})
    return out


def _met(query: str) -> list:
    response = requests.get(MET_SEARCH, timeout=TIMEOUT, headers=HEADERS, params={"q": query, "hasImages": "true"})
    ids = (response.json().get("objectIDs") or [])[:10] if response.status_code == 200 else []
    out = []
    for object_id in ids:
        o = requests.get(MET_OBJECT.format(id=object_id), timeout=TIMEOUT, headers=HEADERS).json()
        if not (o.get("isPublicDomain") and o.get("primaryImage")):
            continue
        out.append({"title": o.get("title") or "Untitled", "artist": o.get("artistDisplayName") or "",
                    "date": o.get("objectDate") or "", "kind": (o.get("classification") or "").lower(),
                    "museum": "The Metropolitan Museum of Art", "image": o["primaryImage"],
                    "fallback": o.get("primaryImageSmall") or o["primaryImage"],
                    "thumb": o.get("primaryImageSmall") or o["primaryImage"],
                    "url": o.get("objectURL") or ""})
    return out


def search(query: str) -> list:
    """Public-domain works for `query`, best kinds first. Never raises: an
    unreachable museum just contributes nothing."""
    found = []
    for source in (_aic, _met):
        try:
            found += source(query)
        except (requests.RequestException, ValueError) as exc:
            log.info(f"  [art] {source.__name__[1:]} search failed ({exc})")
    found.sort(key=lambda a: KIND_RANK.get(a["kind"], 2))
    return found[:MAX_CANDIDATES]


def credit(work: dict) -> str:
    who = f", {work['artist']}" if work.get("artist") else ""
    when = f" ({work['date']})" if work.get("date") else ""
    return f"Art: {work['title']}{who}{when}. {work['museum']}, public domain."


# --- choosing ---------------------------------------------------------------

PICK_SYSTEM = """
You pick the artwork to show, slowly panned, while a short vertical video
says a line. Choose the one that most clearly shows what the line is
about (its people, its moment) and would look good filling a phone
screen. Reject fragments, text-only pages, heavily damaged or
unclear images, graphic violence, and ANY nudity or partial nudity, even
in classical art: it limits which ads the video can carry. Answer 0 if
none fits well; a wrong picture is worse than none.
""".strip()


def pick(candidates: list, passage: str) -> dict:
    """The candidate a vision model says shows the passage, or None."""
    from pipeline import llm

    content = [{"type": "text", "text": f"The line: {passage}"}]
    shown = []
    for work in candidates:
        try:
            response = requests.get(work["thumb"], timeout=TIMEOUT, headers=HEADERS)
        except requests.RequestException:
            continue
        # Only a real image: an error page shown as "artwork" once made the
        # vision model reject everything.
        if response.status_code != 200 or not response.headers.get("content-type", "").startswith("image/jpeg"):
            continue
        data = response.content
        shown.append(work)
        content.append({"type": "text", "text": f"Artwork {len(shown)}: {work['title']}, "
                                                f"{work['artist']} ({work['kind'] or 'artwork'})"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(data).decode("ascii")}})
    if not shown:
        return None
    schema = {"type": "object", "properties": {"choice": {"type": "integer"}},
              "required": ["choice"], "additionalProperties": False}
    try:
        choice = llm.call_json(PICK_SYSTEM, content, schema, operation="art_pick",
                               model=PICK_MODEL, max_tokens=800, effort=None).get("choice")
    except PipelineError as exc:
        log.info(f"  [art] couldn't choose ({exc})")
        return None
    return shown[choice - 1] if isinstance(choice, int) and 1 <= choice <= len(shown) else None


# --- showing ----------------------------------------------------------------

def _download(work: dict) -> "Image.Image":
    from PIL import Image
    for url in (work["image"], work["fallback"]):
        try:
            response = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            if response.status_code == 200 and response.headers.get("content-type", "").startswith("image/"):
                image = Image.open(io.BytesIO(response.content)).convert("RGB")
                image.thumbnail((2400, 2400))
                return image
        except (requests.RequestException, OSError):
            continue
    raise PipelineError(f"couldn't download {work['url']}",
                        user_message="A painting couldn't be downloaded.")


def ken_burns(image, seconds: float, out_path: Path) -> Path:
    """A slow zoom (and, for a tall work, a slow drift down it) as a
    1080x1920 clip. A wide work is shown whole over a blurred, darkened
    copy of itself, above the captions' space, rather than cropped to a
    sliver."""
    import imageio_ffmpeg
    from PIL import Image, ImageFilter, ImageEnhance

    frames = max(1, round(seconds * FPS))
    w, h = image.size
    tall = h / w >= 1.25
    if not tall:
        cover = max(W / w, H / h) * 1.1
        back = image.resize((int(w * cover), int(h * cover)), Image.BICUBIC)
        left, top = (back.width - W) // 2, (back.height - H) // 2
        back = back.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(40))
        back = ImageEnhance.Brightness(back).enhance(0.45)
        fit = min((W - 80) / w, 1180 / h)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           str(out_path)]
    encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(frames):
            p = i / max(1, frames - 1)
            ease = p * p * (3 - 2 * p)
            if tall:
                zoom = 1.0 + 0.08 * ease
                cw, ch = W / (max(W / w, H / h) * zoom), H / (max(W / w, H / h) * zoom)
                cx = w / 2
                cy = ch / 2 + (h - ch) * (0.15 + 0.35 * ease)       # drifting down the work
                box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
                frame = image.transform((W, H), Image.EXTENT, box, Image.BICUBIC)
            else:
                scale = fit * (1.0 + 0.06 * ease)
                fw, fh = int(w * scale), int(h * scale)
                frame = back.copy()
                frame.paste(image.resize((fw, fh), Image.BICUBIC), ((W - fw) // 2, 690 - fh // 2))
            encoder.stdin.write(np.asarray(frame, dtype=np.uint8).tobytes())
    finally:
        encoder.stdin.close()
        code = encoder.wait()
    if code != 0:
        raise PipelineError(f"ffmpeg exited {code}", user_message="A painting couldn't be animated.")
    return out_path


# --- the stage --------------------------------------------------------------

def allowed(channel) -> bool:
    """Whether the director may use artwork on this channel. ("passage"
    was this setting's earlier, one-segment form.)"""
    return getattr(getattr(channel, "artwork", None), "mode", "off") in ("allowed", "passage")


def make(query: str, words: str, seconds: float, out_path: Path) -> tuple:
    """(clip, credit) for one segment: the best-fitting work for `query`,
    panned for `seconds`. Raises PipelineError when nothing fits, and the
    segment keeps its footage."""
    candidates = search(query)
    work = pick(candidates, words) if candidates else None
    if work is None:
        raise PipelineError(f"no artwork fits {query!r}",
                            user_message="No painting fitted this segment.")
    ken_burns(_download(work), seconds, out_path)
    return out_path, credit(work)
