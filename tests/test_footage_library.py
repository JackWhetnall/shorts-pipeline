"""
The footage library: schema migration, ranking, diversity, enrichment and
compaction.

No API calls and no encoding except where a test says so explicitly. The
clips here are rows in a temporary database; where a real file is needed
it is a few bytes written locally.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pipeline.footage import compact, enrich, intake, retrieval, store


@pytest.fixture
def db(tmp_path, monkeypatch):
    """An isolated library database and directory."""
    path = tmp_path / "library.db"
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    monkeypatch.setattr("pipeline.footage.store.LIBRARY_DB_PATH", path)
    monkeypatch.setattr("pipeline.footage.store.LIBRARY_DIR", library_dir)
    monkeypatch.setattr("pipeline.footage.compact.LIBRARY_DIR", library_dir)
    monkeypatch.setattr("pipeline.footage.compact.CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr("core.paths.LIBRARY_DIR", library_dir)
    real_connect = store.connect
    monkeypatch.setattr(store, "connect", lambda p=None: real_connect(p or path))
    return path


def add(db, filename, **kwargs):
    clip = store.Clip(filename=filename, **kwargs)
    store.upsert(clip, db_path=db)
    return clip


# --- migration ---------------------------------------------------------

class TestMigration:
    """An existing database has to gain the new columns in place. A
    virtual table cannot be altered, so the index is rebuilt."""

    def test_a_pre_attribute_database_is_upgraded(self, tmp_path, monkeypatch):
        import sqlite3
        path = tmp_path / "old.db"

        # The shape this project shipped first.
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE clips (
                filename TEXT PRIMARY KEY, description TEXT NOT NULL DEFAULT '',
                duration REAL NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT '',
                license TEXT NOT NULL DEFAULT '', license_verified INTEGER NOT NULL DEFAULT 0,
                added TEXT NOT NULL DEFAULT '', use_count INTEGER NOT NULL DEFAULT 0,
                last_used TEXT, frame_hashes TEXT NOT NULL DEFAULT '[]');
            CREATE VIRTUAL TABLE clips_fts USING fts5(filename UNINDEXED, description);
            INSERT INTO clips (filename, description, duration)
                VALUES ('a.mp4', 'a candle burning', 10.0);
            INSERT INTO clips_fts (filename, description)
                VALUES ('a.mp4', 'a candle burning');
        """)
        conn.commit()
        conn.close()

        clips = store.all_clips(db_path=path)
        assert len(clips) == 1
        assert clips[0].subject == ""          # new column, defaulted
        assert clips[0].reject_count == 0
        assert clips[0].description == "a candle burning"

        with store.connect(path) as conn:
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(clips_fts)")}
            assert {"subject", "setting", "description"} <= columns
            # Rebuilt from clips, not left empty.
            assert conn.execute("SELECT COUNT(*) FROM clips_fts").fetchone()[0] == 1

    def test_migration_is_idempotent(self, db):
        add(db, "a.mp4", description="x", subject="candle")
        for _ in range(3):
            assert len(store.all_clips(db_path=db)) == 1


# --- weighted ranking --------------------------------------------------

