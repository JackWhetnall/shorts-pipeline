"""
Narration and word-level caption timings, in one pass.

ElevenLabs' with-timestamps endpoint returns character-level alignment
against the exact text sent, so word timings come from grouping runs of
non-whitespace characters. Punctuation stays attached to its word for
free, with no fuzzy re-matching to recover it.

Segments are spoken separately and stitched back together with real
silence: segment 0, pause, citation if any, pause, segment 1, and so on.
A citation's speaking time folds into segment 0's span, so segment 0's
footage keeps playing through the readout rather than needing its own
clip. Every pause length comes from the channel's pacing config.

Timings are derived from the audio that was actually produced, never
estimated from word counts. Punctuation pauses and engine quirks make
word-count estimates unreliable enough that captions visibly drift.

Two independent quality checks run on every segment, because they catch
different failures. The alignment check reads ElevenLabs' own metadata
for a backward time jump, a repeated phrase, or too many words. The
transcript check transcribes the real rendered audio locally and diffs it
against the intended text — which is the only one that can catch a
garble inside a word that leaves the metadata looking perfectly clean.
"""

from __future__ import annotations

import base64
import difflib
import os
import re
import shutil
import time
from pathlib import Path

import numpy as np
import requests

from core import costs, job_context, voice_quota
from core.errors import ExternalServiceError, MissingCredentialError
from core.logging_setup import get_logger
from pipeline.audio import apply_fade, decode_audio_file, match_channels
from pipeline.plan import Voiceover, WordTiming

log = get_logger(__name__)

ELEVENLABS_MODEL = "eleven_turbo_v2_5"
SAMPLE_RATE = 44100
OUTPUT_FORMAT = f"mp3_{SAMPLE_RATE}_128"
TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"

# ElevenLabs' concurrent-request ceiling is tier-dependent and can be as
# low as 2-3. Deliberately below the generic default: tripping it doesn't
# just slow things down, it 429s. The backoff below is the real safety
# net; this makes hitting the limit less likely in the first place.
TTS_MAX_WORKERS = 3

# Retry budget for 429 and 5xx. Separate from the per-segment quality
# retry below, which is about a bad-sounding result rather than a request
# that never completed. A 429 used to propagate straight out and kill a
# whole video on first occurrence.
RATE_LIMIT_MAX_RETRIES = 5
RATE_LIMIT_BACKOFF_BASE = 2.0   # seconds, doubling: 2, 4, 8, 16, 32

# A hard cut at the last reported character can clip a word's natural
# decay; a short pad avoids that without admitting real silence.
TRAILING_PAD = 0.25
SEGMENT_FADE_IN = 0.01
SEGMENT_FADE_OUT = 0.02

# Local, not a cloud ASR service — this is a QA check and shouldn't add a
# third paid vendor. small.en rather than base.en because the smaller
# model mis-transcribes uncommon proper nouns ("Aesop" as "Asop"), and
# names are core content here, not edge cases.
WHISPER_MODEL_SIZE = "small.en"
TRANSCRIPT_MATCH_THRESHOLD = 0.85

# Homographs the engine mispronounces without context, respelled for
# speech only. Captions always show the original spelling.
PRONUNCIATION_OVERRIDES = {"Job": "Jobe"}

_whisper_model = None
# Set once if the model can't be loaded at all, so a machine without it
# doesn't pay the same failure per segment, per video, forever.
_whisper_unavailable = False


def _api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise MissingCredentialError("ELEVENLABS_API_KEY", "voiceover generation")
    return key


def _get_whisper():
    """The local verification model, or None if it isn't usable here.

    Returns None rather than raising. This is a quality check on top of a
    result that already exists — the audio is synthesized and paid for by
    the time it runs — so a missing model, a failed first-time download or
    a machine without the disk for it should cost the check, not the
    video. The failure is recorded once and reported once.
    """
    global _whisper_model, _whisper_unavailable
    if _whisper_unavailable:
        return None
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu",
                                          compute_type="int8")
        except Exception as exc:  # noqa: BLE001 - a QA check must not fail a render
            _whisper_unavailable = True
            log.warning(f"  [tts] speech verification is unavailable ({exc}). "
                        f"Audio will be generated without the transcript check.")
            return None
    return _whisper_model


# --- text handling ----------------------------------------------------

def apply_pronunciation_overrides(text: str) -> str:
    for original, respelled in PRONUNCIATION_OVERRIDES.items():
        text = re.sub(rf"\b{re.escape(original)}\b", respelled, text)
    return text


