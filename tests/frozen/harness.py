"""
The frozen channels' fingerprints (decision 075).

Minute Pastor and Pub Quiz Buzz are kept exactly as they are while the
project moves to long-form, but most of the code they run (writing,
voice, rendering, publishing) is shared with what's being built. So this
runs each one's real pipeline, `pipeline.run.generate`, end to end, with
every outside service replaced by a recorder, and reduces what came out
to a fingerprint:

- every request to Claude and to ElevenLabs, word for word;
- the footage it chose and the quiz board it filmed;
- frames of the finished picture and a hash of its sound;
- the files written beside the video;
- the settings it resolves to, and its publishing slots.

`test_frozen_channels.py` compares that with the golden copy in
`golden/`. A difference means a change to shared code has changed one of
the frozen channels' videos. Either the change is made additive (behind
a default those channels keep), or the owner agrees to the change and
the goldens are written again with `python -m tests.frozen.regenerate`.

The channels' settings are the snapshot in `channels.json`, taken when
the channels were frozen, not the live config/channels.json: what's
pinned is the code's behaviour, and the owner stays free to change a
setting in the app. Nothing is read from or written to the installation's
own data (config, channels, cache, output, footage, facts, music): its
paths are redirected to a temporary folder, and an audit hook records any
access that slips through, which fails the check.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import importlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
GOLDEN_DIR = HERE / "golden"
CHANNELS = json.loads((HERE / "channels.json").read_text(encoding="utf-8"))
FROZEN = tuple(CHANNELS)

PROJECT_ROOT = HERE.parent.parent
DATA_DIRS = {"output", "footage", "channels", "cache", "job_state", "deleted_channels",
             "config", "facts", "music", "backups"}

# The modules a frozen channel's run reaches, imported before their data
# paths are redirected (a module imported later would keep the real ones).
MODULES = (
    "core.paths", "core.channels", "core.curriculum", "core.gallery", "core.costs", "core.backgrounds",
    "core.assets", "core.publish_queue", "core.publish_gate", "core.job_context", "core.money",
    "pipeline.run", "pipeline.script_gen", "pipeline.tts", "pipeline.visuals", "pipeline.assemble",
    "pipeline.sound", "pipeline.quiz", "pipeline.description", "pipeline.editor_check",
    "pipeline.similarity", "pipeline.llm", "pipeline.footage.store", "pipeline.footage.library",
    "pipeline.footage.retrieval", "pipeline.footage.sources", "pipeline.scenes.render",
    "pipeline.scenes.art", "pipeline.templates.page", "pipeline.templates.theme",
    "pipeline.facts.store", "pipeline.facts.rounds", "pipeline.facts.bank", "pipeline.pictures",
)

SECONDS_PER_CHARACTER = 0.065
SLOTS_AFTER = datetime(2026, 10, 7, 9, 0)

MP_SEED = {"type": "quote", "reference": "Psalms 46:10",
           "text": "Be still, and know that I am God: I will be exalted among the heathen, "
                   "I will be exalted in the earth."}

PQB_DIFFICULTY = "Hard"
PQB_ROUNDS = {
    "Science": [
        ("What is the chemical symbol for tungsten?", "W"),
        ("Which planet has the shortest day in the solar system?", "Jupiter"),
        ("What is the hardest natural substance on the Mohs scale?", "Diamond"),
        ("Which gas makes up about 78 percent of Earth's atmosphere?", "Nitrogen"),
        ("What is the powerhouse of the cell?", "The mitochondrion"),
        ("How many bones are in the adult human body?", "206"),
        ("What is the SI unit of electrical resistance?", "The ohm"),
        ("Which element has the atomic number 1?", "Hydrogen"),
        ("What type of rock is formed from cooled lava?", "Igneous"),
        ("Who proposed the theory of general relativity?", "Albert Einstein"),
    ],
    "Geography": [
        ("What is the capital of Australia?", "Canberra"),
        ("Which river flows through Baghdad?", "The Tigris"),
        ("What is the largest desert in Asia?", "The Gobi"),
        ("Which country has the most natural lakes?", "Canada"),
        ("What is the smallest country in South America by area?", "Suriname"),
        ("Which strait separates Spain from Morocco?", "The Strait of Gibraltar"),
        ("What is the highest mountain in Africa?", "Kilimanjaro"),
        ("Which US state has the longest coastline?", "Alaska"),
        ("What is the capital of Mongolia?", "Ulaanbaatar"),
        ("Which sea lies between Italy and the Balkans?", "The Adriatic"),
    ],
}
# The short whose own fingerprint is kept; the others exist to be recut.
PQB_SHORT = "Science"

CLIPS = [
    ("still lake at dawn with mist over the water", "lake", "mountains"),
    ("person sitting quietly on a wooden bench in a park", "person on bench", "park"),
    ("candle flame flickering in a dark room", "candle", "room"),
    ("waves rolling onto an empty beach at sunset", "waves", "beach"),
    ("sunlight through tall forest trees", "forest", "woodland"),
    ("hands folded resting on a table by a window", "hands", "kitchen"),
    ("clouds drifting slowly across a blue sky", "clouds", "sky"),
    ("open road through green hills", "road", "countryside"),
    ("birds flying over a calm river", "birds", "river"),
    ("old stone church on a hill at golden hour", "church", "hillside"),
    ("rain drops running down a window pane", "rain", "window"),
    ("night sky full of stars over a desert", "stars", "desert"),
]


# --- the recorder ---------------------------------------------------------------------

@dataclasses.dataclass
class Recorder:
    tmp: Path
    llm: list = dataclasses.field(default_factory=list)
    voice: list = dataclasses.field(default_factory=list)
    shots: list = dataclasses.field(default_factory=list)
    board: list = dataclasses.field(default_factory=list)
    video: list = dataclasses.field(default_factory=list)
    audio: list = dataclasses.field(default_factory=list)
    mix: list = dataclasses.field(default_factory=list)
    frame_check: list = dataclasses.field(default_factory=list)
    thumbnail: list = dataclasses.field(default_factory=list)
    stray: list = dataclasses.field(default_factory=list)
    op: str = ""

    KEPT = ("llm", "voice", "shots", "board", "video", "audio", "mix", "frame_check", "thumbnail")

    def take(self) -> dict:
        """What's been recorded since the last take, and a clean slate."""
        taken = {name: getattr(self, name) for name in self.KEPT}
        for name in self.KEPT:
            setattr(self, name, [])
        return taken


