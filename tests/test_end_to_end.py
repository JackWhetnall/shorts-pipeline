"""
The whole pipeline, start to finish, with every paid service faked.

There was no test that ran `generate()` end to end, which is how a broken
response schema and an under-sized token budget both reached a real run.
Unit tests covered the pure functions on either side of those calls and
nothing covered the wiring between them.

Nothing here costs money. The Claude client is replaced with canned
responses, ElevenLabs is replaced with locally-synthesized silence, and
the footage comes from clips generated on disk by ffmpeg. The render is
real — that part has no API cost and is the step most likely to break
silently.

Also covers the hostile-input sweep across every route, because a 500 on
a mistyped query string is the same class of problem: an unhappy path
nobody exercised.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.slow


# --- fakes -------------------------------------------------------------

class FakeUsage:
    input_tokens = 100
    output_tokens = 200
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResponse:
    def __init__(self, payload):
        self.content = [FakeBlock(json.dumps(payload) if isinstance(payload, dict) else payload)]
        self.stop_reason = "end_turn"
        self.stop_details = None
        self.usage = FakeUsage()


SCRIPT_PAYLOAD = {
    "segments": [
        {"text": "The quiet moments matter more than we think.",
         "shot_brief": "a candle burning steadily in a dark room",
         "keywords": ["candle", "dark room"]},
        {"text": "Even a small pause changes how a sentence lands.",
         "shot_brief": "an empty road at dusk",
         "keywords": ["road", "dusk"]},
    ],
    "title_options": ["The Quiet Moments", "What A Pause Does", "Small Silences"],
    "description_body": "A short reflection on pauses.\n\n#reflection #quiet",
}


def make_clips(directory, count: int) -> list:
    """Real, tiny mp4s. ffmpeg's own test pattern — no download, no API."""
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    directory.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(count):
        path = directory / f"clip{i}.mp4"
        subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi",
             "-i", f"testsrc=size=1080x1920:rate=15:duration=3",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-loglevel", "error", str(path)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        made.append(path)
    return made


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A complete, isolated installation: config, output, footage library."""
    from core.channels import ChannelConfig, channel_to_sparse_dict, write_raw
    from pipeline.footage import store

    config_path = tmp_path / "channels.json"
    output_dir = tmp_path / "out"
    library_dir = tmp_path / "library"
    db_path = tmp_path / "library.db"

    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", config_path)
    monkeypatch.setattr("core.paths.OUTPUT_DIR", output_dir)
    monkeypatch.setattr("core.paths.LIBRARY_DIR", library_dir)
    monkeypatch.setattr("pipeline.footage.store.LIBRARY_DIR", library_dir)
    monkeypatch.setattr("pipeline.footage.store.LIBRARY_DB_PATH", db_path)
    monkeypatch.setattr("pipeline.footage.library.LIBRARY_DIR", library_dir)
    monkeypatch.setattr("core.paths.COST_LOG_PATH", tmp_path / "costs.jsonl")
    monkeypatch.setattr("core.costs.COST_LOG_PATH", tmp_path / "costs.jsonl")
    monkeypatch.setattr("core.paths.SCRIPT_HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr("pipeline.similarity.SCRIPT_HISTORY_PATH", tmp_path / "history.json")

    real_connect = store.connect
    monkeypatch.setattr(store, "connect", lambda p=None: real_connect(p or db_path))

    channel = ChannelConfig(
        key="t", channel_display_name="Test Channel", content_mode="topic",
        voice="voice-id", style_prompt="Write plainly.", topics=["quiet moments"])
    channel.output_dir = str(output_dir)
    channel.pacing.segment_count = 2
    channel.pacing.outro_seconds = 1.0
    channel.pacing.max_shot_seconds = 3.0
    write_raw({"t": channel_to_sparse_dict(channel)}, config_path)

    for i, path in enumerate(make_clips(library_dir, 6)):
        store.upsert(store.Clip(
            filename=path.name,
            description=f"a candle burning on an empty road at dusk, variation {i}",
            duration=3.0, frame_hashes=[i * 7, i * 11, i * 13]), db_path=db_path)

    return {"channel": channel, "output_dir": output_dir,
            "library_dir": library_dir, "tmp": tmp_path}


@pytest.fixture
def fake_services(monkeypatch, world):
    """Claude and ElevenLabs, replaced. Neither is contacted."""
    import numpy as np
    from pipeline import llm, tts
    from pipeline.plan import WordTiming

    clip_names = sorted(p.name for p in world["library_dir"].glob("*.mp4"))

    def fake_create(**kwargs):
        schema = (kwargs.get("output_config") or {}).get("format", {}).get("schema", {})
        properties = set((schema.get("properties") or {}).keys())
        if "picks" in properties:
            return FakeResponse({"picks": [
                {"segment_index": i,
                 "matches": [{"filename": n, "confidence": 9} for n in clip_names],
                 "search_queries": ["candle", "road"]}
                for i in range(2)]})
        return FakeResponse(SCRIPT_PAYLOAD)

    client = MagicMock()
    client.messages.create.side_effect = fake_create
    monkeypatch.setattr(llm, "client", lambda: client)

    def fake_segment(text, voice_id, out_path, speed=1.0, max_attempts=3):
        """Silence of a plausible length, with word timings to match."""
        words = text.split()
        per_word = 0.3
        timings = [WordTiming(w, i * per_word, i * per_word + 0.22)
                   for i, w in enumerate(words)]
        duration = max(0.5, len(words) * per_word)
        samples = np.zeros((int(duration * tts.SAMPLE_RATE), 2), dtype=np.float32)
        # The real function writes this file; the stitcher deletes it.
        from moviepy.audio.AudioClip import AudioArrayClip
        clip = AudioArrayClip(samples, fps=tts.SAMPLE_RATE)
        clip.write_audiofile(str(out_path), codec="libmp3lame", logger=None)
        clip.close()
        return timings, samples, tts.SAMPLE_RATE

    monkeypatch.setattr(tts, "synthesize_segment", fake_segment)
    return client


# --- the whole thing ---------------------------------------------------

class TestFullGeneration:
    """One render, every assertion.

    Deliberately not split into a test per assertion: each render is a
    real 1080x1920 encode, and six of them turned this file into an
    eight-minute run for no extra coverage. The degraded cases below get
    their own renders because they genuinely need different setups.
    """

    @pytest.fixture
    def rendered(self, world, fake_services):
        from pipeline.plan import Seed
        from pipeline.run import generate
        return generate(world["channel"], Seed(type="topic", topic="quiet moments"),
                        interactive=False)

    def test_the_happy_path_produces_everything_it_should(self, rendered, world):
        from moviepy.editor import VideoFileClip
        from core import gallery

        plan = rendered

        # The video itself.
        assert plan.video_path.exists(), "no video file"
        assert plan.video_path.stat().st_size > 10_000

        # Every sidecar the rest of the app reads.
        for suffix in ("_meta.txt", "_description.txt", "_cost.json",
                       "_publish.json", "_report.json"):
            assert (plan.out_dir / f"{plan.stem}{suffix}").exists(), f"missing {suffix}"

        # Shape and duration.
        clip = VideoFileClip(str(plan.video_path))
        try:
            assert (clip.w, clip.h) == (1080, 1920)
            assert clip.audio is not None, "audio was not muxed in"
            expected = plan.voiceover.duration + world["channel"].pacing.outro_seconds
            assert clip.duration == pytest.approx(expected, abs=0.4)
        finally:
            clip.close()

        # Title and description, generated and stored rather than retyped.
        info = gallery.load_publish_info(plan.video_path)
        assert info["title"] == "The Quiet Moments"
        assert "#reflection" in info["description"]

        # Quality signals recorded beside the video, not just logged.
        report = gallery.load_report(plan.video_path)
        assert report["footage_repeated"] is False
        assert report["footage_degraded"] is False
        assert report["shot_count"] == len(plan.shots)
        assert len(set(report["clips"])) == len(report["clips"]), "clips must be distinct"

        # Cost attributed to this specific video.
        cost = gallery.load_cost_summary(plan.video_path)
        assert cost["calls"] >= 2, "script and footage match should both be logged"

        # Shot briefs recorded, so a poor match is traceable to its brief.
        meta = plan.meta_path.read_text(encoding="utf-8")
        assert "shot:" in meta
        assert "candle burning" in meta


class TestFullGenerationDegraded:
    """The unhappy paths, end to end. Each one must still produce a video."""

    def test_a_failed_footage_match_still_renders(self, world, fake_services, monkeypatch):
        from pipeline import llm
        from pipeline.footage import library
        from pipeline.plan import Seed
        from pipeline.run import generate

        real_call = library.llm.call_json

        def fail_only_matching(*args, **kwargs):
            if kwargs.get("operation") == "footage_match":
                raise llm.TruncatedResponse("cut short")
            return real_call(*args, **kwargs)

        monkeypatch.setattr(library.llm, "call_json", fail_only_matching)

        plan = generate(world["channel"], Seed(type="topic", topic="quiet moments"),
                        interactive=False)

        assert plan.video_path.exists(), "the render must survive a scoring failure"
        assert plan.footage_degraded is True, "and must say it was degraded"

    def test_a_missing_clip_file_still_renders(self, world, fake_services, monkeypatch):
        """A row whose file has gone must not be discovered inside the
        encode, a minute in."""
        from pipeline import assemble
        from pipeline.plan import Seed
        from pipeline.run import generate

        real_replace = assemble._replace_missing_clips
        deleted = {"done": False}

        def delete_one_then_replace(plan):
            if not deleted["done"] and plan.shots:
                plan.shots[0].clip_path.unlink(missing_ok=True)
                deleted["done"] = True
            return real_replace(plan)

        monkeypatch.setattr(assemble, "_replace_missing_clips", delete_one_then_replace)

        plan = generate(world["channel"], Seed(type="topic", topic="quiet moments"),
                        interactive=False)
        assert plan.video_path.exists()
        assert plan.footage_degraded is True

    def test_no_transcript_check_still_renders(self, world, fake_services, monkeypatch):
        from pipeline import tts
        from pipeline.plan import Seed
        from pipeline.run import generate

        monkeypatch.setattr(tts, "_get_whisper", lambda: None)
        plan = generate(world["channel"], Seed(type="topic", topic="quiet moments"),
                        interactive=False)
        assert plan.video_path.exists()


# --- hostile input across every route ---------------------------------

class TestNoRouteReturnsFiveHundred:
    """A mistyped query string is the same class of problem as an
    unhandled API response: an unhappy path nobody exercised."""

    JUNK = ["", "notanumber", "-1", "1e999", "nan", "../../etc/passwd",
            "<script>alert(1)</script>", "'; DROP TABLE clips;--", "x" * 1500]

    @pytest.fixture
    def client(self, world, monkeypatch):
        from web import create_app
        app = create_app()
        app.config.update(TESTING=True)
        with app.test_client() as c:
            yield c

    def test_every_get_route_survives_junk_arguments(self, client):
        from web import create_app
        app = create_app()

        failures = []
        for rule in app.url_map.iter_rules():
            if "GET" not in rule.methods or rule.endpoint == "static":
                continue
            for junk in self.JUNK:
                path = rule.rule
                for arg in rule.arguments:
                    path = path.replace(f"<{arg}>", junk or "x")
                    path = path.replace(f"<path:{arg}>", junk or "x")
                if "<" in path:
                    continue
                response = client.get(f"{path}?page={junk}&q={junk}&show={junk}")
                if response.status_code >= 500:
                    failures.append((path, junk, response.status_code))

        assert not failures, f"routes returned 500 on junk input: {failures[:5]}"

    def test_api_errors_are_json_not_html(self, client):
        response = client.get("/api/jobs/does-not-exist")
        assert response.status_code == 404
        assert response.is_json

    def test_numeric_parsing_never_raises(self):
        from web.helpers import as_float, as_int
        for junk in self.JUNK + [None, {}, [], float("inf"), float("nan")]:
            assert isinstance(as_int(junk, 1, minimum=1), int)
            assert isinstance(as_float(junk, 1.0, minimum=0.1), float)