def revert_pronunciation_overrides(word: str) -> str:
    """Undo a respelling, including with punctuation attached ("Jobe," ->
    "Job,").

    Case-insensitive, case-preserving. A case-sensitive version silently
    never fired on the lowercased transcript-comparison path, so Whisper
    "correcting" the respelled Jobe back to Job read as a genuine
    mismatch and triggered a paid retry on perfectly good audio.
    """
    for original, respelled in PRONUNCIATION_OVERRIDES.items():
        if word.lower().startswith(respelled.lower()):
            replacement = original if word[:1].isupper() else original.lower()
            return replacement + word[len(respelled):]
    return word


_CITATION_PATTERN = re.compile(r"^(.*?)\s+(\d+):(\d+)(?:-(\d+))?$")


def expand_citation_for_speech(citation: str) -> str:
    """"John 3:16" -> "John, chapter 3, verse 16".

    Read as a raw number and colon it comes out as "three colon sixteen".
    Anything not matching the book chapter:verse shape (a bare
    "Shakespeare") is spoken unchanged. Captions show this expanded form
    because captions always reflect what is actually said.
    """
    match = _CITATION_PATTERN.match((citation or "").strip())
    if not match:
        return citation
    book, chapter, verse_start, verse_end = match.groups()
    if verse_end:
        return f"{book}, chapter {chapter}, verses {verse_start} to {verse_end}"
    return f"{book}, chapter {chapter}, verse {verse_start}"


_WORD_JOIN = re.compile(r"[-']")
_WORD_NORMALIZE = re.compile(r"[^a-z0-9]+")


def normalize_words(text: str) -> list:
    """Comparable word list.

    Hyphens and apostrophes are stripped rather than treated as
    separators: Whisper sometimes hyphenates a word it's unsure of
    ("pangram" as "pan-gram"), which would otherwise read as one wrong
    word becoming two.
    """
    joined = _WORD_JOIN.sub("", (text or "").lower())
    return [revert_pronunciation_overrides(w) for w in _WORD_NORMALIZE.sub(" ", joined).split()]


_PUNCT_STRIP = re.compile(r"^[.,!?;:\"'()\[\]]+|[.,!?;:\"'()\[\]]+$")


def looks_glitched(text: str, word_timings: list) -> bool:
    """Whether ElevenLabs' own alignment metadata looks wrong.

    Three cheap signals: a word start moving backward (a replayed chunk
    restarts its clock); a 3-word phrase reappearing soon after (catches
    a small duplicated fragment mid-sentence, which barely moves the word
    count); and noticeably more words than the source has.
    """
    if not word_timings:
        return False
    for i in range(1, len(word_timings)):
        if word_timings[i].start < word_timings[i - 1].start:
            return True

    words = [_PUNCT_STRIP.sub("", w.word.lower()) for w in word_timings]
    last_seen = {}
    for i in range(len(words) - 2):
        gram = tuple(words[i:i + 3])
        if not all(gram):
            continue
        if gram in last_seen and i - last_seen[gram] < 40:
            return True
        last_seen[gram] = i

    # Very short text tokenizes unevenly ("Job 1:8"), so its expected
    # count isn't a reliable baseline.
    expected = len(text.split())
    return expected > 4 and len(word_timings) > expected * 1.15 + 2


def transcript_match_ratio(expected_text: str, audio_path: str) -> float:
    """Word-level similarity between the intended text and what the
    rendered audio actually says. Both sides go through the same
    normalisation, so a respelling isn't penalised either way."""
    model = _get_whisper()
    if model is None:
        # No verification available: report a pass so the caller doesn't
        # retry synthesis it has no way to judge. Retrying against a check
        # that cannot run would just triple the bill.
        return 1.0
    try:
        segments, _ = model.transcribe(
            audio_path, language="en", beam_size=1, condition_on_previous_text=False)
        transcribed = " ".join(seg.text for seg in segments)
    except Exception as exc:  # noqa: BLE001 - see _get_whisper
        log.warning(f"  [tts] transcript check failed to run ({exc}); skipping it.")
        return 1.0
    expected = normalize_words(expected_text)
    if not expected:
        return 1.0
    return difflib.SequenceMatcher(None, expected, normalize_words(transcribed)).ratio()