class _Usage:
    input_tokens = 1000
    output_tokens = 500
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    stop_reason = "end_turn"
    stop_details = None
    usage = _Usage()

    def __init__(self, payload):
        self.content = [_Block(json.dumps(payload))]


class _VoiceResponse:
    status_code = 200
    ok = True

    def __init__(self, data: dict, characters: int):
        self._data = data
        self.headers = {"x-character-count": str(characters)}

    def json(self):
        return self._data


# --- answers ----------------------------------------------------------------------------

def _filled(schema: dict):
    """The smallest answer a schema accepts: no problems found, nothing to add."""
    kind = schema.get("type")
    if kind == "object":
        return {k: _filled(schema["properties"][k]) for k in schema.get("required", [])}
    if kind == "array":
        return []
    if "enum" in schema:
        return schema["enum"][0]
    return {"string": "", "integer": 0, "number": 0, "boolean": False}.get(kind)


def _mp_script(channel) -> dict:
    lines = [
        ("Stillness can feel like losing, when every voice says keep moving.",
         "a person sitting alone on a bench as the city rushes past", ["bench", "city"]),
        ("This line was first sung by people whose city was surrounded, not people with time to spare.",
         "an old stone wall at dusk", ["stone wall", "dusk"]),
        ("Be still is not a suggestion to relax. It is permission to stop carrying what was never yours.",
         "hands opening and letting go of a small stone", ["hands", "stone"]),
        ("Maybe today the bravest thing is to sit down, breathe, and let the noise be noise.",
         "mist lifting off a calm lake at sunrise", ["lake", "sunrise"]),
    ][:channel.pacing.segment_count]
    return {
        "hook": "What if the hardest thing you do today is stop?",
        "hook_shot_brief": "a busy street slowing to a stop",
        "hook_keywords": ["street", "slow motion"],
        "quote_shot_brief": "still water reflecting a quiet sky",
        "quote_keywords": ["still water", "sky"],
        "segments": [{"text": t, "shot_brief": b, "keywords": k} for t, b, k in lines],
        "title_options": ["Permission to Stop", "Be Still, Even Now", "The Bravest Thing Today"],
        "description_body": "A short reflection on Psalm 46:10.\n\n#bible #reflection #faith",
        "hook_promise": "why stopping can be brave",
        "payoff": "stillness as letting go",
        "screen_hook": "Stopping is allowed",
        "emphasis": ["still", "permission", "breathe"],
    }


