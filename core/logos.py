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

POST https://api.openai.com/v1/images/generations, one image per
candidate since decision 099: each candidate is drawn in a different
direction (DIRECTIONS), which one prompt with n=CANDIDATE_COUNT can't do.
The calls run side by side, so a batch takes about as long as one. Plain `requests`, no SDK, matching the ElevenLabs
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

from core import costs
from core import assets
from core.errors import ExternalServiceError, MissingCredentialError, PipelineError
from core.logging_setup import get_logger
from core.paths import channel_logo_dir, write_atomically

log = get_logger(__name__)

OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
OPENAI_EDITS_URL = "https://api.openai.com/v1/images/edits"
OPENAI_MODEL = "gpt-image-1"
IMAGE_SIZE = "1024x1024"

# Decision 099. The prompt used to ask every channel for "shading,
# gradients, and layered detail" in "a full, vivid color palette", centred
# on a plain background, and all five candidates came from that one
# prompt. Every channel's logo came out as the same glossy sticker
# (orange on a navy disc, dark vignette), and the five were near-copies of
# each other. Now the prompt sets only the rules a logo has to keep; how
# it looks comes from a different direction for each candidate, drawn
# from DIRECTIONS, each with its own medium and its own way with colour.
PROMPT_TEMPLATE = (
    "A logo mark for a content channel about {topic}. {concept}{direction} "
    "One clear idea, not a collection of symbols: it must read at a glance "
    "as a small round profile picture. Colours chosen for this subject and "
    "this treatment, not a default palette. No text, no letters, no words, "
    "and no social-media app icons, play-button icons, camera icons, or any "
    "other brand or platform symbols. Filling the square, on a flat "
    "background that is part of the design."
)

# Distinct looks, each a medium and a colour approach. A batch takes
# CANDIDATE_COUNT different ones, so the options differ from each other
# and from other channels' logos.
DIRECTIONS = [
    "Flat vector in exactly two colours plus the background: bold solid shapes, no gradients, no "
    "shading, no outlines.",
    "Negative-space mark: one silhouette whose empty space forms a second image, in one colour on a "
    "contrasting ground.",
    "Hand-cut paper collage: a few torn and cut paper shapes with visible paper texture, muted colours.",
    "Monoline icon: a single even-weight line drawing, rounded ends, one line colour on a bold ground.",
    "Vintage woodcut or engraving: fine carved hatching in one dark ink on a warm off-white ground.",
    "Risograph print: two overlapping ink colours with slight misregistration and grain, bright paper.",
    "Bold geometric emblem built from circles, triangles and straight lines only, three flat colours.",
    "Brush-and-ink mark: a few confident expressive brush strokes, one ink colour, lots of space.",
    "Soft clay-like 3D object with matte surfaces and gentle studio light, pastel colours, no gloss.",
    "Mid-century modern illustration: simple stylised shapes, limited retro palette, flat with subtle "
    "texture.",
    "Stained-glass style: bold dark leading between flat panes of a few rich colours.",
    "Pixel-art icon on a 32-pixel grid, crisp square pixels, a small palette.",
]

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


def build_prompt(fragment: str, style_suffix: str = "", direction: str = "", concept: str = "") -> str:
    concept = f"The mark shows {concept.rstrip('.')}. " if concept else ""
    return " ".join(PROMPT_TEMPLATE.format(topic=fragment.strip(), direction=direction,
                                           concept=concept).split()) + style_suffix


def directions(n: int, rng=None, used: list = ()) -> list:
    """n different looks for one batch (decision 099), the ones this
    channel has had least first, so a new batch isn't the last one again."""
    import random
    rng = rng or random
    counts = {d: list(used).count(d) for d in DIRECTIONS}
    pool = sorted(DIRECTIONS, key=lambda d: (counts[d], rng.random()))
    return pool[:min(n, len(DIRECTIONS))]


# Every idea a channel has been shown, kept with its picture: what it
# showed and in which direction, so the next batch can be different.
IDEAS_FILE = "ideas.json"
CONCEPTS_COST = 0.01            # the sketch of new ideas, one low-effort Sonnet call
CONCEPTS_SYSTEM = (
    "You are a brand designer sketching logo ideas for a content channel. Each idea is one "
    "sentence saying what the mark shows: a single clear image or symbol, never a collection of "
    "symbols, and never text or letters. Give ideas that differ from each other in what they "
    "show, not only in how; at least one should be unexpected. Never repeat or closely vary an "
    "idea the channel has already been shown. End each idea with its two or three colours, "
    "different across the ideas and from those already shown (the image model drifts to warm "
    "orange backgrounds when left to choose)."
)