class TestWeightedRanking:
    """The point of the subject column: a clip that IS the thing should
    outrank one that merely contains it."""

    def test_subject_outranks_an_incidental_mention(self, db):
        add(db, "beads.mp4", subject="prayer beads", setting="wooden table",
            description="Dark wooden prayer beads coiled on a polished table.")
        add(db, "bedroom.mp4", subject="bedroom interior", setting="bedroom",
            description=("A softly blurred bedroom with furniture, a lamp, and a "
                         "string of prayer beads just visible at the edge of frame "
                         "beside some books and a folded blanket."))

        with store.connect(db) as conn:
            rows = retrieval._search(conn, '"prayer" OR "beads"', 5)

        assert rows, "the query should match both clips"
        assert rows[0]["filename"] == "beads.mp4", (
            "the clip whose subject is prayer beads must rank first")

    def test_rejections_push_a_clip_down(self, db):
        add(db, "good.mp4", subject="candle", description="a candle burning")
        add(db, "rejected.mp4", subject="candle", description="a candle burning")

        with store.connect(db) as conn:
            before = [r["filename"] for r in retrieval._search(conn, '"candle"', 5)]

        # Reject one enough times to matter.
        for _ in range(4):
            store.record_rejections(["rejected.mp4"], db_path=db)

        with store.connect(db) as conn:
            after = [r["filename"] for r in retrieval._search(conn, '"candle"', 5)]

        assert set(before) == set(after), "both clips should still be candidates"
        assert after[-1] == "rejected.mp4", "the repeatedly-rejected clip should sink"

    def test_one_rejection_does_not_bury_a_strong_match(self, db):
        add(db, "exact.mp4", subject="prayer beads", description="prayer beads")
        add(db, "weak.mp4", subject="a table", description="a table with many objects")
        store.record_rejections(["exact.mp4"], db_path=db)

        with store.connect(db) as conn:
            rows = [r["filename"] for r in retrieval._search(conn, '"prayer" OR "beads"', 5)]
        assert rows[0] == "exact.mp4", "a nudge, not a ban"


# Hash values with a genuine 64-bit distance between them. A single set
# bit differs from another single set bit by 2, not by 64 — a fixture
# that gets this wrong tests nothing.
LOOKS_A = 0x0000000000000000
LOOKS_B = 0xFFFFFFFFFFFFFFFF
LOOKS_A_NEAR = 0x0000000000000003     # 2 bits from LOOKS_A


# --- shot diversity ----------------------------------------------------

class TestShotDiversity:
    """Cutting between two shots that look the same reads as a mistake
    even when the footage is genuinely different."""

    def _clip(self, name, subject="", hashes=None):
        return store.Clip(filename=name, subject=subject,
                          frame_hashes=hashes if hashes is not None else [0, 0, 0])

    def test_identical_looking_clips_are_flagged(self):
        from pipeline.footage.library import _looks_like
        a = self._clip("a.mp4", hashes=[111, 222, 333])
        b = self._clip("b.mp4", hashes=[111, 222, 333])
        assert _looks_like(a, b)

    def test_visually_different_clips_are_not(self):
        from pipeline.footage.library import _looks_like
        a = self._clip("a.mp4", hashes=[LOOKS_A] * 3)
        b = self._clip("b.mp4", hashes=[LOOKS_B] * 3)
        assert not _looks_like(a, b)

    def test_the_same_subject_counts_as_too_alike(self):
        """Two different ocean clips back to back still read as one long
        ocean shot."""
        from pipeline.footage.library import _too_alike
        a = self._clip("a.mp4", subject="ocean waves", hashes=[LOOKS_A] * 3)
        b = self._clip("b.mp4", subject="ocean waves", hashes=[LOOKS_B] * 3)
        assert _too_alike(a, b)

    def test_different_subjects_that_look_different_are_fine(self):
        from pipeline.footage.library import _too_alike
        a = self._clip("a.mp4", subject="ocean waves", hashes=[LOOKS_A] * 3)
        b = self._clip("b.mp4", subject="candle flame", hashes=[LOOKS_B] * 3)
        assert not _too_alike(a, b)

    def test_nothing_precedes_the_first_shot(self):
        from pipeline.footage.library import _too_alike
        assert not _too_alike(self._clip("a.mp4"), None)

    def test_missing_hashes_never_block_a_pick(self):
        from pipeline.footage.library import _looks_like
        assert not _looks_like(self._clip("a.mp4", hashes=[]),
                               self._clip("b.mp4", hashes=[]))

    def test_selection_avoids_running_similar_clips_together(self, db):
        """End to end through _select: given a same-subject clip and a
        different one, both confidently matched, the different one wins
        the adjacent slot."""
        from pipeline.footage.library import _select
        from pipeline.plan import Segment

        ocean_a = self._clip("ocean_a.mp4", subject="ocean", hashes=[LOOKS_A] * 3)
        ocean_b = self._clip("ocean_b.mp4", subject="ocean", hashes=[LOOKS_A_NEAR] * 3)
        candle = self._clip("candle.mp4", subject="candle", hashes=[LOOKS_B] * 3)
        available = {c.filename: c for c in (ocean_a, ocean_b, candle)}

        data = {"picks": [{
            "segment_index": 0,
            "matches": [{"filename": "ocean_a.mp4", "confidence": 9},
                        {"filename": "ocean_b.mp4", "confidence": 9},
                        {"filename": "candle.mp4", "confidence": 8}],
            "search_queries": [],
        }]}
        picks, shortfalls = _select(data, [Segment("x")], [2], available, set())

        assert not shortfalls
        assert picks[0][0] == "ocean_a.mp4"
        assert picks[0][1] == "candle.mp4", "the second ocean clip should be skipped"

    def test_similarity_never_causes_a_shortfall(self, db):
        """If every candidate looks alike, take them anyway — a filled
        shot beats an empty one."""
        from pipeline.footage.library import _select
        from pipeline.plan import Segment

        clips = [self._clip(f"o{i}.mp4", subject="ocean", hashes=[LOOKS_A] * 3)
                 for i in range(3)]
        available = {c.filename: c for c in clips}
        data = {"picks": [{
            "segment_index": 0,
            "matches": [{"filename": c.filename, "confidence": 9} for c in clips],
            "search_queries": [],
        }]}
        picks, shortfalls = _select(data, [Segment("x")], [3], available, set())
        assert len(picks[0]) == 3
        assert not shortfalls