def _user_text(request: dict) -> str:
    content = request["messages"][0]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content if isinstance(block, dict))


def _pqb_lines(request: dict) -> dict:
    answers = re.findall(r"^\d+\. .*? Answer: (.*?)\.(?: Note: .*)?$", _user_text(request), re.M)
    leads = ["", "Question two.", "Number three.", "Question four.", "Halfway there, question five.",
             "Question six.", "Number seven.", "Question eight.", "Nearly there, question nine.",
             "Last one, question ten."]
    return {
        "hook": "Ten questions. Bet you can't get seven.",
        "intro": "Tonight's round is a hard one. Here's question one.",
        "questions": [{"number": i + 1, "lead_in": leads[i % len(leads)], "spoken_answer": f"{a}. It's {a}."}
                      for i, a in enumerate(answers)],
        "outro": "How many did you get? Tell me in the comments.",
        "title_options": ["Hard Quiz: Can You Get 7/10?"],
        "description_body": "Ten hard questions. Pause if you need longer.",
    }


def _long_links() -> dict:
    rounds = len(PQB_ROUNDS)
    return {
        "welcome": "Welcome to quiz night. Grab a pen, it's a hard one.",
        "round_intros": [f"On to round {i + 2}." for i in range(rounds - 1)],
        "finish_lines": [f"That's round {i + 1} done." for i in range(rounds)],
        "answers_intros": [f"Answers to round {i + 1}." for i in range(rounds)],
        "signoff": "That's the night. Same time next week.",
        "title_options": ["Twenty Hard Questions"],
        "description": "A hard pub quiz night, two rounds.",
        "thumbnail_line": "Can you get 15?",
    }


def _footage_picks(request: dict) -> dict:
    text = json.dumps([request.get("system"), request.get("messages")])
    names = sorted(set(re.findall(r"frozen_clip_\d+\.mp4", text)))
    picks = []
    for i in range(12):
        ordered = names[i % max(1, len(names)):] + names[:i % max(1, len(names))]
        picks.append({"segment_index": i,
                      "matches": [{"filename": n, "confidence": 9 - min(3, j)} for j, n in enumerate(ordered)],
                      "search_queries": ["quiet", "calm"]})
    return {"picks": picks}


def _answer(op: str, request: dict, channel) -> dict:
    if op == "script":
        return _mp_script(channel)
    if op == "quiz_write":
        return _pqb_lines(request)
    if op == "longform_links":
        return _long_links()
    if op == "footage_match":
        return _footage_picks(request)
    schema = ((request.get("output_config") or {}).get("format") or {}).get("schema")
    return _filled(schema) if schema else {}


# --- sound and picture placeholders ----------------------------------------------------------

