"""
Which typefaces a channel can use for its captions.

Font choice was previously not a setting at all: the renderer tried three
hardcoded paths and took whichever existed. That made every channel look
identical in the one place a viewer actually reads.

A caption font has to do a specific job — heavy enough to hold a stroke
outline, legible at a glance over moving footage, and present on the
machine doing the rendering. So this offers a curated list of faces that
meet that bar and are near-universal on their platform, resolved to real
files at startup, rather than a dropdown of all 514 fonts installed here
(most of which are symbol sets, light weights, or scripts that fall apart
under a 4px stroke).

`available()` only ever returns faces whose file exists, so a channel
configured on one machine degrades to the default on another rather than
failing to render.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Face:
    key: str
    label: str
    note: str
    # Candidate filenames, best first. Several because the same face ships
    # under different names across Windows versions and Linux distros.
    filenames: tuple


# Ordered by how well they suit burned-in short-form captions: heavy
# grotesques first, then humanist sans, then the two serifs and the
# novelty face for channels that want them.
FACES = (
    Face("arial_bold", "Arial Bold", "The default. Neutral and dependable.",
         ("arialbd.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf")),
    Face("impact", "Impact", "Very heavy and condensed. Fits more words per line.",
         ("impact.ttf", "Anton-Regular.ttf")),
    Face("segoe_black", "Segoe UI Black", "Heaviest of the modern sans faces.",
         ("seguibl.ttf",)),
    Face("segoe_bold", "Segoe UI Bold", "Modern and clean, lighter than Black.",
         ("segoeuib.ttf",)),
    Face("bahnschrift", "Bahnschrift", "Condensed and technical.",
         ("bahnschrift.ttf",)),
    Face("verdana_bold", "Verdana Bold", "Wide and very legible at small sizes.",
         ("verdanab.ttf", "DejaVuSans-Bold.ttf")),
    Face("tahoma_bold", "Tahoma Bold", "Tighter than Verdana, same clarity.",
         ("tahomabd.ttf",)),
    Face("trebuchet_bold", "Trebuchet Bold", "Friendly, slightly rounded.",
         ("trebucbd.ttf",)),
    Face("franklin_gothic", "Franklin Gothic Demi", "Newsprint weight and character.",
         ("framd.ttf",)),
    Face("rockwell_bold", "Rockwell Bold", "Slab serif. Solid and grounded.",
         ("rockb.ttf",)),
    Face("georgia_bold", "Georgia Bold", "Serif. Warmer and more traditional.",
         ("georgiab.ttf", "DejaVuSerif-Bold.ttf")),
    Face("cambria_bold", "Cambria Bold", "Serif with sturdier strokes than Georgia.",
         ("cambriab.ttf",)),
    Face("comic_bold", "Comic Sans MS Bold", "Informal. Suits light-hearted formats.",
         ("comicbd.ttf",)),
)

FACES_BY_KEY = {face.key: face for face in FACES}
DEFAULT_FACE = "arial_bold"

# Where fonts live, by platform. Every directory is searched; missing ones
# are skipped, so one list covers all three.
FONT_DIRECTORIES = (
    Path(r"C:\Windows\Fonts"),
    Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
)


@lru_cache(maxsize=1)
def _installed() -> dict:
    """{lowercased filename: full path} for every font on this machine.

    Cached for the process: scanning a few font directories is cheap but
    not free, and the answer cannot change while the app is running in
    any way worth reacting to.
    """
    found = {}
    for directory in FONT_DIRECTORIES:
        if not directory.exists():
            continue
        try:
            for path in directory.rglob("*.tt[fc]"):
                found.setdefault(path.name.lower(), path)
        except OSError:
            continue
    return found


def resolve(face_key: str) -> Path:
    """The font file for a face, or None if none of its candidates exist.

    Falls back through the face's own alternatives first — the same
    typeface often ships under a different filename on Linux — before
    giving up.
    """
    face = FACES_BY_KEY.get(face_key or "")
    if face is None:
        return None
    installed = _installed()
    for filename in face.filenames:
        path = installed.get(filename.lower())
        if path is not None:
            return path
    return None


def available() -> list:
    """Every face that can actually be rendered on this machine."""
    return [face for face in FACES if resolve(face.key) is not None]


def resolve_or_default(face_key: str) -> Path:
    """The requested face, the default, or None to mean "whatever Pillow
    has built in".

    A channel configured on a machine with Impact and rendered on one
    without must still produce a video.
    """
    return resolve(face_key) or resolve(DEFAULT_FACE)


def label_for(face_key: str) -> str:
    face = FACES_BY_KEY.get(face_key or "")
    return face.label if face else "Default"
