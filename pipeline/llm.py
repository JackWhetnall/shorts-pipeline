"""
The one place this project talks to Claude.

Three things this layer owes its callers, and the third is the one that
broke a real run:

**Prompt caching, where it can actually hit.** `call_json` takes the
system prompt as ordered blocks and marks the stable prefix cacheable, so
a genuine repeat reads at a tenth of the input price. A write costs 25%
more than an uncached read, so a block should only be marked cacheable if
the same bytes really will be sent again within a few minutes. The footage
matcher's candidate block was marked, and never repeated — see decision
027. `_log_cache_effect` reports writes and reads per call.

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

**Half price where nobody is waiting.** Inside `with batched():` every
call goes through the Message Batches API instead, which bills every
token at half the rate in exchange for an answer that takes minutes
rather than seconds. Everything above still applies: a batch result is
the same Message, so it is checked, retried and costed the same way.
The hourly background run (pipeline.facts.keep) is the one place that
uses it: it was most of the bill and nothing waits on it. See decision
063.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from anthropic import Anthropic, NotFoundError

from core import costs
from core.errors import ExternalServiceError, MissingCredentialError, PipelineError
from core.logging_setup import get_logger
from core.paths import LLM_BATCH_JOURNAL_PATH

log = get_logger(__name__)

# One tier for every call this project makes. These are constrained tasks
# with a schema - structured extraction and scoring - not open-ended
# reasoning. Named here rather than at each call site so changing tier is
# one edit. FAST_MODEL is for the cheap, high-volume judgements.
DEFAULT_MODEL = "claude-sonnet-5-5"
VISION_MODEL = "claude-sonnet-5-5"
FAST_MODEL = "claude-haiku-5-5"

# Decision 121. The frozen channels (decision 075) keep the models they
# were made with: their work is sent to these instead, so they make
# exactly what they made. By channel key while their work is being done
# (job_context), and around their own pipelines (`legacy_models`).
# A renamed frozen channel would lose this: rename it here too.
LEGACY = {"claude-sonnet-5-5": "claude-sonnet-5", "claude-haiku-5-5": "claude-haiku-4-5"}
LEGACY_CHANNELS = ("minute_pastor", "pub_quiz_buzz")

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

# The SDK refuses a non-streaming call above this (it estimates worst-case
# duration from max_tokens alone and requires streaming past ten minutes'
# worth) — see anthropic._base_client.Anthropic._calculate_nonstreaming_
# timeout. Nothing here streams, so every budget — the caller's own and
# the truncation retry's 3x multiple of it — is clamped under it rather
# than ever finding out the hard way.
MAX_NONSTREAMING_TOKENS = 20_000

# Batch mode. Most batches end within minutes; the API's own limit is a
# day, after which a request expires unanswered. Polled gently: a check
# is free, but there's no hurry.
BATCH_POLL_FIRST = 10          # seconds
BATCH_POLL_MAX = 120
BATCH_WAIT_MAX = 25 * 3600
# Results stay collectable for 29 days; a journal entry older than that
# points at nothing.
BATCH_JOURNAL_DAYS = 28
# Independent calls run side by side in batch mode (run_together), so a
# run waits for one batch round rather than one per call.
TOGETHER_MAX = 8

_client = None
# None outside batch mode; inside it, the `unless` check batched() was given.
_batch_mode = contextvars.ContextVar("llm_batch_mode", default=None)
_legacy = contextvars.ContextVar("llm_legacy_models", default=None)


@contextmanager
def legacy_models(on: bool = True):
    """Calls made inside go to the models the frozen channels were made
    with (LEGACY, decision 121), or, `on=False`, to the newer ones whatever
    channel the job is for."""
    token = _legacy.set(bool(on))
    try:
        yield
    finally:
        _legacy.reset(token)


def for_channel(channel_key: str):
    """`legacy_models` for a frozen channel's work, a no-op for others."""
    return legacy_models(channel_key in LEGACY_CHANNELS)


def _on_legacy() -> bool:
    from core import job_context
    chosen = _legacy.get()
    return job_context.get_channel_key() in LEGACY_CHANNELS if chosen is None else chosen


