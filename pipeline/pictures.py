"""
Pictures for picture rounds: flags, country outlines, famous faces,
landmarks and paintings, from sources that are safe to reuse.

Where each comes from, and why it's safe:

- flags: flagcdn.com's images of national flags. Flags themselves are
  public domain.
- outlines: drawn here from Natural Earth's country shapes (public
  domain), fetched once and cached. Nothing to license; nothing to go
  missing.
- faces and landmarks: the lead image of the subject's English Wikipedia
  article, only when it's a Wikimedia Commons file under a licence that
  allows reuse (public domain, CC0, CC BY, CC BY-SA), credited in the
  description as those licences ask. Wikipedia's non-free images (fair-use
  posters, album covers) are local files, not Commons ones, and are
  refused: "fair use" is a case-by-case defence, not permission, and the
  likeliest route to a copyright claim.
- paintings: the museum collections pipeline.artwork already uses (public
  domain works from the Art Institute of Chicago and the Met).

Every picture is looked at before it's used (check): does it show what
the answer says, with nothing in it that gives the answer away, and is it
fit for a general audience. A question whose picture fails is replaced like one whose answer failed the fact check. Pictures
are cached per subject, so each is fetched and checked once. See
decision 046.
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import math
import re
from pathlib import Path
from urllib.parse import quote, unquote

import requests

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR

log = get_logger(__name__)

KINDS = {
    "flags": "Flags: which country's flag is this?",
    "outlines": "Country outlines: which country has this shape?",
    "faces": "Famous faces: who is this?",
    "landmarks": "Landmarks: name the place",
    "paintings": "Paintings: who painted it, or what is it called?",
}
# Dingbats were tried and removed: a dingbat's meaning is in its exact
# shape, which a model can't reliably design or judge, and there's no
# free library of real ones (decision 046).
FOLDER = CACHE_DIR / "quiz_pictures"
TIMEOUT = 25
HEADERS = {"User-Agent": "ShortsPipeline/1.0 (personal quiz videos; https://example.invalid)"}
MAX_SIDE = 1200
CHECK_MODEL = "claude-haiku-4-5"

FLAG_CODES = "https://flagcdn.com/en/codes.json"
FLAG_IMAGE = "https://flagcdn.com/w1280/{code}.png"
OUTLINES = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
            "ne_50m_admin_0_countries.geojson")
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
REUSABLE = re.compile(r"^(public domain|pd\b|cc0|cc[ -]by(?:[ -]sa)?(?:[ -][\d.]+)?)", re.I)


class PictureError(PipelineError):
    pass


def _get(url: str, **kwargs):
    try:
        response = requests.get(url, timeout=TIMEOUT, headers=HEADERS, **kwargs)
    except requests.RequestException as exc:
        raise PictureError(f"couldn't reach {url}: {exc}",
                           user_message="A picture source couldn't be reached.") from exc
    if response.status_code != 200:
        raise PictureError(f"{url} answered {response.status_code}",
                           user_message="A picture couldn't be fetched.")
    return response


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60] or hashlib.sha1(
        text.encode()).hexdigest()[:12]


def _save_image(data: bytes, path: Path) -> Path:
    """Any image, no bigger than MAX_SIDE, as PNG (flags keep their flat
    colours) or JPEG (photographs)."""
    from PIL import Image
    image = Image.open(io.BytesIO(data))
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".png":
        image.save(path, "PNG", optimize=True)
    else:
        image.convert("RGB").save(path, "JPEG", quality=90)
    return path


# --- the choices a writer may make (flags and outlines) ---------------------------

def _cached_json(url: str, name: str):
    path = FOLDER / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(url).content)
    return json.loads(path.read_text(encoding="utf-8"))


def flag_countries() -> dict:
    """{country name: flagcdn code} for sovereign countries and territories
    (not US states and the like, whose codes have a hyphen)."""
    return {name: code for code, name in _cached_json(FLAG_CODES, "flag_codes.json").items()
            if "-" not in code}


def _shapes() -> dict:
    """{country name: GeoJSON geometry} from Natural Earth."""
    data = _cached_json(OUTLINES, "ne_50m_admin_0_countries.geojson")
    return {f["properties"].get("NAME_EN") or f["properties"]["NAME"]: f["geometry"]
            for f in data["features"] if f.get("geometry")}


def outline_countries() -> list:
    """Countries big and compact enough to recognise by shape: a speck,
    or a scatter of islands, isn't a fair question."""
    out = []
    for name, geometry in _shapes().items():
        rings = _rings(geometry)
        main = max((_area(r) for r in rings), default=0)
        total = sum(_area(r) for r in rings)
        if main >= 0.8 and main >= 0.6 * total:          # square degrees, roughly
            out.append(name)
    return sorted(out)


def choices(kind: str) -> list:
    """What the writer must choose from, for the kinds that have a fixed
    list; [] for the rest."""
    if kind == "flags":
        return sorted(flag_countries())
    if kind == "outlines":
        return outline_countries()
    return []


# --- outlines ----------------------------------------------------------------------

def _rings(geometry: dict) -> list:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    return []


def _area(ring: list) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2


