"""
Generates the voiceover AND word-level caption timings in one pass, plus
real per-segment start/end times so Stage 2 can cut footage to what's
actually being said instead of a word-count estimate.

ElevenLabs' "with-timestamps" endpoint returns character-level alignment
(exact start/end per character against the text sent), so word timings
come from grouping consecutive non-whitespace characters — this naturally
keeps punctuation attached to its word (no fuzzy re-matching needed to
recover it, unlike a word-boundary-only API). Requires ELEVENLABS_API_KEY.

Segments are spoken one at a time, stitched back together with real
silence in between: segment 0 -> pause -> citation (if any) -> pause ->
segment 1 -> pause -> segment 2 ... A citation's speaking time is folded
into segment 0's span, so segment 0's footage keeps playing through the
citation readout instead of needing its own clip. Pause durations come
from the channel's pacing config (config/channels.py), not a hardcoded
rhythm — a reflective-quote channel and a jokes channel can have
completely different timing.
"""

import base64
import difflib
import os
import re
import shutil
import time
from pathlib import Path

import numpy as np
import requests
from moviepy.audio.AudioClip import AudioArrayClip

from audio_utils import decode_audio_file, apply_fade
import job_context

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_MODEL = "eleven_turbo_v2_5"
ELEVENLABS_SAMPLE_RATE = 44100
ELEVENLABS_OUTPUT_FORMAT = f"mp3_{ELEVENLABS_SAMPLE_RATE}_128"

# How many segments synthesize at once (see _synthesize's job_context.
# parallel_map call). ElevenLabs' concurrent-request limit is tied to
# account tier and can be as low as 2-3 on lower tiers - deliberately
# conservative rather than the generic parallel_map default of 8, since
# tripping it doesn't just slow things down, it 429s. _post_with_backoff
# below is the real safety net regardless of tier; this just makes
# hitting the limit at all less likely in the first place.
TTS_MAX_WORKERS = 3

# _post_with_backoff's retry budget for 429 (rate limit) / 5xx (transient
# service error) responses - independent of _tts_segment's own retry loop
# below, which is about SYNTHESIS QUALITY (a garbled result), not the
# request itself failing. A 429 used to propagate straight out of
# raise_for_status() and kill the whole video generation on the first
# occurrence - exactly the kind of transient condition a short wait
# resolves, not a reason to fail the job outright.
TTS_RATE_LIMIT_MAX_RETRIES = 5
TTS_RATE_LIMIT_BACKOFF_BASE = 2.0  # seconds; doubles each retry (2, 4, 8, 16, 32)


def _post_with_backoff(voice_id: str, payload: dict):
    delay = TTS_RATE_LIMIT_BACKOFF_BASE
    for attempt in range(TTS_RATE_LIMIT_MAX_RETRIES + 1):
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps",
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == TTS_RATE_LIMIT_MAX_RETRIES:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else delay
            print(f"  [tts] ElevenLabs returned {response.status_code} "
                  f"(attempt {attempt + 1}/{TTS_RATE_LIMIT_MAX_RETRIES}), "
                  f"retrying in {wait:.0f}s...")
            time.sleep(wait)
            delay *= 2
            continue
        response.raise_for_status()
        return response

# Independent verification that the rendered audio actually says what the
# script says. _looks_glitched (below) only inspects ElevenLabs' own
# self-reported alignment metadata — it's blind to a synthesis-level
# artifact (a stutter/garble inside a word) that doesn't happen to shift
# word timings or duplicate a whole word. Transcribing the real rendered
# audio with a model that had nothing to do with generating it, and diffing
# against the intended text, catches that class of problem too. Local (not
# a cloud API) so this doesn't add a third paid vendor just for a QA check
# — runs on CPU, int8 quantized, one-time model download on first use.
WHISPER_MODEL_SIZE = "small.en"
TRANSCRIPT_MATCH_THRESHOLD = 0.85

_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _whisper_model


_WORD_JOIN = re.compile(r"[-']")
_WORD_NORMALIZE = re.compile(r"[^a-z0-9]+")


def _normalize_words(text: str) -> list:
    # Hyphens/apostrophes are stripped (not treated as separators) — Whisper
    # sometimes hyphenates a compound word it's unsure of (transcribing
    # "pangram" as "pan-gram"), which would otherwise split one word into
    # two and look like a mismatch against the single-word original.
    joined = _WORD_JOIN.sub("", text.lower())
    words = _WORD_NORMALIZE.sub(" ", joined).split()
    return [_revert_pronunciation_overrides(w) for w in words]