def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list) -> None:
    subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class Media:
    """Files the fakes hand back, made once per run with ffmpeg."""

    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self._tones = {}

    def tone(self, seconds: float) -> bytes:
        """A voiced line: a steady tone of exactly this length, as mp3."""
        seconds = round(seconds, 2)
        if seconds not in self._tones:
            path = self.folder / f"tone_{seconds:.2f}.mp3"
            _run(["-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=44100:duration={seconds}",
                  "-ac", "1", "-b:a", "64k", str(path)])
            self._tones[seconds] = path.read_bytes()
        return self._tones[seconds]

    def music(self) -> Path:
        path = self.folder / "music.mp3"
        if not path.exists():
            _run(["-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=200",
                  "-ac", "2", "-b:a", "96k", str(path)])
        return path

    def background(self) -> Path:
        """A full-frame, flat, long, nearly empty video to stand in for footage."""
        path = self.folder / "background.mp4"
        if not path.exists():
            _run(["-f", "lavfi", "-i", "color=c=0x334455:size=1080x1920:rate=1:duration=400",
                  "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)])
        return path

    def jpeg(self) -> str:
        from PIL import Image
        rng = np.random.default_rng(11)
        image = Image.fromarray(rng.integers(0, 255, (192, 108, 3), dtype=np.uint8))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=80)
        return base64.b64encode(out.getvalue()).decode()


# --- isolation --------------------------------------------------------------------------

_AUDIT = {"on": False, "stray": None}


def _audit(event: str, args) -> None:
    if not _AUDIT["on"] or event not in ("open", "os.listdir", "os.scandir", "os.remove", "os.rename"):
        return
    target = args[0] if args else None
    if not isinstance(target, (str, bytes, os.PathLike)):
        return
    try:
        path = Path(os.fsdecode(target)).resolve()
        relative = path.relative_to(PROJECT_ROOT)
    except (ValueError, OSError):
        return
    if relative.parts and relative.parts[0] in DATA_DIRS:
        # Refused, not only noted: a frozen run must never write into the
        # owner's real output or config (a slip once put a test video in
        # Minute Pastor's output folder). Noted as well, in case the
        # refusal is swallowed by best-effort code.
        _AUDIT["stray"].append(f"{event} {relative.as_posix()}")
        raise PermissionError(f"frozen run touched the installation's own data: {relative.as_posix()}")


sys.addaudithook(_audit)


def _redirect_data(monkeypatch, root: Path) -> None:
    """Every module-level path into the installation's data, pointed at `root` instead."""
    for name in MODULES:
        importlib.import_module(name)
    for name, module in list(sys.modules.items()):
        if not name.startswith(("core.", "pipeline.", "web.")) or module is None:
            continue
        for attr, value in list(vars(module).items()):
            if not isinstance(value, Path) or attr.startswith("__"):
                continue
            try:
                relative = value.resolve().relative_to(PROJECT_ROOT)
            except (ValueError, OSError):
                continue
            if relative.parts and relative.parts[0] in DATA_DIRS:
                monkeypatch.setattr(module, attr, root / relative)


# --- the fakes, installed ---------------------------------------------------------------------

def _scrub(value):
    """A request as recorded: pictures reduced to a hash of their bytes."""
    if isinstance(value, dict):
        if value.get("type") == "base64" and "data" in value:
            return {**value, "data": "sha1:" + hashlib.sha1(value["data"].encode()).hexdigest()[:16]}
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _install(monkeypatch, rec: Recorder, media: Media, channel) -> None:
    from moviepy.audio.AudioClip import AudioClip
    from moviepy.video.VideoClip import VideoClip
    from pipeline import editor_check, llm, sound, tts
    from pipeline.footage import sources
    from pipeline.scenes import render

    for key in ("ELEVENLABS_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "frozen")

    # Claude: every request recorded, answered by operation.
    real_call = llm._call

    def recording(request, operation, model):
        rec.op = operation
        rec.llm.append({"operation": operation, **_scrub(request)})
        return real_call(request, operation, model)

    client = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **request: _Response(_answer(rec.op, request, channel))))
    monkeypatch.setattr(llm, "_call", recording)
    monkeypatch.setattr(llm, "client", lambda: client)

    # ElevenLabs: every request recorded; a tone as long as the text, and
    # character timings to match.
    def post(voice_id, payload):
        rec.voice.append({"voice": voice_id, **payload})
        text = payload["text"]
        starts = [round(i * SECONDS_PER_CHARACTER, 4) for i in range(len(text))]
        ends = [round((i + 1) * SECONDS_PER_CHARACTER, 4) for i in range(len(text))]
        audio = media.tone(len(text) * SECONDS_PER_CHARACTER + 0.1)
        return _VoiceResponse({"audio_base64": base64.b64encode(audio).decode(),
                               "alignment": {"characters": list(text),
                                             "character_start_times_seconds": starts,
                                             "character_end_times_seconds": ends}}, len(text))
    monkeypatch.setattr(tts, "_post_with_backoff", post)
    monkeypatch.setattr(tts, "_get_whisper", lambda: None)

    # Footage: never fetched; the background track recorded rather than cut.
    monkeypatch.setattr(sources, "any_key_configured", lambda: False)

    def background(shots, crossfade, out_path):
        rec.shots.append({"crossfade": crossfade, "shots": [
            {"segment": s.segment_index, "start": round(s.start, 3), "end": round(s.end, 3),
             "scene": bool(s.scene), "clip": Path(s.clip_path).name if s.clip_path else None}
            for s in shots]})
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(media.background(), out_path)
        return Path(out_path)
    from pipeline import assemble
    monkeypatch.setattr(assemble, "build_background_track", background)

    # The quiz board: its page recorded rather than filmed.
    def page(html, duration, out_path, fps=30, size=None):
        normal = html.replace(str(rec.tmp), "<tmp>").replace(str(rec.tmp).replace("\\", "/"), "<tmp>")
        (rec.tmp / "board.html").write_text(normal, encoding="utf-8")
        rec.board.append({"sha1": hashlib.sha1(normal.encode("utf-8")).hexdigest(),
                          "characters": len(normal), "seconds": round(duration, 3), "fps": fps,
                          "size": list(size) if size else None})
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(media.background(), out_path)
        return Path(out_path)
    monkeypatch.setattr(render, "render_page", page)

    def still(html, t, out_path=None, size=None):
        normal = html.replace(str(rec.tmp), "<tmp>").replace(str(rec.tmp).replace("\\", "/"), "<tmp>")
        rec.thumbnail.append({"sha1": hashlib.sha1(normal.encode("utf-8")).hexdigest(),
                              "t": t, "size": list(size) if size else None})
        data = base64.b64decode(media.jpeg())
        if out_path:
            Path(out_path).write_bytes(data)
        return data
    monkeypatch.setattr(render, "page_frame", still)

    # The encode: settings recorded and frames sampled, nothing written
    # but a placeholder.
    def write_video(clip, filename, **kwargs):
        d = float(clip.duration)
        times = [0.5, d * 0.25, d * 0.5, d * 0.75, max(0.0, d - 0.5)]
        frames = []
        for i, t in enumerate(times):
            frame = np.ascontiguousarray(clip.get_frame(t), dtype=np.uint8)
            frames.append(hashlib.sha1(frame.tobytes()).hexdigest()[:16])
            from PIL import Image
            Image.fromarray(frame).save(rec.tmp / f"frame_{len(rec.video)}_{i}.png")
        rec.video.append({"seconds": round(d, 3), "fps": kwargs.get("fps"), "codec": kwargs.get("codec"),
                          "preset": kwargs.get("preset"), "audio": kwargs.get("audio"),
                          "size": list(clip.size), "frames_at": [round(t, 3) for t in times],
                          "frames": frames})
        shutil.copyfile(media.background(), filename)

    def write_audio(clip, filename, fps=None, codec=None, **kwargs):
        entry = {"seconds": round(float(clip.duration), 3), "fps": fps, "codec": codec}
        samples = getattr(clip, "array", None)
        if samples is not None:
            quantised = np.round(np.asarray(samples, dtype=np.float64) * 32767).astype(np.int32)
            entry["sha1"] = hashlib.sha1(quantised.tobytes()).hexdigest()[:16]
        rec.audio.append(entry)
        if samples is None or not str(filename).endswith(".mp3"):
            Path(filename).write_bytes(b"frozen")       # only ever muxed, and the mux is faked
            return
        # A short's narration is read back when its round goes into a long
        # quiz, so it's real audio: encoded in one go rather than moviepy's
        # chunk by chunk, which took most of a minute here.
        pcm = np.ascontiguousarray(np.asarray(samples, dtype=np.float32))
        subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(fps or 44100),
                        "-ac", str(pcm.shape[1] if pcm.ndim > 1 else 1), "-i", "-", "-b:a", "64k", str(filename)],
                       input=pcm.tobytes(), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def merge(video, audio, output, vcodec="copy", acodec="copy", **kwargs):
        shutil.copyfile(video, output)

    monkeypatch.setattr(VideoClip, "write_videofile", write_video)
    monkeypatch.setattr(AudioClip, "write_audiofile", write_audio)
    monkeypatch.setattr("moviepy.video.io.ffmpeg_tools.ffmpeg_merge_video_audio", merge)

    # The sound: its own music, and the mix recorded.
    monkeypatch.setattr(sound, "music_tracks", lambda key: [media.music()])
    real_mix = sound.mix

    def mix(voice, fps, channel_, plan, to_track_time):
        out = real_mix(voice, fps, channel_, plan, to_track_time)
        quantised = np.round(np.asarray(out, dtype=np.float64) * 32767).astype(np.int32)
        rec.mix.append({"samples": int(out.shape[0]), "channels": int(out.shape[1]) if out.ndim > 1 else 1,
                        "fps": fps, "peak": round(float(np.max(np.abs(out))), 4),
                        "rms": round(float(np.sqrt(np.mean(np.square(out, dtype=np.float64)))), 5),
                        "sha1": hashlib.sha1(quantised.tobytes()).hexdigest()[:16]})
        return out
    monkeypatch.setattr(sound, "mix", mix)

    # The picture check: which moments it looks at.
    def frames_at(video_path, times):
        rec.frame_check.append([round(float(t), 3) for t in times])
        return [media.jpeg() for _ in times]
    monkeypatch.setattr(editor_check, "_frames_at", frames_at)


