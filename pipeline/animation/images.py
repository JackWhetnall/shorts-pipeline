"""
Pictures with references: keyframes, style frames and cast sheets.

Consistency comes from here. Every keyframe is drawn with the channel's
style frame as a reference, and with the model sheet of every character
and place in it, so a character is the same character in every shot and
every video, and every frame is the same hand (decision 051). OpenAI's
image models take several reference pictures on their edits endpoint and
are billed by the token, which they report, so the cost recorded is the
real one.
"""

from __future__ import annotations

import base64
import io
import os
import re
import threading
import time
from collections import deque
from pathlib import Path

import requests

from core import costs
from core.errors import ExternalServiceError, MissingCredentialError
from core.logging_setup import get_logger
from core.paths import write_atomically
from pipeline.animation.models import ImageModel

log = get_logger(__name__)

GENERATIONS = "https://api.openai.com/v1/images/generations"
EDITS = "https://api.openai.com/v1/images/edits"
FILES = "https://api.openai.com/v1/files"
BATCHES = "https://api.openai.com/v1/batches"
SERVICE = "The image service (OpenAI)"
PORTRAIT = (864, 1536)          # 9:16, both sides multiples of 16
LANDSCAPE = (1536, 1024)        # model sheets: a character three times across
ATTEMPTS = 4
# A rate limit is waited out, not failed on: this many tries.
RATE_LIMITED_ATTEMPTS = 8
# References are sent no larger than this: the model reads a picture's
# style and identity from far fewer pixels, and pays per pixel read.
REFERENCE_SIDE = 1024

# OpenAI limits its image models per minute by the account's usage tier,
# counted in input images. This account's is 5 (29 Sep 2026): drawing the
# looks' examples four at a time lost ten of forty to 429s, and a video's
# keyframes, drawn in parallel with two to four references each, would
# have lost frames the same way. So every call waits its turn here, a
# call with references counting each one, and a 429 that states the limit
# resets it (a higher tier raises it by itself).
per_minute = 5
_sent = deque()                 # (monotonic time, weight)
_turn = threading.Lock()


def _wait_turn(weight: int) -> None:
    weight = max(1, min(weight, per_minute))
    while True:
        with _turn:
            now = time.monotonic()
            while _sent and now - _sent[0][0] >= 60:
                _sent.popleft()
            if not _sent or sum(w for _, w in _sent) + weight <= per_minute:
                _sent.append((now, weight))
                return
            wait = 60.5 - (now - _sent[0][0])
        time.sleep(max(0.5, wait))


def _rate_limited(response) -> float:
    """Seconds to wait after a 429, learning the stated limit on the way."""
    global per_minute
    text = response.text or ""
    limit = re.search(r"Limit (\d+)", text)
    if limit and "per min" in text:
        per_minute = max(1, int(limit.group(1)))
    again = re.search(r"try again in ([\d.]+)\s*(ms|s)", text)
    if again:
        seconds = float(again.group(1)) / (1000 if again.group(2) == "ms" else 1)
    else:
        seconds = float(response.headers.get("retry-after") or 15)
    return min(90.0, seconds + 1.0)


# Batches (decision 094): a storyboard's pictures go as one batch at half
# price, references uploaded once and named by file id. Most end within an
# hour; the API allows a day. Polled gently; a run stopped mid-wait picks
# its batch up again from the journal instead of paying twice.
BATCH_POLL_FIRST, BATCH_POLL_MAX = 30, 300
BATCH_WAIT_MAX = 20 * 3600
_journal_lock = threading.Lock()


def _key() -> str:
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value:
        raise MissingCredentialError("OPENAI_API_KEY", "animation keyframes")
    return value