def _transcript_match_ratio(expected_text: str, audio_path: str) -> float:
    """Transcribes audio_path and returns a word-level similarity ratio
    (0-1) against expected_text. Both sides are normalized through
    _revert_pronunciation_overrides so a respelled word (e.g. "Jobe" for
    "Job") isn't penalized whichever way Whisper happens to transcribe it."""
    model = _get_whisper_model()
    segments, _ = model.transcribe(audio_path, language="en", beam_size=1, condition_on_previous_text=False)
    transcribed = " ".join(seg.text for seg in segments)
    expected_words = _normalize_words(expected_text)
    actual_words = _normalize_words(transcribed)
    if not expected_words:
        return 1.0
    return difflib.SequenceMatcher(None, expected_words, actual_words).ratio()

# A hard cut at the exact last-reported-character end can occasionally
# clip a word's natural trailing decay; a small pad avoids that without
# risking including much real silence.
TRAILING_PAD = 0.25

# Short declick fades applied to every segment before concatenation — see
# the comment at the call site in _synthesize.
SEGMENT_FADE_IN = 0.01
SEGMENT_FADE_OUT = 0.02

# Homographs the TTS engine might mispronounce without context. Respelled
# phonetically for TTS only — captions still show the original spelling.
# Matched by exact capitalized word, so the common-noun spelling (e.g.
# "job") is never touched.
PRONUNCIATION_OVERRIDES = {
    "Job": "Jobe",
}


def _apply_pronunciation_overrides(text: str) -> str:
    for original, respelled in PRONUNCIATION_OVERRIDES.items():
        text = re.sub(rf"\b{re.escape(original)}\b", respelled, text)
    return text


def _revert_pronunciation_overrides(word: str) -> str:
    """Undo the respelling in a caption word, even with trailing
    punctuation attached (e.g. "Jobe," -> "Job,"). Case-insensitive match
    (but case-preserving output) since this is also used, via
    _normalize_words, on already-lowercased words in the transcript-match
    check — a case-sensitive check silently never fires there, which
    would make a genuine "Job" vs "Jobe"/"job" wording difference in the
    transcript look like a real mismatch and trigger a pointless retry."""
    for original, respelled in PRONUNCIATION_OVERRIDES.items():
        if word.lower().startswith(respelled.lower()):
            replacement = original if word[:1].isupper() else original.lower()
            return replacement + word[len(respelled):]
    return word


def _words_from_alignment(alignment: dict) -> list:
    """Groups character-level alignment into words by splitting on
    whitespace — punctuation stays attached to its word since it's just
    another non-whitespace character at the correct index."""
    characters = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]

    words = []
    current_chars = []
    current_start = None
    current_end = None
    for ch, start, end in zip(characters, starts, ends):
        if ch.isspace():
            if current_chars:
                words.append({"word": "".join(current_chars), "start": current_start, "end": current_end})
                current_chars = []
                current_start = None
        else:
            if current_start is None:
                current_start = start
            current_chars.append(ch)
            current_end = end
    if current_chars:
        words.append({"word": "".join(current_chars), "start": current_start, "end": current_end})
    return words


def _build_tts_plan(segments: list, citation: str, pacing: dict):
    """Returns [(text, pause_after_seconds, segment_index_or_None), ...].
    segment_index is None for the spoken citation, which doesn't start its
    own visual segment — it folds into segment 0's span. If citation is
    None (no reference to read aloud — e.g. a joke/topic format), it's
    simply omitted."""
    plan = []
    last_index = len(segments) - 1
    for i, seg in enumerate(segments):
        if i == 0 and citation:
            plan.append((seg["text"], pacing["pause_after_first_segment"], i))
            plan.append((_expand_citation_for_speech(citation), pacing["pause_after_citation"], None))
        else:
            pause = pacing["pause_between_segments"] if i < last_index else 0.0
            plan.append((seg["text"], pause, i))
    return plan


_CITATION_PATTERN = re.compile(r"^(.*?)\s+(\d+):(\d+)(?:-(\d+))?$")