# --- the worlds -------------------------------------------------------------------------------

def _library(monkeypatch) -> None:
    from core import paths
    from pipeline.footage import store
    rng = random.Random(5)
    for i, (description, subject, setting) in enumerate(CLIPS):
        name = f"frozen_clip_{i:02d}.mp4"
        paths.LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        (paths.LIBRARY_DIR / name).write_bytes(b"frozen")
        store.upsert(store.Clip(filename=name, description=description, duration=12.0,
                                source="pexels", subject=subject, setting=setting, motion="slow",
                                palette="natural", time_of_day="day",
                                frame_hashes=[rng.getrandbits(63) for _ in range(3)]))


def _quiz_world(monkeypatch, channel) -> dict:
    """Pub Quiz Buzz's plan with a category per round in PQB_ROUNDS at one
    level, each with its round made ahead (decision 062): ten questions
    from the bank. Returns {category: seed}."""
    from core import curriculum
    from pipeline.facts import bank, rounds
    from pipeline.plan import Seed
    categories = list(PQB_ROUNDS)
    curriculum.start(channel.key, "Pub quiz", [
        {"title": c, "summary": f"{c} questions", "level": "foundation", "target_subtopics": 1}
        for c in categories])
    for i, category in enumerate(categories):
        curriculum.add_subtopics(channel.key, f"u{i + 1:02d}", [
            {"title": f"{category}: {PQB_DIFFICULTY}", "angle": PQB_DIFFICULTY}])
    bank_rows = {c: [{"question": q, "answer": a, "note": "", "bank_id": 100 * i + n + 1, "source": "bank"}
                     for n, (q, a) in enumerate(PQB_ROUNDS[c])] for i, c in enumerate(categories)}
    monkeypatch.setattr(rounds, "claim", lambda conn, key, category, difficulty, claim_for:
                        {"id": categories.index(category) + 1, "category": category,
                         "questions": json.dumps([q["bank_id"] for q in bank_rows[category]])})
    monkeypatch.setattr(rounds, "questions_of", lambda conn, row: [dict(q) for q in bank_rows[row["category"]]])
    monkeypatch.setattr(rounds, "used", lambda conn, round_id: None)
    monkeypatch.setattr(rounds, "assemble", lambda conn, channel_: None)
    monkeypatch.setattr(bank, "mark_used", lambda conn, key, ids, label: None)
    entries = {e["title"].split(":")[0]: e for e in curriculum.subtopics(channel.key)}
    return {c: Seed(type="topic", topic=entries[c]["title"], topic_id=entries[c]["id"]) for c in categories}