def _ideas(channel_key: str) -> list:
    import json
    try:
        return json.loads((_candidates_dir(channel_key) / IDEAS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_ideas(channel_key: str, ideas: list) -> None:
    import json
    write_atomically(_candidates_dir(channel_key) / IDEAS_FILE, json.dumps(ideas, indent=1))


def concepts(fragment: str, n: int, shown: list) -> list:
    """n new ideas for what the mark shows, unlike those already shown
    (decision 100). Without them every batch drew the brief's most
    obvious picture again: a question mark and a globe, five times over.
    About a cent. A failure falls back to the brief alone, logged."""
    from core.errors import PipelineError
    from pipeline.llm import call_json
    schema = {"type": "object", "properties": {"ideas": {"type": "array", "items": {"type": "string"}}},
              "required": ["ideas"], "additionalProperties": False}
    before = "\n".join(f"- {c}" for c in shown[-40:]) or "(none yet)"
    try:
        data = call_json(CONCEPTS_SYSTEM, f"The channel: {fragment}\n\nIdeas already shown:\n{before}\n\n"
                                          f"Give {n} new ideas.", schema, operation="logo_concepts",
                         max_tokens=3000, effort="low")
    except PipelineError as exc:
        log.warning(f"  [logo] couldn't sketch new ideas ({exc}); drawing from the brief alone")
        return [""] * n
    ideas = [" ".join(str(i).split()) for i in data.get("ideas") or [] if str(i).strip()][:n]
    return ideas + [""] * (n - len(ideas))


def _logo_dir(channel_key: str) -> Path:
    return channel_logo_dir(channel_key)


def _candidates_dir(channel_key: str) -> Path:
    return assets.candidates_dir(channel_key)


def _call_openai_images(prompt: str, n: int, quality: str = "auto") -> list:
    """Returns a list of raw PNG bytes, one per generated image."""
    api_key = _openai_api_key()
    if not api_key:
        raise MissingCredentialError("OPENAI_API_KEY", "logo generation")

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
        if response.status_code == 429:
            raise _RateLimitError(message or "rate limited")
        raise ExternalServiceError(
            "The image service (OpenAI)", f"HTTP {response.status_code}: {message}",
            status=response.status_code,
            user_message=(f"The image service couldn't generate the logo: "
                          f"{message or 'no detail returned'}"))

    data = response.json()
    images = [base64.b64decode(item["b64_json"]) for item in data["data"]]
    costs.record_openai_images("logo_candidates", OPENAI_MODEL, len(images), quality)
    return images


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

    log.info(f"  [logo] hit OpenAI's per-minute image-generation quota - "
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
        raise MissingCredentialError("OPENAI_API_KEY", "logo generation")

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
        if response.status_code == 429:
            raise _RateLimitError(message or "rate limited")
        raise ExternalServiceError(
            "The image service (OpenAI)", f"HTTP {response.status_code}: {message}",
            status=response.status_code,
            user_message=(f"The image service couldn't restyle the logo: "
                          f"{message or 'no detail returned'}"))

    data = response.json()
    costs.record_openai_images("logo_variant", OPENAI_MODEL, 1, quality)
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
        log.info("  [logo] hit OpenAI's per-minute image quota - waiting a minute before retrying...")
        time.sleep(61)
        return _call_openai_image_edit(prompt, image_bytes, quality=quality)


def generate_candidates(channel_key: str, fragment: str, n: int = CANDIDATE_COUNT) -> list:
    """n new candidates at IMAGE_QUALITY_CANDIDATES (cheaper: these are for
    picking a direction, not the final asset). Each shows a new idea in a
    look the channel has had least (decisions 099, 100). Earlier ones are
    all kept: the owner can always go back to one."""
    candidates_dir = _candidates_dir(channel_key)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    ideas = _ideas(channel_key)
    looks = directions(n, used=[i.get("direction") for i in ideas])
    shows = concepts(fragment, len(looks), [i["concept"] for i in ideas if i.get("concept")])

    from concurrent.futures import ThreadPoolExecutor

    def one(pair):
        direction, concept = pair
        return _generate_images(build_prompt(fragment, direction=direction, concept=concept), 1,
                                quality=IMAGE_QUALITY_CANDIDATES)[0]
    with ThreadPoolExecutor(max_workers=min(n, MAX_IMAGES_PER_MINUTE)) as pool:
        images = list(pool.map(one, zip(looks, shows)))

    batch_id = uuid.uuid4().hex[:8]
    paths = []
    for i, (image_bytes, direction, concept) in enumerate(zip(images, looks, shows)):
        path = candidates_dir / f"{batch_id}_{i}.png"
        write_atomically(path, image_bytes)
        paths.append(path)
        ideas.append({"file": path.name, "direction": direction, "concept": concept, "brief": fragment,
                      "at": time.time()})
    _save_ideas(channel_key, ideas)
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
        raise PipelineError("no primary logo",
                            user_message="Pick a primary logo before generating merch versions.")
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


# Re-exported so callers that generate logos and callers that only ask
# whether one exists don't need two different imports. The definitions
# live in core.assets, which knows nothing about the image API.
get_logo_path = assets.logo_path
has_logo = assets.has_logo


def has_merch_variants(channel_key: str) -> bool:
    logo_dir = _logo_dir(channel_key)
    return all((logo_dir / f"variant_{s['key']}.png").exists() for s in VARIANT_STYLES)