def words_from_alignment(alignment: dict) -> list:
    """Group character-level alignment into words on whitespace.
    Punctuation is just another non-whitespace character, so it stays
    attached at the right index automatically."""
    characters = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]

    words = []
    current, start, end = [], None, None
    for ch, ch_start, ch_end in zip(characters, starts, ends):
        if ch.isspace():
            if current:
                words.append(WordTiming("".join(current), start, end))
                current, start = [], None
        else:
            if start is None:
                start = ch_start
            current.append(ch)
            end = ch_end
    if current:
        words.append(WordTiming("".join(current), start, end))
    return words


# --- synthesis --------------------------------------------------------

def _post_with_backoff(voice_id: str, payload: dict):
    delay = RATE_LIMIT_BACKOFF_BASE
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        response = requests.post(
            TTS_URL.format(voice_id=voice_id),
            headers={"xi-api-key": _api_key(), "Content-Type": "application/json"},
            json=payload, timeout=60,
        )
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == RATE_LIMIT_MAX_RETRIES:
                raise ExternalServiceError(
                    "The voice service (ElevenLabs)",
                    f"HTTP {response.status_code} after {attempt + 1} attempts",
                    status=response.status_code,
                    user_message=("The voice service kept rate-limiting or failing. "
                                  "Waiting a few minutes and retrying usually works."),
                )
            retry_after = response.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else delay
            log.info(f"  [tts] ElevenLabs returned {response.status_code} "
                     f"(attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES}), waiting {wait:.0f}s...")
            time.sleep(wait)
            delay *= 2
            continue
        if response.status_code in (401, 402, 403):
            raise _rejection_error(response)
        response.raise_for_status()
        return response
    raise ExternalServiceError("The voice service (ElevenLabs)", "exhausted retries")


def _rejection_error(response) -> ExternalServiceError:
    """Turn a 401/402/403 into the actual reason, not a guess.

    A bad or missing key is only one of several things ElevenLabs answers
    this way, and it is not even the most common one. Two real examples,
    both reachable with a perfectly valid key:

      401 {"detail": {"code": "quota_exceeded",
                      "message": "This request exceeds your quota of
                      10000. You have 0 credits remaining..."}}
      402 {"detail": {"code": "paid_plan_required",
                      "message": "Free users cannot use library voices
                      via the API..."}}

    Telling someone to "check that ELEVENLABS_API_KEY is set correctly"
    when their key is fine and their quota is simply spent sends them
    looking in the wrong place. ElevenLabs' own message already says what
    happened; the job here is to surface it and add the one thing it
    doesn't say — what to actually do next.
    """
    code, detail_message = "", ""
    try:
        detail = response.json().get("detail", {})
        if isinstance(detail, dict):
            code = detail.get("code", detail.get("status", ""))
            detail_message = detail.get("message", "")
        else:
            detail_message = str(detail)
    except ValueError:
        detail_message = response.text[:300]

    if code == "quota_exceeded":
        user_message = (f"ElevenLabs has run out of character quota for this "
                        f"account. {detail_message} Upgrade the plan or wait for "
                        f"the quota to reset.")
    elif code == "paid_plan_required":
        user_message = (f"ElevenLabs refused this voice on a free plan: "
                        f"{detail_message} Use a voice this account actually owns "
                        f"(cloned or added to its own library), or upgrade the plan.")
    else:
        # A genuinely bad or missing key still lands here, so the
        # original advice is kept — just no longer the only explanation
        # offered for every 401/402/403.
        user_message = (f"ElevenLabs rejected the request ({response.status_code}"
                        f"{f', {code}' if code else ''}): "
                        f"{detail_message or 'no detail returned'}. If this "
                        f"persists, check that ELEVENLABS_API_KEY is set correctly.")

    return ExternalServiceError(
        "The voice service (ElevenLabs)",
        f"HTTP {response.status_code}" + (f" {code}" if code else ""),
        status=response.status_code,
        user_message=user_message,
    )


