"""
Typeset maths for the compositor's diagrams (decision 054): a line that
mixes words and $...$ maths, drawn by matplotlib's mathtext in Computer
Modern, the typeface of LaTeX, as a transparent PNG in one colour.

matplotlib ships the Computer Modern fonts and needs nothing installed, so
formulas render the same on any machine and offline. Its mathtext covers
what explainers write (fractions, powers and indices, roots, sums and
integrals, Greek, accents, \\left( \\right), \\text-like \\mathrm); what
it can't parse falls back to the same line as plain words, and says so in
the log, rather than failing a video.

Images are cached by what they show, so a formula used again (or a digit
in a matrix) is drawn once.
"""

from __future__ import annotations

import hashlib
import io
import re
import threading
from pathlib import Path

from core.logging_setup import get_logger
from core.paths import CACHE_DIR

log = get_logger(__name__)

CACHE = CACHE_DIR / "mathtext"
DPI = 100
_lock = threading.Lock()          # pyplot's state isn't thread-safe; Figure is, but rc isn't
RC = {"mathtext.fontset": "cm", "font.family": "serif", "font.serif": ["cmr10"],
      "axes.formatter.use_mathtext": True, "text.usetex": False}
MATHY = re.compile(r"[\\^_$]|[a-zA-Z]\s*[=<>+\-*/]\s*|[=<>]")


def is_math(text: str) -> bool:
    return "$" in (text or "")


def as_math(text: str) -> str:
    """A matrix entry, an axis label or a node as maths: plain numbers stay
    as they are, anything else is set in maths mode (x_1, \\rho, 3/5)."""
    text = str(text or "").strip()
    if not text or "$" in text:
        return text
    if re.fullmatch(r"[-+]?\d+(\.\d+)?%?", text):
        return text
    if MATHY.search(text) or len(text) <= 3:
        return f"${text}$"
    return text


def font_path(name: str = "cmr10.ttf") -> Path:
    import matplotlib
    return Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name


def _key(text: str, color: str, size: float, face: str = "") -> str:
    basis = f"{text}|{color}|{size:.1f}" + (f"|{face}" if face else "")
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _rc(face: str) -> dict:
    """Computer Modern, or maths written in a handwritten style's own face
    (a whiteboard's marker, a chalkboard's chalk) when matplotlib can find
    it; symbols it lacks come from Computer Modern."""
    if not face:
        return RC
    from matplotlib import font_manager
    try:
        font_manager.findfont(face, fallback_to_default=False)
    except ValueError:
        return RC
    return {**RC, "mathtext.fontset": "custom", "mathtext.rm": face, "mathtext.it": face,
            "mathtext.bf": face, "mathtext.fallback": "cm", "font.family": [face]}


def _draw(text: str, color: str, size: float, face: str = "") -> bytes:
    import matplotlib
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    with _lock, matplotlib.rc_context(_rc(face)):
        fig = Figure(figsize=(0.1, 0.1), dpi=DPI)
        FigureCanvasAgg(fig)
        # size is the height of a capital in pixels; a point is DPI/72 px
        # and a Computer Modern capital is about 0.68 of the em.
        fig.text(0, 0, text, fontsize=size / 0.68 * 72 / DPI, color=color)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=DPI, transparent=True, bbox_inches="tight",
                    pad_inches=0.06)
        return buf.getvalue()


def _plain(text: str) -> str:
    """What a line says without its maths markup, for when mathtext can't
    parse it."""
    text = text.replace("$", "")
    text = re.sub(r"\\(frac|dfrac)\{([^{}]*)\}\{([^{}]*)\}", r"\2/\3", text)
    text = re.sub(r"\\([a-zA-Z]+)", r"\1", text)
    return text.replace("{", "").replace("}", "").replace("_", "").replace("^", "")


def render(text: str, color: str = "#FFFFFF", size: float = 48, face: str = "") -> tuple:
    """(path, width, height) of `text` typeset as a transparent PNG, with
    capitals about `size` pixels tall, in Computer Modern or in `face`."""
    from PIL import Image

    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{_key(text, color, size, face)}.png"
    if not path.exists():
        try:
            data = _draw(text, color, size, face)
        except (ValueError, RuntimeError) as exc:
            first = (str(exc).splitlines() or ["unparseable"])[0]
            log.warning(f"  [animation] couldn't typeset {text!r} ({first}); set as plain words")
            data = _draw(_plain(text), color, size, face)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    with Image.open(path) as im:
        return path, im.width, im.height


def asset_name(path: Path) -> str:
    return f"math_{Path(path).stem}"