def outline_svg(name: str, fill: str = "#2B2118", size: int = 900) -> str:
    """The country's shape as an SVG, its main land and any islands near
    enough to belong in the picture, in a square `size` wide."""
    geometry = _shapes().get(name)
    if geometry is None:
        raise PictureError(f"no outline for {name}", user_message=f"There's no outline for {name}.")
    rings = _rings(geometry)
    main = max(rings, key=_area)
    mx = sum(p[0] for p in main) / len(main)
    my = sum(p[1] for p in main) / len(main)
    # Leave out far-flung territories (France's in the Caribbean, say).
    reach = max(math.dist((mx, my), p) for p in main) * 2.2
    rings = [r for r in rings if math.dist((mx, my), r[0]) <= reach and (_area(r) > 0.002 or r is main)]
    squash = math.cos(math.radians(my))            # longitude shrinks towards the poles
    points = [(x * squash, -y) for r in rings for x, y in r]
    x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
    y0, y1 = min(p[1] for p in points), max(p[1] for p in points)
    scale = (size * 0.9) / max(x1 - x0, y1 - y0)
    ox = (size - (x1 - x0) * scale) / 2
    oy = (size - (y1 - y0) * scale) / 2
    paths = []
    for r in rings:
        d = " ".join(f"{'M' if i == 0 else 'L'}{(x * squash - x0) * scale + ox:.1f},"
                     f"{(-y - y0) * scale + oy:.1f}" for i, (x, y) in enumerate(r))
        paths.append(f"<path d='{d} Z'/>")
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' "
            f"viewBox='0 0 {size} {size}'><g fill='{fill}' stroke='{fill}' stroke-width='1.5' "
            f"stroke-linejoin='round'>{''.join(paths)}</g></svg>")


# --- faces and landmarks: Wikipedia's lead image, when it's reusable ---------------

WIKIDATA = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"


def _commons_file(url: str) -> str:
    """The Commons file name behind an upload.wikimedia.org URL, or ""
    for a local (non-free) Wikipedia file."""
    url = url.split("?")[0]                 # Wikipedia adds tracking parameters
    if "/wikipedia/commons/" not in url:
        return ""
    parts = url.split("/wikipedia/commons/")[1].split("/")
    name = parts[3] if parts[0] == "thumb" else parts[2]
    return unquote(name)


def _licence(file_name: str) -> dict:
    """The file's licence, author and a 1200-pixel copy's address."""
    data = _get(COMMONS_API, params={
        "action": "query", "titles": f"File:{file_name}", "prop": "imageinfo",
        "iiprop": "extmetadata|url", "iiurlwidth": MAX_SIDE, "format": "json"}).json()
    page = next(iter(data.get("query", {}).get("pages", {}).values()), {})
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}

    def value(key):
        return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", (meta.get(key) or {}).get("value", ""))).split())

    artist = value("Artist")
    artist = re.sub(r"^(.+?)\s*$", r"", artist)[:80]     # "Unknown authorUnknown author"
    return {"licence": value("LicenseShortName"), "artist": artist,
            "image": info.get("thumburl") or info.get("url", "")}


def _candidates(title: str) -> list:
    """Commons files that show the subject, best first: the one Wikidata
    records as its image (always a Commons file, chosen to represent it),
    then the Wikipedia article's own lead image."""
    summary = _get(WIKI_SUMMARY.format(title=quote(title.replace(" ", "_"), safe=""))).json()
    files = []
    qid = summary.get("wikibase_item")
    if qid:
        try:
            entity = _get(WIKIDATA.format(qid=qid)).json()["entities"][qid]
            for claim in entity.get("claims", {}).get("P18", [])[:2]:
                name = claim["mainsnak"].get("datavalue", {}).get("value")
                if name:
                    files.append(name.replace(" ", "_"))
        except (PictureError, KeyError, ValueError):
            pass
    lead = (summary.get("originalimage") or summary.get("thumbnail") or {}).get("source", "")
    if _commons_file(lead):
        files.append(_commons_file(lead))
    return list(dict.fromkeys(files))


def wiki_picture(title: str, kind: str) -> dict:
    """{path, credit} for a picture of a Wikipedia subject, refused unless
    it's a Commons file under a licence that allows reuse."""
    refused = []
    for file_name in _candidates(title):
        if file_name.lower().endswith((".svg", ".webm", ".ogv", ".pdf", ".tif", ".tiff")):
            continue                            # logos, video and documents aren't pictures of it
        licence = _licence(file_name)
        if not REUSABLE.match(licence["licence"]) or not licence["image"]:
            refused.append(licence["licence"] or "no licence")
            continue
        path = _save_image(_get(licence["image"]).content, FOLDER / kind / f"{_slug(title)}.jpg")
        who = licence["artist"] or "Wikimedia Commons"
        return {"path": str(path),
                "credit": f"Picture: {title}, {who} ({licence['licence']}), via Wikimedia Commons"}
    raise PictureError(f"no reusable picture of {title} ({', '.join(refused) or 'none on Commons'})",
                       user_message=f"There's no picture of {title} that's free to reuse.")