def _expand_citation_for_speech(citation: str) -> str:
    """"John 3:16" -> "John, chapter 3, verse 16" (or "verses A to B" for a
    range) so it's spoken naturally instead of read as a raw number/colon
    ("three colon sixteen"). A citation that doesn't match this
    book-chapter:verse shape (e.g. plain "Shakespeare") is spoken
    unchanged. Captions reflect whatever's actually said (this expanded
    form), which is the same "captions match the real audio" principle
    already used everywhere else in this pipeline."""
    match = _CITATION_PATTERN.match(citation.strip())
    if not match:
        return citation
    book, chapter, verse_start, verse_end = match.groups()
    if verse_end:
        return f"{book}, chapter {chapter}, verses {verse_start} to {verse_end}"
    return f"{book}, chapter {chapter}, verse {verse_start}"


_PUNCT_STRIP = re.compile(r"^[.,!?;:\"'()\[\]]+|[.,!?;:\"'()\[\]]+$")


def _looks_glitched(text: str, word_timings: list) -> bool:
    """Defensive check for a duplicated/garbled synthesis — any network
    TTS call can occasionally hiccup. Three cheap, reliable signals:
    - word start times ever moving backward (a replayed chunk restarts its
      own clock);
    - a short phrase (3+ words) reappearing again shortly after — this
      catches a small duplicated fragment inside a long segment (e.g. "when
      we don't" repeating once mid-sentence), which barely moves the total
      word count and would slip past a whole-segment length check;
    - noticeably more words than the source text has overall (catches a
      large-scale duplication even if it isn't a short exact repeat)."""
    if not word_timings:
        return False
    for i in range(1, len(word_timings)):
        if word_timings[i]["start"] < word_timings[i - 1]["start"]:
            return True

    words = [_PUNCT_STRIP.sub("", w["word"].lower()) for w in word_timings]
    gram_size = 3
    last_seen = {}
    for i in range(len(words) - gram_size + 1):
        gram = tuple(words[i:i + gram_size])
        if not all(gram):
            continue
        if gram in last_seen and i - last_seen[gram] < 40:
            return True
        last_seen[gram] = i

    # Skip the word-count check on very short text (references like "Job
    # 1:8" can tokenize unevenly) — a short text's "expected" count isn't
    # a reliable baseline.
    expected = len(text.split())
    if expected > 4 and len(word_timings) > expected * 1.15 + 2:
        return True
    return False


def _tts_segment(text: str, voice_id: str, out_path: str, speed: float = 1.0, max_attempts: int = 3):
    """Synthesize one segment via ElevenLabs, returning (word_timings,
    sample_array, fps). word_timings (seconds, relative to the start of
    this segment) has punctuation intact (from character alignment) and
    any pronunciation respelling reverted back to the original spelling.
    Retries on either of two independent problem signals, since these are
    transient service-side hiccups, not deterministic failures:
    - _looks_glitched: ElevenLabs' own alignment metadata looks wrong
      (backward time jump, repeated phrase, too many words);
    - a low _transcript_match_ratio: an independent local transcription of
      the actual rendered audio doesn't match the intended text. This is
      the check that catches what the metadata-only check can't — a
      synthesis-level artifact (a stutter/garble inside a word) that
      doesn't happen to duplicate a whole word or shift any timestamp, so
      ElevenLabs' self-reported alignment still looks perfectly clean.

    (An additional audio-envelope self-similarity check — comparing energy
    envelopes across the clip to catch a duplicated chunk even when the
    alignment metadata looks clean — was tried and dropped: validated
    against 10 real syntheses of known-clean text, it flagged all 10 as
    glitched. Real speech's natural rhythm correlates with itself too
    easily at this timescale for a cheap envelope check to tell "duplicated
    content" apart from "person talking normally". The transcript-match
    check above supersedes what that was trying to catch, without the
    false-positive problem, by checking actual words said instead of raw
    waveform shape.)"""
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not set in your environment.")

    tts_text = _apply_pronunciation_overrides(text)

    for attempt in range(max_attempts):
        response = _post_with_backoff(voice_id, {
            "text": tts_text,
            "model_id": ELEVENLABS_MODEL,
            "output_format": ELEVENLABS_OUTPUT_FORMAT,
            "voice_settings": {"speed": speed},
        })
        data = response.json()

        with open(out_path, "wb") as audio_file:
            audio_file.write(base64.b64decode(data["audio_base64"]))

        word_timings = _words_from_alignment(data["alignment"])
        match_ratio = _transcript_match_ratio(tts_text, out_path)
        fps = ELEVENLABS_SAMPLE_RATE
        arr = decode_audio_file(out_path, fps=fps)

        is_last_attempt = attempt == max_attempts - 1

        if _looks_glitched(tts_text, word_timings) and not is_last_attempt:
            print(f"  [tts] detected a garbled/repeated synthesis, retrying ({attempt + 2}/{max_attempts})...")
            continue

        if match_ratio < TRANSCRIPT_MATCH_THRESHOLD and not is_last_attempt:
            print(f"  [tts] independent transcript check found a mismatch "
                  f"(match {match_ratio:.0%}), retrying ({attempt + 2}/{max_attempts})...")
            continue
        if match_ratio < TRANSCRIPT_MATCH_THRESHOLD:
            print(f"  [tts] WARNING: transcript mismatch persisted after {max_attempts} attempts "
                  f"(match {match_ratio:.0%}) — this segment may have an audible artifact, "
                  f"worth a manual listen: {out_path}")
        break

    for wt in word_timings:
        wt["word"] = _revert_pronunciation_overrides(wt["word"])

    return word_timings, arr, fps


