"""
Auditioning voice x cadence x speed combinations without repeatedly
spending ElevenLabs quota.

Two caches, both under cache/:
  voice_lab_voices.json                          the account's voices
  voice_lab_samples/<voice>_<preset>_<speed>.mp3  one snippet per combo

And a shortlist, config/voice_library.json: voices from ElevenLabs' Voice
Library chosen for a channel but not yet added to the account. Listed
with their own free preview clips, so they can be heard before anyone
adds one (decision 124). They can't be test-voiced until they're added.

Each voice row plays ElevenLabs' own preview clip, which is free and
needs no synthesis. Only "test this combo" generates anything, and it's
keyed on the exact combination so testing the same one twice never hits
the API again.

Cadence is named presets rather than raw pause sliders — nobody
remembers what pause_after_first_segment=0.7 sounds like. "Natural"
matches the pipeline defaults exactly, so it's a known baseline rather
than a guess.
"""

from __future__ import annotations

import json
import os

import requests

from core.channels import Pacing
from core.errors import ExternalServiceError, MissingCredentialError
from core.paths import CACHE_DIR, PROJECT_ROOT

VOICES_CACHE_PATH = CACHE_DIR / "voice_lab_voices.json"
SAMPLES_DIR = CACHE_DIR / "voice_lab_samples"
VOICES_URL = "https://api.elevenlabs.io/v2/voices"
LIBRARY_PATH = PROJECT_ROOT / "config" / "voice_library.json"
LIBRARY = "Voice Library"           # the category a shortlisted voice is listed under

CADENCE_PRESETS = {
    "tight": {"label": "Tight",
              "pacing": {"pause_after_first_segment": 0.3,
                         "pause_between_segments": 0.2,
                         "pause_after_citation": 0.25}},
    "natural": {"label": "Natural (pipeline default)",
                "pacing": {"pause_after_first_segment": 0.7,
                           "pause_between_segments": 0.4,
                           "pause_after_citation": 0.5}},
    "relaxed": {"label": "Relaxed",
                "pacing": {"pause_after_first_segment": 1.0,
                           "pause_between_segments": 0.7,
                           "pause_after_citation": 0.8}},
    "dramatic": {"label": "Dramatic pauses",
                 "pacing": {"pause_after_first_segment": 1.4,
                            "pause_between_segments": 1.0,
                            "pause_after_citation": 1.2}},
}

# Channel-agnostic sample text: enough sentences to hear the rhythm
# between pauses, tied to no particular channel's content.
TEST_LINES = [
    "The quiet moments matter more than we think.",
    "Even a small pause can change how a sentence lands.",
    "That's the whole idea behind testing this.",
]


def refresh_voices() -> list:
    """Fetch the account's voices: the premade ones and its own (generated,
    cloned, added from the library). Doesn't consume TTS character quota."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise MissingCredentialError("ELEVENLABS_API_KEY", "the voice list")

    response = requests.get(
        VOICES_URL, headers={"xi-api-key": key},
        params={"page_size": 100}, timeout=20,
    )
    if not response.ok:
        # ElevenLabs' own error body ("missing the permission voices_read")
        # is far more actionable than a bare 401 — a key restricted to
        # text-to-speech can synthesize fine but still can't list voices,
        # which is exactly the kind of thing worth surfacing verbatim.
        try:
            detail = response.json().get("detail", {})
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except ValueError:
            message = response.text
        raise ExternalServiceError(
            "The voice service (ElevenLabs)", f"HTTP {response.status_code}",
            status=response.status_code,
            user_message=(f"Couldn't load the voice list ({response.status_code}): "
                          f"{message or 'no detail returned'}. A key restricted to "
                          f"text-to-speech needs the voices_read permission as well."),
        )

    voices = [
        {"voice_id": v["voice_id"], "name": v["name"],
         "category": v.get("category", ""), "description": v.get("description") or "",
         "preview_url": v.get("preview_url")}
        for v in response.json().get("voices", [])
    ]
    # The account's own first: they're the ones a channel was set up with.
    voices.sort(key=lambda v: v["category"] == "premade")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(VOICES_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(voices, f, indent=2)
    return voices


def get_cached_voices(library: bool = True) -> list:
    """Cached list, fetched once if absent. Never refreshes on its own.
    `library`: the shortlisted Voice Library voices after the account's,
    those not in it yet; off where only a voice that can speak will do."""
    voices = None
    if VOICES_CACHE_PATH.exists():
        try:
            with open(VOICES_CACHE_PATH, "r", encoding="utf-8") as f:
                voices = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    if voices is None:
        voices = refresh_voices()
    if not library:
        return voices
    have = {v["voice_id"] for v in voices}
    return voices + [v for v in library_voices() if v["voice_id"] not in have]


def library_voices() -> list:
    """The shortlisted Voice Library voices, as the voice list has them."""
    try:
        rows = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [{"voice_id": r["voice_id"], "name": r["name"], "category": LIBRARY,
             "description": r.get("description") or "", "preview_url": r.get("preview_url")}
            for r in rows if r.get("voice_id") and r.get("name")]


def shortlist(entries: list) -> list:
    """Add Voice Library voices to the shortlist ({voice_id, name,
    description, preview_url, public_owner_id}), replacing any with the
    same id. Returns the shortlist."""
    try:
        rows = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    new = {e["voice_id"]: e for e in entries if e.get("voice_id")}
    rows = [r for r in rows if r.get("voice_id") not in new] + list(new.values())
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY_PATH.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return rows


def sample_path(voice_id: str, preset_key: str, speed: float):
    safe = "".join(c for c in voice_id if c.isalnum() or c in "-_")
    return SAMPLES_DIR / f"{safe}_{preset_key}_{speed:.2f}.mp3"


def get_or_create_snippet(voice_id: str, preset_key: str, speed: float):
    """The cached snippet for this exact combination, generated through
    the real pipeline the first time — so it gets the same audio handling
    and verification a real video does."""
    from pipeline import tts
    from pipeline.plan import Segment

    if preset_key not in CADENCE_PRESETS:
        raise ExternalServiceError(
            "Voice Lab", f"unknown preset {preset_key}",
            user_message=f'"{preset_key}" isn\'t a cadence preset.')

    target = sample_path(voice_id, preset_key, speed)
    if target.exists():
        return target

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    pacing = Pacing(**{**CADENCE_PRESETS[preset_key]["pacing"], "segment_count": len(TEST_LINES)})
    tts.generate_voiceover([Segment(line) for line in TEST_LINES], None,
                           voice_id, str(target), pacing, speed=speed)
    return target
