"""
What a place sounds like, under the narration (decision 087).

The first One Day In History film had a voice and a music bed and
nothing else: a bakery with no fire in it, a street with no feet on it.
Each chapter of an outline names its background (`sound`, one of SOUNDS
below), and the video lays that bed under its stretch of the film,
looped, crossfaded into the next chapter's, well under the voice.

The beds are made once by ElevenLabs' sound-effects model and kept, for
every film on every channel: a fixed vocabulary on purpose, so the
library stops costing anything after the first few films. A bed costs
about 40 credits a second (BED_SECONDS long, made loopable). The API key
needs the "sound generation" permission; without it the film is made
without beds and its report says so.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import requests

from core import costs
from core.errors import ExternalServiceError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR

log = get_logger(__name__)

FOLDER = CACHE_DIR / "ambience"
URL = "https://api.elevenlabs.io/v1/sound-generation"
BED_SECONDS = 20
# How far a bed sits under the voice. It was 15, and the fire's crackle
# was "loud and harsh" under the remade plague film (decision 089).
UNDER_DB = 24.0
CREST = 3.0                     # a bed's loudest moment, at most this many times its average
CROSSFADE = 1.5

# What a scene's direction must show for its chapter's bed to play under
# it (decision 089): the fire ran under street scenes, close faces and
# cards for minutes at a time, "inconsistent with what is on show".
FITS = {
    "interior_fire": r"(fire|hearth|oven|bakehouse|bakery|kitchen|forge|flames?|embers?|fireplace)",
    "street_quiet": r"(street|lane|alley|road|square|doorway|outside|town|village)",
    "street_busy": r"(street|lane|alley|road|square|crowd|cart|outside|town|bridge)",
    "market": r"(market|stall|crowd|square|trader|haggl\w*)",
    "night": r"(night|dark|moon\w*|midnight|stars?)",
    "rain": r"(rain\w*|storm|wet|downpour)",
    "bells": r"(bells?|church|steeple|tower|cathedral|street|town|rooftops?)",
    "countryside": r"(field|fields|meadow|countryside|farm|hill|hills|road|village|orchard)",
    "sea": r"(sea|ship|deck|waves?|harbour|harbor|ocean|boat|shore)",
    "battle": r"(battle\w*|cannon|musket\w*|soldiers?|army|trench\w*|siege)",
    "hall": r"(hall|court|chamber|crowd|room|church|theatre|tavern)",
    "workshop": r"(workshop|forge|anvil|bench|tools?|smith|mill|factory)",
}


def fits(key: str, direction: str) -> bool:
    """Whether a scene shows the place its chapter's bed is the sound of."""
    import re
    pattern = FITS.get(key)
    return bool(pattern and re.search(rf"\b{pattern}\b", direction or "", re.IGNORECASE))

SOUNDS = {
    "none": "",
    "interior_fire": "Inside a small old room: a wood fire crackling in a brick hearth, an occasional creak of timber, no voices, no music",
    "street_quiet": "An empty old town street at dawn: wind, a distant dog, a far-off church bell, no traffic, no voices, no music",
    "street_busy": "A busy old town street: footsteps on cobbles, distant voices, a cart's wooden wheels and a horse, no music",
    "market": "An open-air market: a murmuring crowd, haggling, hens, footsteps, no music",
    "night": "A quiet town at night: soft wind, crickets, a distant bell, no voices, no music",
    "rain": "Steady rain on roof tiles and cobbles, gutters running, no thunder, no music",
    "bells": "Church bells tolling slowly across a town a few streets away, wind, no music",
    "countryside": "Open countryside by day: birdsong, wind in long grass, distant sheep, no music",
    "sea": "A wooden ship at sea: creaking timbers, waves against the hull, wind in the rigging, no music",
    "battle": "A distant battle: cannon and musket fire rumbling far away, shouting very faint, no music",
    "hall": "A crowded indoor hall: murmured conversation, footsteps on wooden boards, no music",
    "workshop": "A busy workshop: hammering on metal and wood, tools set down, footsteps, no music",
}


def path_for(key: str) -> Path:
    return FOLDER / f"{key}.mp3"


def make(key: str) -> Path:
    """The bed for `key`, made once. Raises ExternalServiceError when the
    service won't (most often: the key lacks the permission)."""
    path = path_for(key)
    if path.exists():
        return path
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    response = requests.post(URL, timeout=180, headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                             json={"text": SOUNDS[key], "duration_seconds": BED_SECONDS, "prompt_influence": 0.4,
                                   "loop": True})
    if response.status_code != 200:
        missing = "sound_generation" in response.text
        raise ExternalServiceError(
            "The sound service (ElevenLabs)", f"sound-generation {response.status_code}: {response.text[:200]}",
            user_message=("The ElevenLabs key can't make sound effects: in ElevenLabs, Developers, API keys, "
                          "give it the Sound effects permission." if missing else
                          "ElevenLabs couldn't make a background sound."))
    FOLDER.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    costs.record_elevenlabs("ambience", "sound-generation", 0)
    log.info(f"  [ambience] made the {key} bed")
    return path


def bed(spans: list, fps: int, length: int, voice_rms: float) -> tuple:
    """(stereo samples `length` long, problem or ""): each (start, end,
    key) span filled with its bed, looped, the joins crossfaded, its
    loudness UNDER_DB below `voice_rms` (the narration's, while speaking)."""
    from pipeline.tts import decode_audio_file
    out = np.zeros((length, 2), dtype=np.float32)
    target = voice_rms * 10 ** (-UNDER_DB / 20)
    problem, loaded = "", {}
    for start, end, key in spans:
        if not SOUNDS.get(key):
            continue
        if key not in loaded:
            try:
                samples = decode_audio_file(str(make(key)), fps=fps).astype(np.float32)
            except ExternalServiceError as exc:
                problem = f"No background sound: {exc.user_message}"
                log.warning(f"  [ambience] {problem}")
                return out, problem
            if samples.ndim == 1:
                samples = np.repeat(samples[:, None], 2, axis=1)
            rms = float(np.sqrt((samples ** 2).mean()) or 1.0)
            samples = samples * (target / rms)
            peak = float(np.abs(samples).max() or 1.0)
            if peak > CREST * target:
                samples *= CREST * target / peak        # a crackle that cuts through is turned down
            loaded[key] = samples
        source = loaded[key]
        a, b = max(0, int((start - CROSSFADE / 2) * fps)), min(length, int((end + CROSSFADE / 2) * fps))
        if b <= a:
            continue
        reps = int(np.ceil((b - a) / len(source)))
        piece = np.tile(source, (reps, 1))[: b - a].copy()
        fade = min(int(CROSSFADE * fps), (b - a) // 2)
        if fade > 0:
            ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
            piece[:fade] *= ramp
            piece[-fade:] *= ramp[::-1]
        out[a:b] += piece
    return out, problem