def _synthesize(segments: list, citation: str, voice_id: str, out_audio_path: str, pacing: dict, speed: float = 1.0):
    # A retry of an interrupted/failed job (webapp/jobs.py's retry_job)
    # reuses the same job id - if this exact voiceover was already
    # synthesized before whatever interrupted the job, reuse it rather
    # than paying for several ElevenLabs calls (plus Whisper verification)
    # a second time. The cached mp3 is decoded fresh rather than trusting
    # a stored array, for the same reason the rest of this file always
    # decodes rather than round-tripping raw samples (see audio_utils.py's
    # decode_audio_file docstring).
    checkpoint = job_context.load_json_checkpoint("voiceover")
    cached_audio = job_context.checkpoint_artifact_path("voiceover.mp3")
    if checkpoint and cached_audio and cached_audio.exists():
        print("  [tts] reusing previously synthesized voiceover (resumed)...")
        shutil.copyfile(cached_audio, out_audio_path)
        fps = checkpoint["fps"]
        final_array = decode_audio_file(out_audio_path, fps=fps)
        return out_audio_path, checkpoint["all_timings"], checkpoint["segment_timings"], final_array, fps

    plan = _build_tts_plan(segments, citation, pacing)

    out_path = Path(out_audio_path)
    seg_paths = [out_path.with_name(f"{out_path.stem}_seg{i}.mp3") for i in range(len(plan))]

    # Build the final track as a raw sample array rather than compositing
    # moviepy AudioClips — moviepy's CompositeAudioClip mishandles mixing
    # clips with different channel counts (real speech vs. synthetic
    # silence), so we do the concatenation ourselves.
    arrays = []
    all_timings = []
    segment_starts = {}
    offset = 0.0
    fps = None
    nchannels = None

    job_context.report_detail("tts", None, {"total": len(plan), "items": []})
    for i, (text, _, _) in enumerate(plan):
        preview = text if len(text) <= 50 else text[:47] + "..."
        job_context.report_detail("tts", i, {"preview": preview, "status": "pending"})

    # The actual ElevenLabs + Whisper-verification work per segment
    # (_tts_segment) is fully independent per segment - only the stitching
    # below (offsets, fades, concatenation) genuinely needs order, since
    # each segment's start time depends on the cumulative duration of
    # everything before it. Run the slow, independent part concurrently,
    # then walk the results in plan order for stitching.
    def _synth_one(item):
        i, (text, pause, segment_index) = item
        preview = text if len(text) <= 50 else text[:47] + "..."
        print(f"  [tts] synthesizing {i + 1}/{len(plan)}: \"{preview}\"")
        job_context.report_detail("tts", i, {"status": "active"})
        try:
            timings, arr, seg_fps = _tts_segment(text, voice_id, str(seg_paths[i]), speed=speed)
        except Exception:
            job_context.report_detail("tts", i, {"status": "error"})
            raise
        job_context.report_detail("tts", i, {"status": "done"})
        return pause, segment_index, timings, arr, seg_fps

    results = job_context.parallel_map(_synth_one, list(enumerate(plan)), max_workers=TTS_MAX_WORKERS)

    try:
        for pause, segment_index, timings, arr, seg_fps in results:
            fps = fps or seg_fps

            if arr.ndim == 1:
                arr = arr.reshape(-1, 1)
            if nchannels is None:
                nchannels = arr.shape[1]
            elif arr.shape[1] != nchannels:
                arr = np.repeat(arr.mean(axis=1, keepdims=True), nchannels, axis=1)

            if timings:
                trim_samples = int(min(len(arr), (timings[-1]["end"] + TRAILING_PAD) * fps))
                arr = arr[:trim_samples]

            # Splicing separately-encoded segments together with a hard cut
            # can leave an audible click/stutter right at the seam if the
            # waveform isn't at zero there — every seam lines up with a
            # sentence/segment boundary, which is exactly where this was
            # reported. A short fade smooths it regardless of cause.
            arr = apply_fade(arr, fps, fade_in=SEGMENT_FADE_IN, fade_out=SEGMENT_FADE_OUT)

            if segment_index is not None:
                segment_starts[segment_index] = offset

            arrays.append(arr)
            for t in timings:
                all_timings.append({
                    "word": t["word"],
                    "start": t["start"] + offset,
                    "end": t["end"] + offset,
                })
            offset += len(arr) / fps

            if pause > 0:
                arrays.append(np.zeros((int(pause * fps), nchannels)))
                offset += pause

        total_duration = offset
        final_array = np.concatenate(arrays, axis=0)
        final_clip = AudioArrayClip(final_array, fps=fps)
        final_clip.write_audiofile(out_audio_path, codec="libmp3lame", logger=None)
        final_clip.close()
    finally:
        for seg_path in seg_paths:
            seg_path.unlink(missing_ok=True)

    starts = [segment_starts[i] for i in range(len(segments))]
    ends = starts[1:] + [total_duration]
    segment_timings = [
        {**seg, "start": start, "end": end}
        for seg, start, end in zip(segments, starts, ends)
    ]

    try:
        cache_target = job_context.checkpoint_artifact_path("voiceover.mp3")
        if cache_target is not None:
            shutil.copyfile(out_audio_path, cache_target)
            job_context.save_json_checkpoint("voiceover", {
                "all_timings": all_timings, "segment_timings": segment_timings, "fps": fps,
            })
    except Exception:
        pass  # checkpointing is best-effort, never block a real result on it

    return out_audio_path, all_timings, segment_timings, final_array, fps