def _pin(request: dict) -> dict:
    """The request as it should be sent. A Haiku 5.5 call that sets no
    effort runs at "low": it thinks by default where Haiku 4.5 didn't, and
    these calls were written for a model that answered at once. On a frozen
    channel's work, the model it was made with, and no effort for Haiku 4.5,
    which refuses one."""
    model = request.get("model")
    if _on_legacy() and model in LEGACY:
        request = {**request, "model": LEGACY[model]}
        if request["model"] == "claude-haiku-4-5" and "output_config" in request:
            config = {k: v for k, v in request["output_config"].items() if k != "effort"}
            request = {k: v for k, v in request.items() if k != "output_config"}
            if config:
                request["output_config"] = config
        return request
    if model == FAST_MODEL:
        # Its budgets were sized for Haiku 4.5's answer alone: room for the
        # thinking too, and for a tokenizer that counts ~30% more. Only
        # what's used is billed.
        request = {**request, "max_tokens": round(request["max_tokens"] * 1.3) + 1500}
        if not (request.get("output_config") or {}).get("effort"):
            request["output_config"] = {**(request.get("output_config") or {}), "effort": "low"}
    return request


_journal_lock = threading.Lock()
# The system prompt's length for the call being built: a message prefix is
# worth caching when the two together pass the minimum.
_system_chars = contextvars.ContextVar("llm_system_chars", default="")


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
        rendered[last_cacheable]["cache_control"] = _cache_control()
    return rendered


def _cache_control() -> dict:
    """A cache breakpoint. Calls in batch mode are minutes apart, past the
    default five-minute life, so a prefix written there would expire
    before anything read it (decision 095): they ask for an hour, which
    costs 2x input to write instead of 1.25x and pays back on the first
    read."""
    return {"type": "ephemeral", "ttl": "1h"} if in_batch_mode() else {"type": "ephemeral"}


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
    from core import film_budget
    film_budget.check_current()         # a film past its ceiling stops here (decision 094)
    batch = in_batch_mode()
    try:
        response = _send_batched(request, operation) if batch else client().messages.create(**request)
    except Exception as exc:
        raise _as_service_error(exc) from exc

    record = costs.record_claude(operation, model, response.usage, batch=batch)
    _log_cache_effect(operation, response.usage, record)
    return response


# --- batch mode ---------------------------------------------------------

@contextmanager
def batched(unless=None):
    """Send every call made inside this block (on this thread, and on
    threads run_together starts from it) through the Message Batches API
    at half price. Each call blocks until its batch ends, so only use it
    where nobody is waiting on the answer.

    `unless`: checked before each call; while it returns True the call
    goes direct instead. A video made ahead uses it to stop taking its
    time once someone's own video is queued behind it."""
    token = _batch_mode.set(unless or (lambda: False))
    try:
        yield
    finally:
        _batch_mode.reset(token)


def in_batch_mode() -> bool:
    unless = _batch_mode.get()
    return unless is not None and not unless()


def run_together(calls: list) -> list:
    """Run independent zero-argument calls and return their results in
    order. Outside batch mode they simply run one after another; inside
    it they wait out their batches side by side, so four fact-check
    chunks take one batch round rather than four. The first exception
    raised is re-raised once all have finished."""
    if len(calls) <= 1 or not in_batch_mode():
        return [call() for call in calls]
    with ThreadPoolExecutor(max_workers=min(TOGETHER_MAX, len(calls)),
                            thread_name_prefix="llm-batch") as pool:
        # Each in a copy of this context: batch mode, and the job and
        # channel the costs are filed under, carry across.
        futures = [pool.submit(contextvars.copy_context().run, call) for call in calls]
        return [f.result() for f in futures]


def _request_key(request: dict) -> str:
    """A request's identity: the same bytes, the same key. Also its
    custom_id, which allows 64 characters of [A-Za-z0-9_-]."""
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str)
                          .encode("utf-8")).hexdigest()