# --- enrichment --------------------------------------------------------

class TestEnrichment:
    def test_values_outside_the_allowed_set_fall_back(self):
        assert enrich._clean("Fast", enrich.MOTION_VALUES, "slow") == "fast"
        assert enrich._clean("supersonic", enrich.MOTION_VALUES, "slow") == "slow"
        assert enrich._clean("", enrich.PALETTE_VALUES, "neutral") == "neutral"

    def test_subjects_are_normalised(self):
        assert enrich._clean("  Prayer  Beads. ") == "prayer beads"

    def test_a_batch_updates_every_clip_it_covers(self, db):
        add(db, "a.mp4", description="a candle on a table")
        add(db, "b.mp4", description="an empty road at dusk")
        clips = store.all_clips(db_path=db)

        response = {"clips": [
            {"index": 0, "subject": "candle", "setting": "wooden table",
             "motion": "static", "palette": "warm", "time_of_day": "indoor",
             "has_people": False},
            {"index": 1, "subject": "country road", "setting": "open countryside",
             "motion": "slow", "palette": "cool", "time_of_day": "golden",
             "has_people": False},
        ]}
        with patch.object(enrich.llm, "call_json", return_value=response):
            updated = enrich.enrich_batch(clips, db_path=db)

        assert updated == 2
        assert store.get("a.mp4", db_path=db).subject == "candle"
        assert store.get("b.mp4", db_path=db).time_of_day == "golden"

    def test_a_skipped_clip_is_left_unenriched_rather_than_guessed(self, db):
        add(db, "a.mp4", description="one")
        add(db, "b.mp4", description="two")
        clips = store.all_clips(db_path=db)

        response = {"clips": [{"index": 0, "subject": "candle", "setting": "",
                               "motion": "static", "palette": "warm",
                               "time_of_day": "indoor", "has_people": False}]}
        with patch.object(enrich.llm, "call_json", return_value=response):
            updated = enrich.enrich_batch(clips, db_path=db)

        assert updated == 1
        assert store.get("b.mp4", db_path=db).subject == ""
        assert not store.get("b.mp4", db_path=db).enriched

    def test_a_failed_batch_does_not_stop_the_rest(self, db, monkeypatch):
        for i in range(60):
            add(db, f"c{i}.mp4", description=f"clip {i}")
        monkeypatch.setattr(enrich, "BATCH_SIZE", 25)

        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("first batch exploded")
            return {"clips": []}

        with patch.object(enrich.llm, "call_json", side_effect=flaky):
            result = enrich.enrich_library(db_path=db)

        assert result["batches"] == 3, "all three batches should be attempted"

    def test_the_cost_is_estimated_before_anything_is_spent(self, db):
        for i in range(30):
            add(db, f"c{i}.mp4", description="a description of some length " * 8)
        estimate = enrich.estimate_cost(db_path=db)
        assert estimate["clips"] == 30
        assert estimate["batches"] == 2
        assert 0 < estimate["usd"] < 1.0, "should be cents, not dollars"

    def test_already_enriched_clips_are_skipped_by_default(self, db):
        add(db, "done.mp4", description="x", subject="candle")
        add(db, "todo.mp4", description="y")
        assert enrich.estimate_cost(db_path=db)["clips"] == 1
        assert enrich.estimate_cost(only_missing=False, db_path=db)["clips"] == 2


