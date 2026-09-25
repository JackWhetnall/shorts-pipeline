"""
What each video actually costs to make.

Every run spends ElevenLabs characters, Claude tokens, and sometimes
OpenAI image credits, and until now none of it was recorded anywhere. For
a project whose entire premise is revenue, that's the wrong thing to be
blind about — and it's specifically why the footage matcher was allowed
to grow into ~99% of the Claude bill without anyone noticing. A number
nobody measures is a number nobody manages.

Records go to a JSONL append log (config/cost_log.jsonl): one line per
billable call, appended under a lock, never rewritten. Append-only means
a crash mid-render can lose at most the last line rather than corrupting
the history, and the file stays readable with `tail`.

Prices are per million tokens / per million characters and are declared
here rather than fetched, because a spend log has to keep working
offline. They will drift — `PRICES_CHECKED` says when they were last
confirmed, and a model with no entry records usage with a null cost
instead of guessing.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from core.paths import COST_LOG_PATH

PRICES_CHECKED = "2026-06-24"


@dataclass(frozen=True)
class TokenPrice:
    """USD per million tokens.

    cache_write is ~1.25x input and cache_read ~0.1x input — the whole
    reason prompt caching pays for itself on a prompt that's re-sent
    unchanged, as the footage matcher's library block is.
    """

    input: float
    output: float

    @property
    def cache_write(self) -> float:
        return self.input * 1.25

    @property
    def cache_read(self) -> float:
        return self.input * 0.1


# Anthropic first-party rates.
CLAUDE_PRICES = {
    "claude-opus-5": TokenPrice(5.00, 25.00),
    "claude-sonnet-5": TokenPrice(2.00, 10.00),
    "claude-sonnet-4-6": TokenPrice(3.00, 15.00),
    "claude-haiku-4-5": TokenPrice(1.00, 5.00),
}

# ElevenLabs bills per character of input text; the exact rate depends on
# the subscription tier, so this is the widely-quoted Creator-tier
# effective rate and is a good-enough estimate rather than an invoice.
ELEVENLABS_USD_PER_MILLION_CHARS = 165.0

# gpt-image-1, per generated image at 1024x1024, and at the portrait
# 1024x1536 size (illustrations fill a vertical frame).
OPENAI_IMAGE_PRICES = {"low": 0.011, "medium": 0.042, "high": 0.167, "auto": 0.042}
OPENAI_PORTRAIT_PRICES = {"low": 0.016, "medium": 0.063, "high": 0.25, "auto": 0.063}

_lock = threading.Lock()
_warned_unwritable = False


@dataclass
class CostRecord:
    ts: float
    service: str            # "claude" | "elevenlabs" | "openai-image"
    operation: str          # "script" | "footage_match" | "describe_clip" | ...
    model: str
    cost_usd: float | None  # None when the price for this model isn't known
    job_id: str = None
    channel_key: str = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    characters: int = 0
    images: int = 0


def _write(record: CostRecord) -> None:
    """Append one record. Best-effort by contract: a cost log that can't
    be written must never take down a render that otherwise worked."""
    try:
        COST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(record))
        with _lock:
            with open(COST_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # noqa: BLE001
        # Best-effort by contract, but say so once rather than leaving
        # someone to wonder why the spend report is empty.
        global _warned_unwritable
        if not _warned_unwritable:
            _warned_unwritable = True
            from core.logging_setup import get_logger
            get_logger(__name__).warning("Couldn't write the cost log; spend won't be recorded.")


def record_claude(operation: str, model: str, usage, channel_key: str = None) -> CostRecord:
    """`usage` is the SDK's response.usage. Cached reads and cache writes
    are billed differently from ordinary input, so they're tracked
    separately — otherwise a caching win is invisible in the totals,
    which defeats the point of measuring."""
    from core import job_context

    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

    price = CLAUDE_PRICES.get(model)
    cost = None
    if price is not None:
        cost = (
            input_tokens * price.input
            + output_tokens * price.output
            + cache_read * price.cache_read
            + cache_write * price.cache_write
        ) / 1_000_000

    record = CostRecord(
        ts=time.time(), service="claude", operation=operation, model=model,
        cost_usd=cost, job_id=job_context.get_job_id(),
        channel_key=channel_key or job_context.get_channel_key(),
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_tokens=cache_read, cache_write_tokens=cache_write,
    )
    _write(record)
    return record


def record_elevenlabs(operation: str, model: str, characters: int, channel_key: str = None) -> CostRecord:
    from core import job_context
    record = CostRecord(
        ts=time.time(), service="elevenlabs", operation=operation, model=model,
        cost_usd=characters * ELEVENLABS_USD_PER_MILLION_CHARS / 1_000_000,
        job_id=job_context.get_job_id(),
        channel_key=channel_key or job_context.get_channel_key(), characters=characters,
    )
    _write(record)
    return record


def record_openai_images(operation: str, model: str, count: int, quality: str,
                         channel_key: str = None, portrait: bool = False) -> CostRecord:
    from core import job_context
    prices = OPENAI_PORTRAIT_PRICES if portrait else OPENAI_IMAGE_PRICES
    unit = prices.get(quality, prices["auto"])
    record = CostRecord(
        ts=time.time(), service="openai-image", operation=operation, model=model,
        cost_usd=unit * count, job_id=job_context.get_job_id(),
        channel_key=channel_key or job_context.get_channel_key(), images=count,
    )
    _write(record)
    return record


# --- reading it back --------------------------------------------------

def read_records(path: Path = None) -> list:
    """Every record, oldest first. A malformed line is skipped rather
    than failing the read — a truncated final line from a hard kill
    shouldn't hide the entire history."""
    path = path or COST_LOG_PATH
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _summarize(records: list) -> dict:
    total = sum(r.get("cost_usd") or 0.0 for r in records)
    by_operation = {}
    for r in records:
        key = f"{r['service']}:{r['operation']}"
        by_operation[key] = by_operation.get(key, 0.0) + (r.get("cost_usd") or 0.0)
    return {
        "total_usd": total,
        "calls": len(records),
        "by_operation": dict(sorted(by_operation.items(), key=lambda kv: -kv[1])),
        "cache_read_tokens": sum(r.get("cache_read_tokens", 0) for r in records),
        "input_tokens": sum(r.get("input_tokens", 0) for r in records),
    }


def summary_for_job(job_id: str, path: Path = None) -> dict:
    """What one video cost, broken down by operation. Shown on the
    finished video's page — the whole point is that the expensive step is
    visible at the moment you're looking at what it produced."""
    return _summarize([r for r in read_records(path) if r.get("job_id") == job_id])


def summary_between(start_ts: float, end_ts: float, channel_key: str = None,
                    path: Path = None) -> dict:
    """Spend in a time window, optionally for one channel.

    This is how a single video is costed when there's no job id to key
    on — a plain CLI run has no job, but it does have a start and end
    time and a channel, which is enough to attribute its own calls."""
    return _summarize([
        r for r in read_records(path)
        if start_ts <= r.get("ts", 0) <= end_ts
        and (channel_key is None or r.get("channel_key") == channel_key)
    ])


def summary_for_channel(channel_key: str, path: Path = None) -> dict:
    return _summarize([r for r in read_records(path) if r.get("channel_key") == channel_key])


def summary_all(path: Path = None) -> dict:
    return _summarize(read_records(path))


def format_usd(amount) -> str:
    """Sub-cent amounts are common here (a script call is a fraction of a
    cent), and rounding them to $0.00 makes the log look broken."""
    if amount is None:
        return "—"
    if amount and abs(amount) < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"