def synthesize_segment(text: str, voice_id: str, out_path: str, speed: float = 1.0,
                       max_attempts: int = 3) -> tuple:
    """One segment. Returns (word_timings, samples, fps).

    Retries on either quality signal, since both indicate a transient
    service-side hiccup rather than a deterministic failure.

    (An audio-envelope self-similarity check was tried here and dropped:
    validated against ten real syntheses of known-good text, it flagged
    all ten. Real speech correlates with itself too readily at this
    timescale for a cheap envelope check to distinguish a duplicated
    chunk from a person talking normally. The transcript check covers
    what it was for, by comparing words rather than waveform shape.)
    """
    tts_text = apply_pronunciation_overrides(text)
    word_timings, samples = [], None

    for attempt in range(max_attempts):
        response = _post_with_backoff(voice_id, {
            "text": tts_text,
            "model_id": ELEVENLABS_MODEL,
            "output_format": OUTPUT_FORMAT,
            "voice_settings": {"speed": speed},
        })
        costs.record_elevenlabs("voiceover", ELEVENLABS_MODEL, len(tts_text))

        data = response.json()
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(data["audio_base64"]))

        word_timings = words_from_alignment(data["alignment"])
        samples = decode_audio_file(out_path, fps=SAMPLE_RATE)
        is_last = attempt == max_attempts - 1

        if looks_glitched(tts_text, word_timings) and not is_last:
            log.info(f"  [tts] garbled synthesis detected, retrying "
                     f"({attempt + 2}/{max_attempts})...")
            continue

        ratio = transcript_match_ratio(tts_text, out_path)
        if ratio < TRANSCRIPT_MATCH_THRESHOLD and not is_last:
            log.info(f"  [tts] transcript check found a mismatch ({ratio:.0%}), "
                     f"retrying ({attempt + 2}/{max_attempts})...")
            continue
        if ratio < TRANSCRIPT_MATCH_THRESHOLD:
            log.warning(f"  [tts] transcript still mismatched after {max_attempts} attempts "
                        f"({ratio:.0%}). This segment may have an audible artifact — "
                        f"worth listening to: {out_path}")
        break

    if samples is None or len(samples) == 0:
        raise ExternalServiceError(
            "The voice service (ElevenLabs)",
            f"no audio returned for a segment after {max_attempts} attempts",
            user_message=("The voice service returned empty audio for part of the "
                          "script. Retrying usually works."),
        )

    for timing in word_timings:
        timing.word = revert_pronunciation_overrides(timing.word)
    return word_timings, samples, SAMPLE_RATE


def build_plan(segments: list, citation: str, pacing) -> list:
    """[(text, pause_after, segment_index_or_None), ...].

    The spoken citation gets index None: it doesn't start its own visual
    segment, it folds into segment 0's span. Omitted entirely when a
    format has no citation.
    """
    plan = []
    last = len(segments) - 1
    for i, segment in enumerate(segments):
        if i == 0 and citation:
            plan.append((segment.text, pacing.pause_after_first_segment, i))
            plan.append((expand_citation_for_speech(citation), pacing.pause_after_citation, None))
        else:
            pause = pacing.pause_between_segments if i < last else 0.0
            plan.append((segment.text, pause, i))
    return plan


def narration_characters(segments: list, citation: str, pacing) -> int:
    """Characters ElevenLabs will bill for one clean pass of this script."""
    return sum(len(apply_pronunciation_overrides(text))
               for text, _, _ in build_plan(segments, citation, pacing))


def _stitch(results, segments, out_audio_path: str):
    """Assemble segment audio into one track, filling in segment spans.

    Sequential by necessity: each segment's start time depends on the
    cumulative duration of everything before it. The synthesis itself is
    what runs concurrently.
    """
    from moviepy.audio.AudioClip import AudioArrayClip

    arrays, all_timings = [], []
    segment_starts = {}
    offset = 0.0
    fps = SAMPLE_RATE
    nchannels = None

    for (pause, segment_index, timings, samples) in results:
        if samples.ndim == 1:
            samples = samples.reshape(-1, 1)
        # The first segment sets the channel count; every later one is
        # coerced to match, since concatenating mismatched shapes fails
        # deep inside numpy rather than anywhere informative.
        if nchannels is None:
            nchannels = samples.shape[1]
        samples = match_channels(samples, nchannels)

        if timings:
            trim = int(min(len(samples), (timings[-1].end + TRAILING_PAD) * fps))
            samples = samples[:trim]

        samples = apply_fade(samples, fps, SEGMENT_FADE_IN, SEGMENT_FADE_OUT)

        if segment_index is not None:
            segment_starts[segment_index] = offset

        arrays.append(samples)
        for t in timings:
            all_timings.append(WordTiming(t.word, t.start + offset, t.end + offset))
        offset += len(samples) / fps

        if pause > 0:
            arrays.append(np.zeros((int(pause * fps), nchannels)))
            offset += pause

    final = np.concatenate(arrays, axis=0)
    clip = AudioArrayClip(final, fps=fps)
    clip.write_audiofile(out_audio_path, codec="libmp3lame", logger=None)
    clip.close()

    starts = [segment_starts[i] for i in range(len(segments))]
    ends = starts[1:] + [offset]
    for segment, start, end in zip(segments, starts, ends):
        segment.start = start
        segment.end = end

    return all_timings, final, fps