# --- normalising ------------------------------------------------------------------------------

_TODAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _normal(value, tmp: Path):
    if isinstance(value, dict):
        return {k: _normal(v, tmp) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normal(v, tmp) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        for form in (str(tmp), str(tmp).replace("\\", "/"), str(tmp).replace("\\", "\\\\")):
            value = value.replace(form, "<tmp>")
        return _TODAY.sub("<date>", value)
    return value


def _plain(value):
    if dataclasses.is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


VOLATILE = {"created_at", "updated_at", "at", "ts", "made_at", "started_at", "finished_at", "queued_at",
            "generated_at", "duration_seconds", "job_id", "elapsed"}


def _without_volatile(value):
    if isinstance(value, dict):
        return {k: _without_volatile(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_without_volatile(v) for v in value]
    return value


def _sidecars(folder: Path, stem: str, stems: tuple = ()) -> dict:
    """The files written beside one video. `stems`: every video in the
    folder, so a longer name that starts with this one (a long quiz's
    answers-at-the-end variant) is left to its own entry."""
    longer = [other for other in stems if other != stem and other.startswith(stem)]
    out = {}
    for path in sorted(folder.glob(f"{stem}*")):
        suffix = path.name[len(stem):]
        if suffix and not suffix.startswith(("_", ".")):
            continue                    # another video whose name starts the same way
        if any(path.name.startswith(other) for other in longer):
            continue
        if path.suffix == ".json":
            try:
                out[suffix] = _without_volatile(json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                out[suffix] = "unreadable"
        elif path.suffix == ".txt":
            out[suffix] = path.read_text(encoding="utf-8")
        elif path.is_file():
            out[suffix] = "file"
    return out


# --- the fingerprint ----------------------------------------------------------------------------

def fingerprint(key: str, tmp: Path, monkeypatch) -> dict:
    """Run the frozen channel `key`'s pipeline with everything outside
    recorded, and return what came out, normalised."""
    from core.channels import channel_from_dict

    random.seed(0)
    np.random.seed(0)
    tmp = Path(tmp)
    _redirect_data(monkeypatch, tmp / "data")
    media = Media(tmp / "media")
    media.background(), media.music()            # made before the audit starts
    rec = Recorder(tmp=tmp)

    channel = channel_from_dict(key, json.loads(json.dumps(CHANNELS[key])))
    result = {"config": _plain(channel)}
    from core import publish_queue
    result["slots"] = [t.strftime("%a %H:%M") for t in
                       publish_queue.upcoming_slots(channel.publishing, SLOTS_AFTER.astimezone(), 8)]

    channel.output_dir = str(tmp / "data" / "output" / key)
    _install(monkeypatch, rec, media, channel)
    _library(monkeypatch)
    from pipeline.plan import Seed
    from pipeline.run import generate

    _AUDIT.update(on=True, stray=rec.stray)
    try:
        if channel.format != "quiz":
            plan = generate(channel, Seed(**MP_SEED), interactive=False)
            result["short"] = _short(rec, plan)
        else:
            result.update(_quiz(rec, channel, monkeypatch))
    finally:
        _AUDIT["on"] = False
    result["touched_real_data"] = sorted(set(rec.stray))
    return _normal(result, tmp)


def _short(rec: Recorder, plan) -> dict:
    taken = rec.take()
    return {
        "claude": taken["llm"],
        "voice": taken["voice"],
        "footage": taken["shots"],
        "board": taken["board"],
        "video": taken["video"],
        "audio": taken["audio"],
        "mix": taken["mix"],
        "frame_check": taken["frame_check"],
        "segments": [{"text": s.text, "start": s.start, "end": s.end, "pause_after": s.pause_after}
                     for s in plan.script.segments],
        "video_seconds": getattr(plan, "video_seconds", None),
        "title_card_at": getattr(plan, "title_card_at", None),
        "files": _sidecars(Path(plan.out_dir), plan.stem),
    }


def _quiz(rec: Recorder, channel, monkeypatch) -> dict:
    """A short per category (the first one's fingerprint kept), each
    approved, then the long quiz they make (decisions 044, 066)."""
    from core import gallery
    from pipeline import longform
    from pipeline.run import generate
    seeds = _quiz_world(monkeypatch, channel)
    out = {}
    for category, seed in seeds.items():
        plan = generate(channel, seed, interactive=False)
        made = _short(rec, plan)
        if category == PQB_SHORT:
            out["short"] = made
        gallery.save_queue_state(plan.video_path, queued_at="2026-10-07T00:00:00+00:00", approved_by="you")
    out["long_ready"] = longform.availability(channel)
    made = longform.make(channel, {"type": "longform", "difficulty": PQB_DIFFICULTY, "rounds": len(seeds)})
    taken = rec.take()
    folder = Path(made.video_path).parent
    stems = tuple(sorted(path.stem for path in folder.glob("*.mp4")))
    out["long"] = {
        "claude": taken["llm"], "voice": taken["voice"], "board": taken["board"], "audio": taken["audio"],
        "thumbnail": taken["thumbnail"],
        "files": {stem: _sidecars(folder, stem, stems) for stem in stems},
    }
    return out


def golden_path(key: str) -> Path:
    return GOLDEN_DIR / f"{key}.json"


def read_golden(key: str) -> dict:
    return json.loads(golden_path(key).read_text(encoding="utf-8"))


def write_golden(key: str, data: dict) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    golden_path(key).write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                                encoding="utf-8")


def differences(expected, actual, where: str = "", limit: int = 25, allow_new: tuple = ()) -> list:
    """Where two fingerprints differ, as readable lines, most specific path first.

    `allow_new`: paths under which a key that's new is not a difference.
    The frozen check passes ("/config",): a setting added with a default
    changes nothing by being there; if anything reads it differently for a
    frozen channel, that shows in the rest of the fingerprint."""
    out = []

    def walk(a, b, path):
        if len(out) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a:
                    if not any(f"{path}/{k}".startswith(prefix) for prefix in allow_new):
                        out.append(f"{path}/{k}: new -> {_brief(b[k])}")
                elif k not in b:
                    out.append(f"{path}/{k}: gone (was {_brief(a[k])})")
                else:
                    walk(a[k], b[k], f"{path}/{k}")
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                out.append(f"{path}: {len(a)} items -> {len(b)}")
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f"{path}[{i}]")
        elif a != b:
            out.append(f"{path}: {_brief(a)} -> {_brief(b)}")

    walk(expected, actual, where)
    return out


def _brief(value, n: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    return text if len(text) <= n else text[:n] + "..."