def generate_voiceover(segments: list, citation, voice_id: str, out_audio_path: str, pacing: dict,
                        speed: float = 1.0):
    """
    segments: [{"text":, "keywords":}, ...] — the "segments" list from
    script_gen.generate_script. citation: optional string (e.g. a Bible
    reference) spoken right after segment 0, or None. voice_id: an
    ElevenLabs voice ID (config/channels.py). pacing: the channel's
    pacing config (config/channels.py) — controls pause lengths. speed:
    ElevenLabs' own voice_settings.speed (1.0 = normal, <1 slower, >1
    faster) — a channel-level knob (config/channels.py's "speed",
    defaults to 1.0) also exercised directly by webapp/voice_lab.py for
    auditioning before committing it to a channel.

    Returns (audio_path, word_timings, segment_timings, narration_array, fps).
    word_timings is a list of {"word", "start", "end"} (seconds).
    segment_timings mirrors `segments` with real "start"/"end" seconds added.
    audio_path is written to disk for your records, but narration_array/
    fps are the exact same samples already in memory — pass those straight
    into video_assemble.build_video rather than having it re-decode the
    mp3 file. Re-decoding a lossily-encoded file back into frame-accurate
    samples near its exact end is unreliable (this is the same class of
    ffmpeg-chunked-reader fragility fixed twice already in audio_utils.py),
    and re-decoding is entirely avoidable here since we already have the
    real samples.
    """
    return _synthesize(segments, citation, voice_id, out_audio_path, pacing, speed=speed)


if __name__ == "__main__":
    from config.channels import CHANNELS

    demo_segments = [
        {"text": "The quick brown fox jumps over the lazy dog.", "keywords": ["animals", "chase"]},
        {"text": "Simple words, said plainly, still land.", "keywords": ["simplicity"]},
        {"text": "That is the whole point of a pangram.", "keywords": ["language"]},
    ]
    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    demo_voice_id = CHANNELS["bible_daily"]["voice"]
    path, timings, segment_timings, narration_array, fps = generate_voiceover(
        demo_segments, "Aesop 1:1", demo_voice_id, str(cache_dir / "test.mp3"), CHANNELS["bible_daily"]["pacing"],
    )
    print(path)
    print(timings[:5])
    print(segment_timings)
    print("narration_array shape:", narration_array.shape, "fps:", fps)