def _read_journal() -> dict:
    try:
        return json.loads(LLM_BATCH_JOURNAL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _journal(key: str, batch_id: str = None, operation: str = "") -> None:
    """Record (or with no batch_id, forget) the batch a request went into.

    Checkpointing, so best-effort by contract like the cost log: a journal
    that can't be written costs at most a repeat of one call if the app
    stops mid-wait, and must never fail a call that otherwise worked."""
    try:
        with _journal_lock:
            entries = _read_journal()
            cutoff = time.time() - BATCH_JOURNAL_DAYS * 86400
            entries = {k: v for k, v in entries.items() if v.get("at", 0) >= cutoff}
            if batch_id:
                entries[key] = {"batch": batch_id, "at": time.time(), "operation": operation}
            else:
                entries.pop(key, None)
            LLM_BATCH_JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            LLM_BATCH_JOURNAL_PATH.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - checkpointing; see above
        log.warning(f"  [llm] couldn't update the batch journal ({exc})")


def _send_batched(request: dict, operation: str):
    """One request as a one-request batch: submitted, waited for, and its
    Message returned exactly as messages.create would have returned it.

    A request already submitted by a run that stopped before collecting
    it (the same bytes, so the same key) is picked up rather than paid
    for again."""
    key = _request_key(request)
    known = _read_journal().get(key)
    batch_id = known.get("batch") if known else None
    if batch_id:
        log.info(f"  [llm] {operation}: picking up batch {batch_id} from an earlier run")
        try:
            _wait_for(batch_id, operation)
        except NotFoundError:
            log.warning(f"  [llm] {operation}: batch {batch_id} no longer exists; sending again")
            _journal(key)
            batch_id = None
    if not batch_id:
        batch_id = client().messages.batches.create(
            requests=[{"custom_id": key, "params": request}]).id
        _journal(key, batch_id, operation)
        log.info(f"  [llm] {operation}: sent as batch {batch_id} at half price; waiting for it")
        _wait_for(batch_id, operation)

    result = None
    for item in client().messages.batches.results(batch_id):
        if item.custom_id == key:
            result = item.result
            break
    _journal(key)
    return _batch_message(result, operation, batch_id)


def _wait_for(batch_id: str, operation: str) -> None:
    from core import job_context
    with job_context.waiting_on_batch():
        _wait_until_ended(batch_id, operation)


def _wait_until_ended(batch_id: str, operation: str) -> None:
    started = time.time()
    pause = BATCH_POLL_FIRST
    while True:
        batch = client().messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return
        if time.time() - started > BATCH_WAIT_MAX:
            raise ExternalServiceError(
                "The AI service (Claude)", f"{operation}: batch {batch_id} hadn't ended after "
                f"{BATCH_WAIT_MAX // 3600} hours",
                user_message="The AI service didn't answer a background request within a day.")
        time.sleep(pause)
        pause = min(pause * 2, BATCH_POLL_MAX)


def _batch_message(result, operation: str, batch_id: str):
    """The Message inside a batch result, or the error messages.create
    would have raised for it."""
    kind = getattr(result, "type", None)
    if kind == "succeeded":
        return result.message
    if kind == "errored":
        error = getattr(getattr(result, "error", None), "error", None)
        error_type = getattr(error, "type", "") or ""
        detail = (f"{operation}: batch {batch_id} request errored "
                  f"({error_type}: {getattr(error, 'message', '')})")
        if error_type == "invalid_request_error":
            raise ExternalServiceError(
                "The AI service (Claude)", detail, status=400,
                user_message=("The AI service rejected the request as malformed. That's a bug in "
                              "the pipeline rather than anything you did - the details are in the log."))
        raise ExternalServiceError(
            "The AI service (Claude)", detail, status=500,
            user_message=("The AI service had a problem with a background request. The next "
                          "hourly run tries again."))
    raise ExternalServiceError(
        "The AI service (Claude)",
        f"{operation}: batch {batch_id} came back {kind or 'without this request'}",
        user_message=("A background request to the AI service expired before it was answered. "
                      "The next hourly run tries again."))


def call_json(system, user_msg: str, schema: dict, *, operation: str,
              model: str = DEFAULT_MODEL, max_tokens: int = DEFAULT_MAX_TOKENS,
              effort: str = DEFAULT_EFFORT, images: list = None, cache_prefix: str = None) -> dict:
    """Ask Claude for JSON matching `schema` and return it parsed.

    `system` is either a plain string or a list of SystemBlock, stable
    parts first. `operation` labels the call in the cost log, which is
    what makes a per-video cost breakdown readable.

    Raises TruncatedResponse if the model runs out of budget twice, so a
    caller that can carry on without this answer is able to.

    `schema=None` asks for JSON without constraining it, for shapes too
    rich for structured outputs (which allow at most 24 optional fields
    per schema). The caller must then validate what comes back; the scene
    writer does, field by field.

    `images`: pictures to look at, before the text, as (media_type,
    base64) pairs or ("text", caption) pairs to label the one after.

    `cache_prefix`: the start of the message that other calls repeat word
    for word (an outline sent with every chapter, the quiz rounds sent
    with every batch of questions), cached after the system prompt
    (decision 095). The model reads prefix + user_msg as before.
    """
    budget = min(max_tokens, MAX_NONSTREAMING_TOKENS)
    last_error = None

    for attempt in range(MAX_ATTEMPTS):
        is_last = attempt == MAX_ATTEMPTS - 1
        _system_chars.set(system if isinstance(system, str) else "".join(b.text for b in system))
        request = {
            "model": model,
            "max_tokens": budget,
            "system": _render_system(system),
            "messages": [{"role": "user", "content": _content(user_msg, images, cache_prefix)}],
            "output_config": ({"format": {"type": "json_schema", "schema": schema}}
                              if schema is not None else {}),
        }
        if effort:
            request["output_config"]["effort"] = effort
        if not request["output_config"]:
            del request["output_config"]
        request = _pin(request)

        response = _call(request, operation, request["model"])

        try:
            _check_stop_reason(response, operation, budget)
        except TruncatedResponse as exc:
            last_error = exc
            if is_last:
                raise
            budget = min(budget * TRUNCATION_RETRY_MULTIPLIER, MAX_NONSTREAMING_TOKENS)
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
            budget = min(budget * TRUNCATION_RETRY_MULTIPLIER, MAX_NONSTREAMING_TOKENS)
            log.warning(f"  [llm] {operation}: empty response, retrying with room "
                        f"for {budget:,} tokens...")
            continue

        try:
            return json.loads(text if schema is not None else _json_part(text))
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


def _content(text: str, images: list = None, prefix: str = None):
    if not images and not prefix:
        return text
    content = []
    if prefix:
        block = {"type": "text", "text": prefix}
        if len(prefix) >= MIN_CACHEABLE_CHARS or len(_system_chars.get() or "") + len(prefix) >= MIN_CACHEABLE_CHARS:
            block["cache_control"] = _cache_control()
        content.append(block)
    for media_type, data in images or ():
        if media_type == "text":
            content.append({"type": "text", "text": data})
        else:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": data}})
    content.append({"type": "text", "text": text})
    return content


def _json_part(text: str) -> str:
    """The JSON object in an unconstrained answer: without a code fence
    or any sentence around it."""
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


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

    request = _pin({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": DEFAULT_EFFORT},
    })
    response = _call(request, operation, request["model"])
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
    if status == 400 and "credit balance is too low" in str(exc).lower():
        # Billing, not a bug: the account has no credit. It was reported as
        # a malformed request, and adding credits seemed not to help.
        return ExternalServiceError(
            "The AI service (Claude)", str(exc), status=status,
            user_message=("The Anthropic account has run out of credit. Add credit under Plans & "
                          "Billing at console.anthropic.com, in the same organisation as the API "
                          "key this app uses (the APIs page shows which), wait a minute or two, "
                          "then press Retry."))
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
    # Not an HTTP response at all — the SDK itself refused the request
    # (e.g. a max_tokens large enough that it requires streaming). Still a
    # bug in the pipeline rather than a service outage, but it must not
    # escape as a raw exception with no user_message either.
    return ExternalServiceError(
        "The AI service (Claude)", str(exc),
        user_message=("Something went wrong talking to the AI service. That's "
                      "a bug in the pipeline rather than anything you did - "
                      "the details are in the log."),
    )


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