# --- compaction --------------------------------------------------------

class TestCompaction:
    def test_the_plan_reports_without_touching_anything(self, db, tmp_path):
        library_dir = store.LIBRARY_DIR
        for i in range(3):
            path = library_dir / f"c{i}.mp4"
            path.write_bytes(b"x" * (20 * 1024 * 1024))
            add(db, f"c{i}.mp4", duration=30.0)

        proposal = compact.plan(db_path=db)
        assert len(proposal["candidates"]) == 3
        assert proposal["estimated_saving"] > 0
        # Nothing was rewritten.
        assert all((library_dir / f"c{i}.mp4").stat().st_size == 20 * 1024 * 1024
                   for i in range(3))

    def test_clips_too_small_to_be_worth_it_are_left_alone(self, db):
        (store.LIBRARY_DIR / "tiny.mp4").write_bytes(b"x" * 1000)
        add(db, "tiny.mp4", duration=3.0)
        proposal = compact.plan(db_path=db)
        assert proposal["candidates"] == []
        assert proposal["skipped"] == 1

    def test_a_failed_encode_leaves_the_original_intact(self, db, monkeypatch):
        path = store.LIBRARY_DIR / "c.mp4"
        path.write_bytes(b"x" * (20 * 1024 * 1024))
        clip = add(db, "c.mp4", duration=30.0)

        failed = MagicMock(returncode=1, stderr=b"ffmpeg said no")
        monkeypatch.setattr(compact.subprocess, "run", lambda *a, **k: failed)

        assert compact.compact_clip(clip, db_path=db) == 0
        assert path.stat().st_size == 20 * 1024 * 1024, "the original must survive"

    def test_a_suspiciously_small_result_is_rejected(self, db, monkeypatch):
        """ffmpeg can exit 0 having written something useless."""
        path = store.LIBRARY_DIR / "c.mp4"
        path.write_bytes(b"x" * (20 * 1024 * 1024))
        clip = add(db, "c.mp4", duration=30.0)

        def fake_run(command, **kwargs):
            # Write a truncated output where the command asked for one.
            from pathlib import Path
            Path(command[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(command[-1]).write_bytes(b"tiny")
            return MagicMock(returncode=0, stderr=b"")

        monkeypatch.setattr(compact.subprocess, "run", fake_run)
        assert compact.compact_clip(clip, db_path=db) == 0
        assert path.stat().st_size == 20 * 1024 * 1024

    def test_the_default_keeps_three_shot_windows(self):
        from pipeline.assemble import split_into_shots
        from pipeline.plan import Segment

        # A clip trimmed to the default must still cover more than one
        # maximum-length shot, or every reuse looks identical.
        windows = compact.DEFAULT_MAX_SECONDS / 5.0
        assert windows >= 3
        shots = split_into_shots([Segment("x", start=0, end=compact.DEFAULT_MAX_SECONDS)], 5.0)
        assert len(shots) == 3


# --- the feedback loop -------------------------------------------------

class TestDiscardFeedback:
    def test_only_footage_rejections_count(self, db, tmp_path):
        from core import gallery

        add(db, "a.mp4", description="x")
        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        gallery.save_report(video, {"clips": ["a.mp4"]})

        gallery.set_discarded(video, True, reason="script")
        assert store.get("a.mp4", db_path=db).reject_count == 0

        gallery.set_discarded(video, False)
        gallery.set_discarded(video, True, reason="footage")
        assert store.get("a.mp4", db_path=db).reject_count == 1

    def test_toggling_discard_does_not_double_count(self, db, tmp_path):
        from core import gallery

        add(db, "a.mp4", description="x")
        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        gallery.save_report(video, {"clips": ["a.mp4"]})

        gallery.set_discarded(video, True, reason="footage")
        gallery.set_discarded(video, True, reason="footage")
        assert store.get("a.mp4", db_path=db).reject_count == 1

    def test_a_video_with_no_report_is_harmless(self, db, tmp_path):
        from core import gallery
        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        gallery.set_discarded(video, True, reason="footage")   # must not raise


def test_match_call_is_not_marked_for_prompt_caching(monkeypatch):
    """Regression: the candidate block was marked cacheable and, across a
    month of real runs, was written to the cache 26 times and read from
    it zero times — every round re-shortlists, every video differs — so
    the marker only added the cache-write premium to every call."""
    from types import SimpleNamespace

    from pipeline import llm
    from pipeline.footage import library

    captured = {}

    def fake_call_json(system, user, schema, **kwargs):
        captured["system"] = llm._render_system(system)
        return {"picks": []}

    monkeypatch.setattr(library.llm, "call_json", fake_call_json)
    clips = [SimpleNamespace(filename=f"clip{i}.mp4", description="x " * 400)
             for i in range(50)]
    segments = [SimpleNamespace(text="a line", keywords=["k"])]
    library._run_match(segments, [1], clips, [], {})

    assert captured["system"]
    assert not any("cache_control" in block for block in captured["system"])


def test_frames_are_downscaled_before_description(monkeypatch):
    """Full-resolution frames made each description ~8k input tokens;
    the vision call only needs enough to name subject, setting and
    light."""
    import base64
    import io

    from PIL import Image

    from pipeline.footage import intake

    sent = {}

    def fake_vision(prompt, images, **kwargs):
        sent["images"] = images
        return "a candle on a table"

    monkeypatch.setattr(intake.llm, "call_vision", fake_vision)
    frames = [Image.new("RGB", (1080, 1920), (200, 100, 50)) for _ in range(3)]
    assert intake.describe(frames) == "a candle on a table"

    assert len(sent["images"]) == 3
    for media_type, data in sent["images"]:
        size = Image.open(io.BytesIO(base64.b64decode(data))).size
        assert size == (540, 960)
    # The caller's frames are untouched; they're also used for hashing.
    assert frames[0].size == (1080, 1920)


class TestShortfallFallback:
    """Regression: once fetching ran out of rounds, a short segment was
    filled with the least-recently-used clips in the whole library, with
    no connection to the line and no flag. A line about a crowd in
    Jerusalem got an elephant procession."""

    def _setup(self, db):
        from pipeline.plan import Segment
        add(db, "runner_up.mp4", description="people walking in a stone courtyard")
        add(db, "wrong.mp4", description="a crowd at a festival with elephants")
        add(db, "lexical.mp4", description="a large crowd gathered in an old city square",
            subject="crowd")
        add(db, "unrelated.mp4", description="a vulture on a railing over the sea")
        segment = Segment("Peter spoke to a crowd.", shot_brief="a crowd in an old city",
                          keywords=["crowd", "old city"])
        return segment

    def test_the_models_runner_up_is_used_before_anything_unscored(self, db):
        from pipeline.footage.library import Shortfall, _fill_fallbacks

        segment = self._setup(db)
        data = {"picks": [{"segment_index": 0, "search_queries": [], "matches": [
            {"filename": "runner_up.mp4", "confidence": 4},
            {"filename": "wrong.mp4", "confidence": 1}]}]}
        available = {c.filename: c for c in store.all_clips()}

        outcome = _fill_fallbacks([[]], [Shortfall(0, 1)], [1], [], set(),
                                  segments=[segment], data=data, available=available)
        assert outcome.picks == [["runner_up.mp4"]]
        assert outcome.unconfident == 1

    def test_then_the_segments_own_shortlist_never_a_clip_scored_wrong(self, db):
        from pipeline.footage.library import Shortfall, _fill_fallbacks

        segment = self._setup(db)
        data = {"picks": [{"segment_index": 0, "search_queries": [], "matches": [
            {"filename": "wrong.mp4", "confidence": 1}]}]}

        outcome = _fill_fallbacks([[]], [Shortfall(0, 2)], [2], [], set(),
                                  segments=[segment], data=data, available={})
        assert outcome.picks[0][0] == "lexical.mp4"
        assert "wrong.mp4" not in outcome.picks[0]
        assert outcome.unconfident == 2


def test_new_clips_are_enriched_as_they_are_fetched(db, monkeypatch):
    """Regression: enrichment only ran when someone ran the CLI, so every
    clip fetched since had no subject - the newest quarter of the library
    was invisible to subject weighting and the same-subject check."""
    from pipeline.footage import library

    fresh = add(db, "fresh.mp4", description="a candle on a wooden table")
    done = add(db, "done.mp4", description="a road at dusk", subject="road")
    seen = []
    monkeypatch.setattr(library.enrich, "enrich_batch", lambda clips: seen.extend(clips))

    library._enrich_new([fresh, done])
    assert [c.filename for c in seen] == ["fresh.mp4"]


def test_a_failed_enrichment_does_not_fail_the_render(db, monkeypatch):
    from core.errors import ExternalServiceError
    from pipeline.footage import library

    fresh = add(db, "fresh.mp4", description="a candle on a wooden table")

    def boom(clips):
        raise ExternalServiceError("Claude", "down")

    monkeypatch.setattr(library.enrich, "enrich_batch", boom)
    library._enrich_new([fresh])


def test_avoid_terms_match_whole_words_not_fragments():
    """Regression: substring matching meant "witch" excluded every clip of
    a light switch. Word-start matching keeps plurals and derived forms."""
    from types import SimpleNamespace

    def clip(description, filename="x.mp4"):
        return SimpleNamespace(description=description, filename=filename)

    avoid = ["witch", "mosque", "hindu"]
    assert not retrieval.clip_violates_avoid_list(clip("a hand flips a light switch"), avoid)
    assert retrieval.clip_violates_avoid_list(clip("a witch stirs a cauldron"), avoid)
    assert retrieval.clip_violates_avoid_list(clip("two mosques at dusk"), avoid)
    assert retrieval.clip_violates_avoid_list(clip("a temple of Hinduism"), avoid)
    assert retrieval.clip_violates_avoid_list(clip("a candle", "old_witch_auto1.mp4"), avoid)


class TestClipOwnership:
    """A clip belongs to the first channel that uses it. The same shot on
    two channels run by one person is the mass-production pattern, and a
    real pair of videos on two channels both used one silhouette clip."""

    def test_first_use_claims_it_and_later_uses_do_not_steal_it(self, db):
        add(db, "silhouette.mp4", description="a man sitting in a chair by a window")
        store.mark_used(["silhouette.mp4"], "bible")
        store.mark_used(["silhouette.mp4"], "witch")
        clip = store.get("silhouette.mp4")
        assert clip.owner == "bible" and clip.use_count == 2
        assert clip.available_to("bible") and not clip.available_to("witch")
        assert clip.available_to("")

    def test_another_channels_clip_never_reaches_the_shortlist(self, db):
        from pipeline.plan import Segment

        add(db, "owned.mp4", description="a man sitting in a chair by a window", subject="man in chair")
        add(db, "free.mp4", description="a woman sitting in a chair by a window", subject="woman in chair")
        store.mark_used(["owned.mp4"], "bible")
        segment = Segment("x", shot_brief="a person sitting in a chair by a window",
                          keywords=["chair", "window"])

        names = {c.filename for c in retrieval.shortlist([segment], channel_key="witch")}
        assert "owned.mp4" not in names and "free.mp4" in names
        names = {c.filename for c in retrieval.shortlist([segment], channel_key="bible")}
        assert {"owned.mp4", "free.mp4"} <= names

    def test_ownership_survives_a_redescribe(self, db):
        clip = add(db, "c.mp4", description="old")
        store.mark_used(["c.mp4"], "bible")
        clip = store.get("c.mp4")
        clip.description = "new"
        store.upsert(clip)
        assert store.get("c.mp4").owner == "bible"
