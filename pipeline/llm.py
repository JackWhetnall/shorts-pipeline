"""
The one place this project talks to Claude.

Three things this layer owes its callers, and the third is the one that
broke a real run:

**Prompt caching.** The footage matcher re-sends a stable block of clip
descriptions on every call and on each retry round. `call_json` takes the
system prompt as ordered blocks and marks the stable prefix cacheable, so
repeats read at a tenth of the input price.

**Structured outputs.** `output_config.format` constrains the response to
a schema, so there is no `{...}` block to dig out of prose with a regex
and nothing to re-parse.

**A response that actually arrived.** A schema guarantees the shape of a
*completed* answer; it guarantees nothing if the answer was cut off. On
current models thinking is on by default and is billed from the same
`max_tokens` budget as the output, so a task with a lot to reason about
can spend the entire budget thinking and return a response carrying a
thinking block and no text block at all. That is exactly what happened: a
50-clip, 4-segment scoring call with `max_tokens=3000` came back empty,
`json.loads("")` raised "Expecting value: line 1 column 1", and a video
that had already paid for a script and a voiceover died.

So every call here checks `stop_reason` before trusting `content`, retries
a truncated call once with a much larger budget, and reports what actually
went wrong rather than surfacing a JSON parse error for a response that
was never JSON. Callers that can carry on without an answer are given a
distinct exception type so they can.
"""

from __future__ import annotations

import json
import os
import time

from anthropic import Anthropic

from core import costs
from core.errors import ExternalServiceError, MissingCredentialError, PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

# One tier for every call this project makes. These are constrained tasks
# with a schema - structured extraction and scoring - not open-ended
# reasoning. Named here rather than at each call site so changing tier is
# one edit.
DEFAULT_MODEL = "claude-sonnet-5"
VISION_MODEL = "claude-sonnet-5"

# Thinking is billed out of max_tokens, so every budget here has to cover
# reasoning AND the answer. These are deliberately generous: a large
# ceiling costs nothing (you pay for tokens used, not tokens allowed),
# while one too small is a failed render that has already paid for
# everything upstream of it.
DEFAULT_MAX_TOKENS = 8000
VISION_MAX_TOKENS = 2000

# How hard to think. "low" suits schema-constrained extraction; the
# footage matcher asks for more because scoring fifty clips against four
# segments is a real judgement call. Higher settings cost more and buy
# little on tasks whose output shape is already fixed.
DEFAULT_EFFORT = "low"

# Anthropic won't cache a prefix shorter than roughly a thousand tokens,
# and marking a short block cacheable silently does nothing.
MIN_CACHEABLE_CHARS = 4000

# One retry, with a much larger budget, when a response is truncated. A
# second failure means the budget was not the problem.
TRUNCATION_RETRY_MULTIPLIER = 3
MAX_ATTEMPTS = 2

_client = None


class TruncatedResponse(PipelineError):
    """The model ran out of budget before finishing, or returned nothing.

    Its own type because callers can respond to it usefully - the footage
    matcher degrades to recency-based picks rather than throwing away a
    render - whereas a credentials error or a refusal is not something to
    work around.
    """


class RefusedResponse(PipelineError):
    """The model declined the request. Retrying identical input will
    decline again, so this is never retried."""


def client() -> Anthropic:
    """Lazily constructed so importing this module never requires a key -
    the test suite and every pure-function path import it freely."""
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise MissingCredentialError(
                "ANTHROPIC_API_KEY", "script generation and footage matching")
        _client = Anthropic()
    return _client


class SystemBlock:
    """One piece of the system prompt, and whether it's worth caching.

    Order matters and is the caller's responsibility: caching matches a
    prefix, so every stable block must come before the first volatile
    one. Put a timestamp or a per-request id early and nothing after it
    can ever be cached.
    """

    __slots__ = ("text", "cacheable")

    def __init__(self, text: str, cacheable: bool = False):
        self.text = text
        self.cacheable = cacheable


