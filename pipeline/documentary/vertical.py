"""
A film's wide pictures made tall for its teasers (decision 106).

A teaser used to have every picture drawn again, vertically: about
fifteen cents of pictures and checks a film, and a wait on a batch. The
film already has seventy-odd pictures of the same story in the same
look, so a teaser now takes its pictures from the film.

A tall 9:16 slice of a wide picture is about a third of it, which cuts
through whatever isn't in that third. One look at all of a teaser's
pictures (a few thumbnails, about a cent) says, for each, how far across
it the part that matters runs. The picture is cut to the narrowest window
that keeps all of that: a subject that fits a tall slice fills the frame;
a wider one is shown across the middle, as large as it can be, over a
blurred, dimmed copy of the picture, so nothing that matters is cut.
"""

from __future__ import annotations

from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

SIZE = (864, 1536)              # the vertical look's frame
BLUR = 40
BACKDROP_DIM = 0.55

MARGIN = 0.03                   # either side of the subject, as a share of the picture's width

FOCUS = """
These are pictures from a widescreen film, to be cut down to tall 9:16 frames for phone
shorts. A tall slice keeps only about a third of each picture's width.

For each picture, give how far across it the part that matters runs: `left` and `right`,
from 0 (the picture's left edge) to 1 (its right edge). The part that matters is whatever
the picture is about: the person or people, the key object, the place's one feature that
counts, and anything that has to be seen with it for the picture to make sense. Never cut
through a person, a face, an animal or the key object; sky, sea and empty ground at the
sides don't matter.
""".strip()


def focus(paths: list) -> list:
    """[(left, right)] for each picture: the span that must stay in frame.
    A failed look keeps every picture whole (logged): never an awkward cut."""
    from pipeline.animation import keyframes
    from pipeline.llm import call_json
    if not paths:
        return []
    images = []
    for n, path in enumerate(paths):
        images += [("text", f"Picture {n}:"), keyframes.thumbnail(path)]
    schema = {"type": "object", "properties": {"pictures": {"type": "array", "items": {
        "type": "object", "properties": {"picture": {"type": "integer"}, "left": {"type": "number"},
                                         "right": {"type": "number"}},
        "required": ["picture", "left", "right"], "additionalProperties": False}}},
        "required": ["pictures"], "additionalProperties": False}
    try:
        data = call_json(FOCUS, f"{len(paths)} pictures.", schema, operation="teaser_crop",
                         max_tokens=3000, effort="low", images=images)
    except PipelineError as exc:
        log.warning(f"  [teasers] couldn't look where the pictures' subjects are ({exc}); shown whole")
        return [(0.0, 1.0)] * len(paths)
    found = {}
    for r in data.get("pictures") or []:
        if isinstance(r.get("picture"), int):
            a, b = sorted((min(1.0, max(0.0, float(r["left"]))), min(1.0, max(0.0, float(r["right"])))))
            found[r["picture"]] = (a, b)
    return [found.get(n, (0.0, 1.0)) for n in range(len(paths))]


def tall(source: Path, out: Path, left: float, right: float, size: tuple = SIZE) -> Path:
    """The wide picture `source` as a tall frame at `out`: the narrowest
    window that keeps `left`..`right` (with a margin), filling the frame
    when the subject fits a tall slice, else across the middle over a
    blurred, dimmed copy of the picture."""
    from PIL import Image, ImageEnhance, ImageFilter
    image = Image.open(source).convert("RGB")
    width, height = image.size
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    slice_w = round(height * size[0] / size[1])
    span = (min(1.0, right + MARGIN) - max(0.0, left - MARGIN)) * width
    cut = min(width, max(slice_w, round(span)))
    centre = (left + right) / 2 * width
    x0 = min(max(0, round(centre - cut / 2)), width - cut)
    window = image.crop((x0, 0, x0 + cut, height))
    if cut <= slice_w:
        frame = window.resize(size, Image.LANCZOS)
    else:
        scale = max(size[0] / width, size[1] / height)
        cover = image.resize((round(width * scale), round(height * scale)), Image.LANCZOS)
        cx, cy = (cover.width - size[0]) // 2, (cover.height - size[1]) // 2
        frame = cover.crop((cx, cy, cx + size[0], cy + size[1])).filter(ImageFilter.GaussianBlur(BLUR))
        frame = ImageEnhance.Brightness(frame).enhance(BACKDROP_DIM)
        shown = window.resize((size[0], round(height * size[0] / cut)), Image.LANCZOS)
        frame.paste(shown, (0, (size[1] - shown.height) // 2))
    frame.save(out, quality=92)
    return out
