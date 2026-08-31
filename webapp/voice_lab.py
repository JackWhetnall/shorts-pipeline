"""
Voice/cadence/speed auditioning, cached so trying combinations doesn't
repeatedly burn ElevenLabs quota.

Two independent caches, both under cache/ (same directory
quote_source.py already uses for its Shakespeare cache):
- cache/voice_lab_voices.json: ElevenLabs' premade voice list (voice_id,
  name, category, description, preview_url). Refreshed only on request
  (see refresh_voices) — this call doesn't consume TTS character quota,
  but there's no reason to hit it more than needed.
- cache/voice_lab_samples/<voice_id>_<preset>_<speed>.mp3: one snippet
  per combination actually tested, generated once via the real pipeline
  (tts_captions.generate_voiceover) and reused forever after — the "happy
  for it to hit the API once when building" behavior.

CADENCE_PRESETS bundles the pause-timing fields a channel can set in
"pacing" into a few named vibes, so testing cadence doesn't mean
remembering what pause_after_first_segment=0.7 actually sounds like —
"natural" matches config.channels.DEFAULT_PACING's current values
exactly, so it's a known-good baseline, not a guess.
"""

import json
import os
from pathlib import Path

import requests

import config.channels as channels_module
import tts_captions

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
VOICES_CACHE_PATH = CACHE_DIR / "voice_lab_voices.json"
SAMPLES_DIR = CACHE_DIR / "voice_lab_samples"

ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v2/voices"

CADENCE_PRESETS = {
    "tight": {
        "label": "Tight",
        "pacing": {"pause_after_first_segment": 0.3, "pause_between_segments": 0.2, "pause_after_citation": 0.25},
    },
    "natural": {
        "label": "Natural (current default)",
        "pacing": {"pause_after_first_segment": 0.7, "pause_between_segments": 0.4, "pause_after_citation": 0.5},
    },
    "relaxed": {
        "label": "Relaxed",
        "pacing": {"pause_after_first_segment": 1.0, "pause_between_segments": 0.7, "pause_after_citation": 0.8},
    },
    "dramatic": {
        "label": "Dramatic pauses",
        "pacing": {"pause_after_first_segment": 1.4, "pause_between_segments": 1.0, "pause_after_citation": 1.2},
    },
}

# Generic, channel-agnostic sample text — enough sentences to actually
# hear the rhythm between a preset's pauses, not tied to any one
# channel's real content. No citation, so pause_after_citation is stored
# per-preset but not exercised here (most channels are topic-driven and
# never speak one).
TEST_SEGMENTS = [
    {"text": "The quiet moments matter more than we think.", "keywords": []},
    {"text": "Even a small pause can change how a sentence lands.", "keywords": []},
    {"text": "That's the whole idea behind testing this.", "keywords": []},
]


def _elevenlabs_api_key() -> str:
    return os.environ.get("ELEVENLABS_API_KEY")


def refresh_voices() -> list:
    """Fetches ElevenLabs' premade voice list fresh and overwrites the
    cache. Does not consume TTS character quota."""
    api_key = _elevenlabs_api_key()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set in your environment.")

    response = requests.get(
        ELEVENLABS_VOICES_URL,
        headers={"xi-api-key": api_key},
        params={"category": "premade", "page_size": 100},
        timeout=20,
    )
    if not response.ok:
        # ElevenLabs' error body (e.g. "missing the permission voices_read")
        # is far more actionable than requests' generic "401 Unauthorized"
        # — a scoped/restricted API key can synthesize speech fine but
        # still lack read access to the voice list, which is exactly the
        # kind of thing worth surfacing directly instead of a bare status
        # code.
        try:
            detail = response.json().get("detail", {})
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except ValueError:
            message = response.text
        raise RuntimeError(f"ElevenLabs voice list request failed ({response.status_code}): "
                            f"{message or 'no further detail returned'}")
    data = response.json()

    voices = [
        {
            "voice_id": v["voice_id"],
            "name": v["name"],
            "category": v.get("category", ""),
            "description": v.get("description") or "",
            "preview_url": v.get("preview_url"),
        }
        for v in data.get("voices", [])
    ]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(VOICES_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(voices, f, indent=2)
    return voices


def get_cached_voices() -> list:
    """Reads the cached voice list, fetching it once if there's no cache
    yet. Never re-fetches on its own after that — see refresh_voices for
    the explicit manual refresh."""
    if VOICES_CACHE_PATH.exists():
        with open(VOICES_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return refresh_voices()


def _sample_path(voice_id: str, preset_key: str, speed: float) -> Path:
    safe_voice_id = "".join(c for c in voice_id if c.isalnum() or c in "-_")
    return SAMPLES_DIR / f"{safe_voice_id}_{preset_key}_{speed:.2f}.mp3"


def get_or_create_snippet(voice_id: str, preset_key: str, speed: float) -> Path:
    """Returns the cached snippet for this exact (voice, preset, speed)
    combination, generating it via the real pipeline (same stutter fix,
    same transcript-verification safety net a real video gets) only the
    first time it's asked for."""
    if preset_key not in CADENCE_PRESETS:
        raise ValueError(f"Unknown cadence preset: {preset_key!r}")

    target = _sample_path(voice_id, preset_key, speed)
    if target.exists():
        return target

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    pacing = {**channels_module.DEFAULT_PACING, **CADENCE_PRESETS[preset_key]["pacing"], "segment_count": 2}
    tts_captions.generate_voiceover(
        TEST_SEGMENTS, None, voice_id, str(target), pacing, speed=speed,
    )
    return target