def _render_system(blocks) -> list:
    """Build the SDK's system parameter, attaching a cache breakpoint
    after the last cacheable block.

    One breakpoint, not one per block: the API allows four, but each
    marks a prefix boundary and everything up to the last one is cached
    anyway. A single breakpoint at the end of the stable region is both
    sufficient and the easiest thing to reason about.
    """
    if isinstance(blocks, str):
        blocks = [SystemBlock(blocks)]

    rendered = [{"type": "text", "text": b.text} for b in blocks]
    last_cacheable = None
    for i, b in enumerate(blocks):
        if b.cacheable and len(b.text) >= MIN_CACHEABLE_CHARS:
            last_cacheable = i
    if last_cacheable is not None:
        rendered[last_cacheable]["cache_control"] = {"type": "ephemeral"}
    return rendered


def _text_of(response) -> str:
    """Every text block, joined.

    Joined rather than "the first one": a response may carry a thinking
    block before its text, and on some shapes the answer arrives split
    across more than one block. Taking only the first silently truncates.
    """
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


def _check_stop_reason(response, operation: str, max_tokens: int) -> None:
    """Raise before anyone tries to parse a response that never finished."""
    stop = getattr(response, "stop_reason", None)

    if stop == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise RefusedResponse(
            f"{operation}: model declined ({category or 'no category given'})",
            user_message=("The AI service declined to answer this request. If the "
                          "quote or topic is something it finds objectionable, "
                          "reroll for a different one."),
        )

    if stop == "max_tokens":
        raise TruncatedResponse(
            f"{operation}: hit the {max_tokens}-token ceiling before finishing",
            user_message=("The AI service ran out of room before finishing its "
                          "answer. Retrying with more room usually works."),
        )


def _call(request: dict, operation: str, model: str):
    try:
        response = client().messages.create(**request)
    except Exception as exc:
        raise _as_service_error(exc) from exc

    record = costs.record_claude(operation, model, response.usage)
    _log_cache_effect(operation, response.usage, record)
    return response


