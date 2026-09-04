"""
Distilling structured attributes out of the prose descriptions already in
the library.

A clip's description says everything visible in it — "dark wooden prayer
beads coiled on a polished table, with a closed leather-bound Bible at
the edge of frame and a blurred bedroom behind". Matching a shot brief
against that whole paragraph treats the bedroom and the Bible as equal
evidence to the beads, so a brief about a Bible ranks a clip where a
Bible is a prop.

`subject` fixes that: what the clip is *about*, in a few words, weighted
eight times the prose in the index. `setting`, `motion`, `palette`,
`time_of_day` and `has_people` come along for free in the same call and
pay for themselves in filtering and shot-to-shot variety.

**This reads the existing description rather than looking at the clip
again.** A vision call per clip would mean re-analysing 264 videos; a
text call over descriptions we already paid to generate costs a fraction
of that, and the description is what the matcher reads anyway — so if the
description is wrong, re-describing is the fix, not re-enriching.

Batched because per-clip calls would be mostly overhead: the instructions
are longer than any single description.
"""

from __future__ import annotations

from core.logging_setup import get_logger
from pipeline import llm
from pipeline.footage import store

log = get_logger(__name__)

# Enough clips per call to amortise the instructions, few enough that one
# failure doesn't cost much and the output stays well inside the budget.
BATCH_SIZE = 25

MOTION_VALUES = ("static", "slow", "moderate", "fast")
PALETTE_VALUES = ("warm", "cool", "neutral", "dark", "bright")
TIME_VALUES = ("day", "night", "golden", "indoor", "unknown")

SYSTEM = (
    "You distil short structured attributes out of stock footage descriptions. "
    "You never invent detail that isn't in the description you're given."
)

INSTRUCTIONS = f"""
For each numbered description, return one entry with:

- "index": the number it was given.
- "subject": what the clip is ABOUT, in 2-5 words — the thing a person
  would say the shot is of. Not everything visible: a description
  mentioning beads on a table with a Bible at the edge of frame has the
  subject "prayer beads", not "prayer beads and a Bible in a bedroom".
  Lowercase, no punctuation.
- "setting": where it takes place, 2-4 words ("desert ruins", "modern
  kitchen", "open ocean"). Lowercase. Empty string if the description
  doesn't say.
- "motion": one of {list(MOTION_VALUES)}. How much movement there is —
  camera or subject. A still locked-off shot is "static".
- "palette": one of {list(PALETTE_VALUES)}. The dominant colour feel.
- "time_of_day": one of {list(TIME_VALUES)}. Use "golden" for
  sunrise/sunset light, "indoor" when it's inside and the time isn't
  clear, "unknown" when there's nothing to go on.
- "has_people": true if any person is visible, including silhouettes and
  hands.

Base every field only on what the description actually states. Where it
is silent, use the empty string or "unknown" rather than guessing.
""".strip()

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "subject": {"type": "string"},
                    "setting": {"type": "string"},
                    "motion": {"type": "string", "enum": list(MOTION_VALUES)},
                    "palette": {"type": "string", "enum": list(PALETTE_VALUES)},
                    "time_of_day": {"type": "string", "enum": list(TIME_VALUES)},
                    "has_people": {"type": "boolean"},
                },
                "required": ["index", "subject", "setting", "motion",
                             "palette", "time_of_day", "has_people"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def _clean(value: str, allowed=None, fallback: str = "") -> str:
    value = " ".join((value or "").lower().split()).strip(" .,")
    if allowed and value not in allowed:
        return fallback
    return value


def enrich_batch(clips: list, db_path=None) -> int:
    """Enrich one batch. Returns how many clips were updated."""
    listing = "\n".join(f"{i}. {c.description}" for i, c in enumerate(clips))
    data = llm.call_json(
        [llm.SystemBlock(f"{SYSTEM}\n\n{INSTRUCTIONS}")],
        f"Descriptions:\n{listing}",
        SCHEMA,
        operation="enrich_clips",
        max_tokens=6000,
    )

    by_index = {entry["index"]: entry for entry in data.get("clips", [])}
    updated = 0
    for i, clip in enumerate(clips):
        entry = by_index.get(i)
        if not entry:
            # A missing entry means the model skipped one. Leaving the
            # clip unenriched is correct — it still matches on prose, and
            # a later run picks it up.
            continue
        clip.subject = _clean(entry.get("subject"))
        clip.setting = _clean(entry.get("setting"))
        clip.motion = _clean(entry.get("motion"), MOTION_VALUES, "slow")
        clip.palette = _clean(entry.get("palette"), PALETTE_VALUES, "neutral")
        clip.time_of_day = _clean(entry.get("time_of_day"), TIME_VALUES, "unknown")
        clip.has_people = bool(entry.get("has_people"))
        store.upsert(clip, db_path=db_path)
        updated += 1
    return updated


def enrich_library(only_missing: bool = True, limit: int = None,
                   db_path=None, progress=None) -> dict:
    """Enrich every clip that needs it.

    `progress(done, total)` is called between batches so a CLI or a route
    can report without this module knowing about either.
    """
    clips = store.all_clips(db_path=db_path)
    if only_missing:
        clips = [c for c in clips if not c.enriched]
    if limit:
        clips = clips[:limit]

    if not clips:
        return {"considered": 0, "updated": 0, "batches": 0}

    updated = batches = 0
    for start in range(0, len(clips), BATCH_SIZE):
        batch = clips[start:start + BATCH_SIZE]
        try:
            updated += enrich_batch(batch, db_path=db_path)
        except Exception as exc:  # noqa: BLE001 - one bad batch shouldn't lose the rest
            log.warning(f"  [enrich] batch of {len(batch)} failed ({exc}); continuing.")
        batches += 1
        if progress:
            progress(min(start + BATCH_SIZE, len(clips)), len(clips))

    return {"considered": len(clips), "updated": updated, "batches": batches}


def estimate_cost(only_missing: bool = True, db_path=None) -> dict:
    """What enriching would cost, before spending anything.

    Charging someone real money without telling them first is the kind of
    thing this project has already been bitten by, so every command that
    spends says what it will spend.
    """
    from core.costs import CLAUDE_PRICES

    clips = store.all_clips(db_path=db_path)
    if only_missing:
        clips = [c for c in clips if not c.enriched]
    if not clips:
        return {"clips": 0, "batches": 0, "usd": 0.0}

    batches = (len(clips) + BATCH_SIZE - 1) // BATCH_SIZE
    # ~4 chars per token, plus the instructions once per batch, plus
    # roughly 45 output tokens per clip.
    prose = sum(len(c.description) for c in clips) / 4
    instructions = len(SYSTEM + INSTRUCTIONS) / 4 * batches
    output = len(clips) * 45

    price = CLAUDE_PRICES.get(llm.DEFAULT_MODEL)
    usd = None
    if price:
        usd = ((prose + instructions) * price.input + output * price.output) / 1_000_000
    return {"clips": len(clips), "batches": batches, "usd": usd}