def generate_voiceover(segments: list, citation, voice_id: str, out_audio_path: str,
                       pacing, speed: float = 1.0) -> Voiceover:
    """Synthesize the whole narration and fill in each segment's real
    start/end times.

    `samples` comes back in memory rather than being re-read from the
    written file: re-decoding a lossily-encoded file back into
    frame-accurate samples near its exact end is unreliable, and the real
    samples are already here.
    """
    plan = build_plan(segments, citation, pacing)
    out_path = Path(out_audio_path)
    segment_paths = [out_path.with_name(f"{out_path.stem}_seg{i}.mp3") for i in range(len(plan))]

    job_context.report_detail("tts", None, {"total": len(plan), "items": []})
    for i, (text, _, _) in enumerate(plan):
        preview = text if len(text) <= 50 else text[:47] + "..."
        job_context.report_detail("tts", i, {"preview": preview, "status": "pending"})

    def synth_one(item):
        i, (text, pause, segment_index) = item
        preview = text if len(text) <= 50 else text[:47] + "..."
        log.info(f'  [tts] synthesizing {i + 1}/{len(plan)}: "{preview}"')
        job_context.report_detail("tts", i, {"status": "active"})
        try:
            timings, samples, _ = synthesize_segment(text, voice_id, str(segment_paths[i]), speed)
        except Exception:
            job_context.report_detail("tts", i, {"status": "error"})
            raise
        job_context.report_detail("tts", i, {"status": "done"})
        return pause, segment_index, timings, samples

    try:
        results = job_context.parallel_map(synth_one, list(enumerate(plan)),
                                           max_workers=TTS_MAX_WORKERS)
        all_timings, final, fps = _stitch(results, segments, out_audio_path)
    finally:
        for path in segment_paths:
            path.unlink(missing_ok=True)

    return Voiceover(audio_path=Path(out_audio_path), word_timings=all_timings,
                     samples=final, fps=fps)


def run(plan):
    """Pipeline stage: fill in plan.voiceover and each segment's timings.

    A checkpointed voiceover is reused after an interruption — several
    ElevenLabs calls plus local Whisper verification is the most
    expensive thing here to redo. The cached mp3 is decoded fresh rather
    than trusting stored samples, for the same reason everything else in
    this pipeline decodes rather than round-tripping raw arrays.
    """
    job_context.report_stage(2)

    checkpoint = job_context.load_json_checkpoint("voiceover")
    cached_audio = job_context.checkpoint_artifact_path("voiceover.mp3")
    if checkpoint and cached_audio and cached_audio.exists():
        log.info("[2/5] Reusing the voiceover from the interrupted attempt.")
        shutil.copyfile(cached_audio, plan.audio_path)
        fps = checkpoint["fps"]
        samples = decode_audio_file(str(plan.audio_path), fps=fps)
        for segment, timing in zip(plan.script.segments, checkpoint["segments"]):
            segment.start, segment.end = timing["start"], timing["end"]
        plan.voiceover = Voiceover(
            audio_path=plan.audio_path,
            word_timings=[WordTiming.from_jsonable(w) for w in checkpoint["word_timings"]],
            samples=samples, fps=fps,
        )
        return plan

    # Checked before the first request rather than discovered on the
    # third segment: a quota that runs out mid-narration still bills the
    # segments that did get through.
    voice_quota.require_room(narration_characters(plan.script.segments, plan.script.citation,
                                                  plan.channel.pacing))

    log.info("[2/5] Generating the voiceover...")
    plan.voiceover = generate_voiceover(
        plan.script.segments, plan.script.citation, plan.channel.voice,
        str(plan.audio_path), plan.channel.pacing, speed=plan.channel.speed,
    )

    try:
        target = job_context.checkpoint_artifact_path("voiceover.mp3")
        if target is not None:
            shutil.copyfile(plan.audio_path, target)
            job_context.save_json_checkpoint("voiceover", {
                "fps": plan.voiceover.fps,
                "word_timings": [w.to_jsonable() for w in plan.voiceover.word_timings],
                "segments": [{"start": s.start, "end": s.end} for s in plan.script.segments],
            })
    except Exception:  # noqa: BLE001 - checkpointing is best-effort
        pass
    return plan