def call_json(system, user_msg: str, schema: dict, *, operation: str,
              model: str = DEFAULT_MODEL, max_tokens: int = DEFAULT_MAX_TOKENS,
              effort: str = DEFAULT_EFFORT) -> dict:
    """Ask Claude for JSON matching `schema` and return it parsed.

    `system` is either a plain string or a list of SystemBlock, stable
    parts first. `operation` labels the call in the cost log, which is
    what makes a per-video cost breakdown readable.

    Raises TruncatedResponse if the model runs out of budget twice, so a
    caller that can carry on without this answer is able to.
    """
    budget = max_tokens
    last_error = None

    for attempt in range(MAX_ATTEMPTS):
        is_last = attempt == MAX_ATTEMPTS - 1
        request = {
            "model": model,
            "max_tokens": budget,
            "system": _render_system(system),
            "messages": [{"role": "user", "content": user_msg}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if effort:
            request["output_config"]["effort"] = effort

        response = _call(request, operation, model)

        try:
            _check_stop_reason(response, operation, budget)
        except TruncatedResponse as exc:
            last_error = exc
            if is_last:
                raise
            budget *= TRUNCATION_RETRY_MULTIPLIER
            log.warning(f"  [llm] {operation}: response was cut short, retrying "
                        f"with room for {budget:,} tokens...")
            continue

        text = _text_of(response)
        if not text:
            # Finished cleanly but said nothing. Same practical outcome as
            # truncation and the same fix, so it takes the same path rather
            # than surfacing as a parse error on an empty string.
            last_error = TruncatedResponse(
                f"{operation}: response contained no text",
                user_message=("The AI service returned an empty answer. "
                              "Retrying usually works."),
            )
            if is_last:
                raise last_error
            budget *= TRUNCATION_RETRY_MULTIPLIER
            log.warning(f"  [llm] {operation}: empty response, retrying with room "
                        f"for {budget:,} tokens...")
            continue

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            # Shouldn't happen with a constrained format, but a silent
            # wrong answer is worse than a clear failure.
            last_error = ExternalServiceError(
                "The AI service (Claude)",
                f"{operation}: schema-constrained response was not valid JSON: {exc}",
                user_message=("The AI service returned a malformed response. "
                              "Retrying usually works."),
            )
            if is_last:
                raise last_error from exc
            log.warning(f"  [llm] {operation}: malformed JSON, retrying...")
            time.sleep(1)

    raise last_error or ExternalServiceError(
        "The AI service (Claude)", f"{operation}: exhausted attempts")


def call_vision(prompt: str, images: list, *, operation: str,
                model: str = VISION_MODEL,
                max_tokens: int = VISION_MAX_TOKENS) -> str:
    """Plain-text answer about a set of images. `images` is a list of
    (media_type, base64_data). Used to describe footage clips.

    The budget looks generous for a 2-4 sentence description because
    thinking is billed from it too. The previous 250 would have been
    consumed entirely by reasoning and returned an empty description,
    which would then have been written into the library - poisoning every
    future match for that clip, silently and permanently.
    """
    content = [
        {"type": "image",
         "source": {"type": "base64", "media_type": media_type, "data": data}}
        for media_type, data in images
    ]
    content.append({"type": "text", "text": prompt})

    response = _call({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": DEFAULT_EFFORT},
    }, operation, model)
    _check_stop_reason(response, operation, max_tokens)

    text = _text_of(response)
    if not text:
        raise TruncatedResponse(
            f"{operation}: no description came back",
            user_message="The AI service returned an empty description for this clip.",
        )
    return " ".join(text.split())


def _as_service_error(exc: Exception) -> Exception:
    """Wrap SDK errors so callers see one exception family. Anything
    already carrying a good message passes through."""
    if isinstance(exc, PipelineError):
        return exc
    status = getattr(exc, "status_code", None)
    if status == 429:
        return ExternalServiceError(
            "The AI service (Claude)", str(exc), status=status,
            user_message=("The AI service is temporarily limiting how fast requests "
                          "can be made. This usually clears within a few minutes - "
                          "retrying should work."),
        )
    if status in (401, 403):
        return ExternalServiceError(
            "The AI service (Claude)", str(exc), status=status,
            user_message=("ANTHROPIC_API_KEY was rejected. Check that it's set "
                          "correctly and still valid."),
        )
    if status == 400:
        # Almost always a request this code built wrongly, so say that
        # rather than implying the user did something.
        return ExternalServiceError(
            "The AI service (Claude)", str(exc), status=status,
            user_message=("The AI service rejected the request as malformed. That's "
                          "a bug in the pipeline rather than anything you did - the "
                          "details are in the log."),
        )
    if status is not None and status >= 500:
        return ExternalServiceError(
            "The AI service (Claude)", str(exc), status=status,
            user_message=("The AI service is having problems on their end. Retrying "
                          "should work once it recovers."),
        )
    return exc


def _log_cache_effect(operation: str, usage, record) -> None:
    """Say out loud when a large prompt was served from cache, and when a
    large one wasn't.

    Caching fails silently - a byte change anywhere in the prefix drops
    the hit rate to zero with no error - so a regression shows up in the
    ordinary run log instead of only in the monthly bill.
    """
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    fresh = getattr(usage, "input_tokens", 0) or 0
    cost = costs.format_usd(record.cost_usd) if record else "-"

    if cached:
        log.info(f"  [llm] {operation}: {cached:,} tokens from cache, "
                 f"{fresh:,} fresh ({cost})")
    elif written:
        log.info(f"  [llm] {operation}: cached {written:,} tokens for reuse ({cost})")
    elif fresh > 10_000:
        log.warning(f"  [llm] {operation}: {fresh:,} uncached input tokens - "
                    f"the cacheable prefix may have changed ({cost})")