def _reference_bytes(path: Path) -> bytes:
    from PIL import Image

    image = Image.open(path).convert("RGB")
    image.thumbnail((REFERENCE_SIDE, REFERENCE_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _error(response) -> ExternalServiceError:
    text = response.text[:500]
    status = response.status_code
    lowered = text.lower()
    if "moderation" in lowered or "safety" in lowered:
        message = "OpenAI's safety system refused a picture this video needed."
    elif status == 429 and "rate limit" in lowered:
        message = (f"OpenAI kept this account at its image limit ({per_minute} a minute) for "
                   f"too long. Retrying later works; a higher usage tier raises the limit.")
    elif status in (401, 403):
        message = ("OPENAI_API_KEY was rejected, or this organisation isn't verified for "
                   "the image models. Check platform.openai.com.")
    elif "billing" in lowered or "quota" in lowered:
        message = "The OpenAI account is out of credit. Top it up on its billing page."
    elif status == 404 or "model" in lowered and status == 400:
        message = "This OpenAI key can't use the chosen image model. Pick another in the channel's animation settings."
    else:
        message = "Couldn't draw a picture for the animation. The details are in the log."
    return ExternalServiceError(SERVICE, f"HTTP {status}: {text}", status=status,
                                user_message=message)


def draw(prompt: str, out_path: Path, model: ImageModel, *, references=(),
         size: tuple = PORTRAIT, operation: str = "animation_keyframe",
         quality: str = None, transparent: bool = False) -> Path:
    """One picture from `prompt`, drawn with `references` (paths, in the
    order the prompt names them) when there are any. Saved at out_path;
    the format follows its suffix (.png or .jpg). `transparent` draws a
    cut-out on a transparent background (a kit object; needs .png)."""
    from core import film_budget
    film_budget.check_current()         # a film past its ceiling stops here (decision 094)
    out_path = Path(out_path)
    fmt = "png" if out_path.suffix.lower() == ".png" else "jpeg"
    fields = {"model": model.model, "prompt": prompt, "n": "1",
              "size": f"{size[0]}x{size[1]}", "quality": quality or model.quality,
              "output_format": fmt}
    if fmt == "jpeg":
        fields["output_compression"] = "92"
    if transparent and fmt == "png":
        fields["background"] = "transparent"
    refs = [Path(p) for p in references if p]
    headers = {"Authorization": f"Bearer {_key()}"}
    attempt = limited = 0
    while True:
        _wait_turn(len(refs))
        try:
            if refs:
                files = [("image[]", (f"ref{i}.png", _reference_bytes(p), "image/png"))
                         for i, p in enumerate(refs)]
                response = requests.post(EDITS, headers=headers, data=fields, files=files,
                                         timeout=300)
            else:
                body = dict(fields, n=1)
                if fmt == "jpeg":
                    body["output_compression"] = 92
                response = requests.post(GENERATIONS, headers=headers, json=body, timeout=300)
        except requests.RequestException as exc:
            attempt += 1
            if attempt >= ATTEMPTS:
                raise ExternalServiceError(SERVICE, str(exc),
                                           user_message="Couldn't reach OpenAI to draw a "
                                                        "picture.") from exc
            time.sleep(3 * attempt)
            continue
        text = response.text or ""
        if response.status_code == 429 and "rate limit" in text.lower():
            # Waited out, however long it takes: the limiter above should
            # make this rare, and a lost frame costs more than a minute.
            limited += 1
            if limited < RATE_LIMITED_ATTEMPTS:
                wait = _rate_limited(response)
                log.info(f"  [animation] image service at its limit ({per_minute} a minute); "
                         f"waiting {wait:.0f}s")
                time.sleep(wait)
                continue
        elif response.status_code >= 500:
            attempt += 1
            if attempt < ATTEMPTS:
                time.sleep(10 * attempt)
                continue
        if response.status_code != 200:
            raise _error(response)
        data = response.json()
        costs.record_openai_image_usage(operation, model.model, data.get("usage"),
                                        model.estimate)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(out_path, base64.b64decode(data["data"][0]["b64_json"]))
        return out_path


# --- batches ---------------------------------------------------------------

def _batch_journal_path() -> Path:
    from core.paths import CACHE_DIR
    return CACHE_DIR / "image_batches.json"


def _read_batch_journal() -> dict:
    import json
    try:
        return json.loads(_batch_journal_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_batch_journal(key: str, entry: dict = None) -> None:
    """Record (or with no entry, forget) a batch. Checkpointing, so
    best-effort: a journal that can't be written costs at most one batch
    paid twice if the app stops mid-wait."""
    import json
    try:
        with _journal_lock:
            entries = _read_batch_journal()
            cutoff = time.time() - 28 * 86400
            entries = {k: v for k, v in entries.items() if v.get("at", 0) >= cutoff}
            if entry:
                entries[key] = entry
            else:
                entries.pop(key, None)
            path = _batch_journal_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - checkpointing; see above
        log.warning(f"  [animation] couldn't update the image batch journal ({exc})")


def _batch_key(jobs: list) -> str:
    import hashlib
    import json
    said = [[str(j["key"]), j["prompt"], [f"{Path(r).name}:{int(Path(r).stat().st_mtime)}" for r in j["references"]],
             list(j["size"]), j.get("quality") or j["model"].quality, j["model"].model] for j in jobs]
    return hashlib.sha256(json.dumps(said, sort_keys=True).encode("utf-8")).hexdigest()


def _upload(content: bytes, name: str, kind: str, purpose: str) -> str:
    response = requests.post(FILES, headers={"Authorization": f"Bearer {_key()}"}, data={"purpose": purpose},
                             files={"file": (name, content, kind)}, timeout=300)
    if response.status_code != 200:
        raise _error(response)
    return response.json()["id"]


def _forget_files(ids: list) -> None:
    """Uploaded references and batch files, deleted once collected (best
    effort: a file left behind costs nothing but room)."""
    for file_id in ids:
        try:
            requests.delete(f"{FILES}/{file_id}", headers={"Authorization": f"Bearer {_key()}"}, timeout=60)
        except requests.RequestException:
            pass


def _wait_batch(batch_id: str) -> dict:
    headers = {"Authorization": f"Bearer {_key()}"}
    started, pause = time.time(), BATCH_POLL_FIRST
    while True:
        try:
            batch = requests.get(f"{BATCHES}/{batch_id}", headers=headers, timeout=60).json()
        except (requests.RequestException, ValueError):
            batch = {}
        if batch.get("status") in ("completed", "failed", "expired", "cancelled"):
            return batch
        if time.time() - started > BATCH_WAIT_MAX:
            log.warning(f"  [animation] image batch {batch_id} hadn't finished after "
                        f"{BATCH_WAIT_MAX // 3600} hours; cancelled")
            requests.post(f"{BATCHES}/{batch_id}/cancel", headers=headers, timeout=60)
            return batch
        time.sleep(pause)
        pause = min(pause * 2, BATCH_POLL_MAX)


def draw_batch(jobs: list) -> dict:
    """Many pictures as one OpenAI batch, at half price: {job key: path,
    or None for one that failed}. Each job is {"key", "prompt", "out",
    "model", "references", "size", "operation", "quality"?}, every one with
    references (they go to the edits endpoint). Blocks until the batch
    ends, so only for work nobody is waiting on."""
    import json
    from core import film_budget
    if not jobs:
        return {}
    film_budget.check_current()
    headers = {"Authorization": f"Bearer {_key()}"}
    key = _batch_key(jobs)
    entry = _read_batch_journal().get(key)
    if entry:
        log.info(f"  [animation] picking up image batch {entry['batch']} from an earlier run")
    else:
        file_ids, uploaded = {}, []
        for job in jobs:
            for ref in job["references"]:
                ref = str(ref)
                if ref not in file_ids:
                    file_ids[ref] = _upload(_reference_bytes(Path(ref)), "ref.png", "image/png", "vision")
                    uploaded.append(file_ids[ref])
        lines = []
        for job in jobs:
            fmt = "png" if Path(job["out"]).suffix.lower() == ".png" else "jpeg"
            body = {"model": job["model"].model, "prompt": job["prompt"], "n": 1,
                    "images": [{"file_id": file_ids[str(r)]} for r in job["references"]],
                    "size": f"{job['size'][0]}x{job['size'][1]}",
                    "quality": job.get("quality") or job["model"].quality, "output_format": fmt}
            if fmt == "jpeg":
                body["output_compression"] = 92
            lines.append(json.dumps({"custom_id": str(job["key"]), "method": "POST", "url": "/v1/images/edits",
                                     "body": body}))
        input_id = _upload("\n".join(lines).encode("utf-8"), "batch.jsonl", "application/jsonl", "batch")
        response = requests.post(BATCHES, headers={**headers, "Content-Type": "application/json"}, timeout=60,
                                 data=json.dumps({"input_file_id": input_id, "endpoint": "/v1/images/edits",
                                                  "completion_window": "24h"}))
        if response.status_code != 200:
            _forget_files(uploaded + [input_id])
            raise _error(response)
        entry = {"batch": response.json()["id"], "files": uploaded + [input_id], "at": time.time()}
        _write_batch_journal(key, entry)
        log.info(f"  [animation] {len(jobs)} picture(s) sent as batch {entry['batch']} at half price; waiting")
    batch = _wait_batch(entry["batch"])
    by_key = {str(j["key"]): j for j in jobs}
    out = {j["key"]: None for j in jobs}
    collected = []
    if batch.get("output_file_id"):
        collected.append(batch["output_file_id"])
        text = requests.get(f"{FILES}/{batch['output_file_id']}/content", headers=headers, timeout=600).text
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            job = by_key.get(row.get("custom_id"))
            response = row.get("response") or {}
            body = response.get("body") or {}
            if job is None:
                continue
            if response.get("status_code") != 200 or not body.get("data"):
                log.warning(f"  [animation] picture {job['key']} failed in the batch: "
                            f"{str((body.get('error') or {}).get('message') or row.get('error'))[:160]}")
                continue
            costs.record_openai_image_usage(job.get("operation", "animation_keyframe"), job["model"].model,
                                            body.get("usage"), job["model"].estimate, batch=True)
            path = Path(job["out"])
            path.parent.mkdir(parents=True, exist_ok=True)
            write_atomically(path, base64.b64decode(body["data"][0]["b64_json"]))
            out[job["key"]] = path
    if batch.get("error_file_id"):
        collected.append(batch["error_file_id"])
    missing = sum(1 for v in out.values() if v is None)
    log.info(f"  [animation] image batch {entry['batch']} {batch.get('status', 'ended')}: "
             f"{len(jobs) - missing} drawn" + (f", {missing} failed" if missing else ""))
    _forget_files(entry.get("files", []) + collected)
    _write_batch_journal(key)
    return out