# --- fetching one --------------------------------------------------------------------

def fetch(kind: str, subject, style: dict = None) -> dict:
    """{path, credit} for one question's picture, cached by subject."""
    if kind == "flags":
        codes = {k.lower(): v for k, v in flag_countries().items()}
        code = codes.get(str(subject).lower())
        if not code:
            raise PictureError(f"no flag for {subject}", user_message=f"There's no flag for {subject}.")
        path = FOLDER / "flags" / f"{code}.png"
        if not path.exists():
            _save_image(_get(FLAG_IMAGE.format(code=code)).content, path)
        return {"path": str(path), "credit": ""}
    if kind == "outlines":
        fill = (style or {}).get("colors", {}).get("ink", "#2B2118")
        path = FOLDER / "outlines" / f"{_slug(str(subject))}_{fill.lstrip('#')}.svg"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(outline_svg(str(subject), fill), encoding="utf-8")
        return {"path": str(path), "credit": ""}
    if kind in ("faces", "landmarks"):
        path = FOLDER / kind / f"{_slug(str(subject))}.jpg"
        credit_file = path.with_suffix(".credit")
        if path.exists() and credit_file.exists():
            return {"path": str(path), "credit": credit_file.read_text(encoding="utf-8")}
        found = wiki_picture(str(subject), kind)
        credit_file.write_text(found["credit"], encoding="utf-8")
        return found
    if kind == "paintings":
        return _painting(str(subject))
    raise PictureError(f"unknown kind {kind}", user_message="That kind of picture round isn't known.")


def _painting(subject: str) -> dict:
    from pipeline import artwork
    path = FOLDER / "paintings" / f"{_slug(subject)}.jpg"
    credit_file = path.with_suffix(".credit")
    if path.exists() and credit_file.exists():
        return {"path": str(path), "credit": credit_file.read_text(encoding="utf-8")}
    found = artwork.search(subject.replace("—", " ").replace(" by ", " "))
    work = artwork.pick(found, f"The painting {subject}") if found else None
    if work is None:
        raise PictureError(f"no painting found for {subject}",
                           user_message=f"{subject} wasn't found in the museum collections.")
    image = artwork._download(work)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "JPEG", quality=90)
    credit = artwork.credit(work)
    credit_file.write_text(credit, encoding="utf-8")
    return {"path": str(path), "credit": credit}


# --- looking before using ------------------------------------------------------------

FACE_SYSTEM = """
You check the photograph for a "who is this?" question in a quiz video
before it's published. Who it shows is already known from its source; do
not try to identify anyone. Answer strictly.
- shows_it: is it a clear photograph of one person, their face plainly
  visible (not a crowd, not from behind, not tiny in the frame)?
- gives_away: is there writing anywhere that names or points to them: a
  caption, a name, a team or country name, a shirt number, a logo?
- suitable: fit for a general audience, and recognisable at phone size?
""".strip()

CHECK_SYSTEM = """
You check the picture for one question of a quiz video before it's
published. Answer strictly.
- shows_it: does the picture clearly show what the answer says (the right
  flag, person, place, painting, country shape)? Unsure is no.
- gives_away: is there writing, a caption, a label or a sign in the
  picture that names the answer or makes it obvious?
- suitable: fit for a general audience, and recognisable at phone size?
""".strip()

def _jpeg_b64(path: str) -> str:
    from PIL import Image
    if path.endswith(".svg"):
        raise PictureError("svg", user_message="")
    image = Image.open(path).convert("RGB")
    image.thumbnail((768, 768))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def check(kind: str, path: str, question: str, answer: str) -> str:
    """"" if the picture will do, else what's wrong with it. Flags and
    outlines are drawn from data and need no look; a check that can't run
    passes nothing."""
    from pipeline import llm
    if kind in ("flags", "outlines"):
        return ""
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": _jpeg_b64(path)}}]
    try:
        schema = {"type": "object", "properties": {
            "shows_it": {"type": "boolean"}, "gives_away": {"type": "boolean"},
            "suitable": {"type": "boolean"}, "note": {"type": "string"}},
            "required": ["shows_it", "gives_away", "suitable", "note"], "additionalProperties": False}
        system = FACE_SYSTEM if kind == "faces" else CHECK_SYSTEM
        data = llm.call_json(system, content + [{"type": "text", "text":
                             f"Question: {question}\nAnswer: {answer}"}], schema,
                             operation="picture_check", model=CHECK_MODEL, max_tokens=800, effort=None)
    except PipelineError as exc:
        return f"the picture check couldn't run ({exc.user_message})"
    if not data.get("shows_it"):
        what = "one person's face" if kind == "faces" else answer
        return f"doesn't clearly show {what}: {data.get('note', '')}"
    if data.get("gives_away"):
        return f"gives the answer away: {data.get('note', '')}"
    if not data.get("suitable"):
        return f"not suitable: {data.get('note', '')}"
    return ""


def data_uri(path: str) -> str:
    """A picture for embedding in a board page."""
    p = Path(path)
    if p.suffix == ".svg":
        return "data:image/svg+xml;base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    mime = "image/png" if p.suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
