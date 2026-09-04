"""
Regression tests for the pure logic in the pipeline.

Every test here corresponds to a bug this project actually shipped and
then fixed, or to an invariant a fix depends on. The project's own notes
describe several of these fixes in detail — including one that says it
was "verified with a unit test" for a test that isn't in the repository.
Written and thrown away is the same as never written: the next refactor
brings the bug back.

Nothing here needs an API key, a network, or a video file.
"""

from __future__ import annotations

import pytest

from core.channels import (
    Cta, EndScreen, Monetization, ChannelConfig, channel_from_dict,
    channel_to_sparse_dict, resolve_active_ctas,
)
from core.errors import ConfigError
from core.paths import slugify, safe_join, unique_stem, PathTraversalError
from pipeline import similarity, tts
from pipeline.assemble import group_words, split_into_shots, wrap_words, load_font
from pipeline.footage import intake, retrieval
from pipeline.plan import Script, Segment, WordTiming


# --- paths and slugs ---------------------------------------------------

class TestSlugify:
    def test_collapses_runs_and_strips_edges(self):
        assert slugify("Minute Pastor!") == "minute_pastor"
        assert slugify("John 3:16") == "john_3_16"
        assert slugify("  --Hello--  World  ") == "hello_world"

    def test_falls_back_when_nothing_usable(self):
        assert slugify("!!!", fallback="video") == "video"
        assert slugify("", fallback="clip") == "clip"
        assert slugify(None, fallback="x") == "x"

    def test_output_is_always_a_valid_key(self):
        import re
        for raw in ["Ünïcodé Ch@nnel", "a-b-c", "9 lives", "___"]:
            result = slugify(raw, fallback="fallback")
            assert re.fullmatch(r"[a-z0-9_]+", result), result


class TestSafeJoin:
    def test_allows_descendants(self, tmp_path):
        assert safe_join(tmp_path, "a", "b.txt") == (tmp_path / "a" / "b.txt").resolve()

    def test_allows_the_root_itself(self, tmp_path):
        # The idiom this replaced ("root in target.parents") rejected
        # this case, and one route had to special-case it while three
        # others silently didn't.
        assert safe_join(tmp_path) == tmp_path.resolve()

    @pytest.mark.parametrize("attack", ["../secrets", "a/../../secrets", "../../../etc/passwd"])
    def test_rejects_traversal(self, tmp_path, attack):
        with pytest.raises(PathTraversalError):
            safe_join(tmp_path, attack)


def test_unique_stem_appends_suffixes(tmp_path):
    assert unique_stem(tmp_path, "john_3_16") == "john_3_16"
    (tmp_path / "john_3_16.mp4").touch()
    assert unique_stem(tmp_path, "john_3_16") == "john_3_16_2"
    (tmp_path / "john_3_16_2.mp4").touch()
    assert unique_stem(tmp_path, "john_3_16") == "john_3_16_3"


# --- channel config ----------------------------------------------------

class TestChannelConfig:
    def _valid(self, **overrides):
        base = dict(content_mode="topic", voice="v1", style_prompt="be funny",
                    topics=["coffee"], channel_display_name="Test")
        base.update(overrides)
        return channel_from_dict("test", base)

    def test_validate_accepts_a_complete_channel(self):
        self._valid().validate()

    @pytest.mark.parametrize("overrides,fragment", [
        ({"voice": ""}, "voice"),
        ({"style_prompt": ""}, "style prompt"),
        ({"content_mode": "nonsense"}, "recognised"),
        ({"content_mode": "static_corpus", "source": ""}, "source"),
        ({"topics": []}, "topic list"),
    ])
    def test_validate_names_the_channel_and_the_problem(self, overrides, fragment):
        with pytest.raises(ConfigError) as exc:
            self._valid(**overrides).validate()
        message = str(exc.value)
        assert "test" in message
        assert fragment in message

    def test_output_dir_defaults_from_the_key(self):
        assert self._valid().output_dir == "output/test"

    def test_style_color_list_becomes_a_tuple(self):
        # channels.json can only hold a list; PIL requires a tuple.
        channel = self._valid(style={"outro_bg_color": [1, 2, 3, 255]})
        assert channel.style.outro_bg_color == (1, 2, 3, 255)

    def test_dict_access_still_works(self):
        # Templates and older call sites index channels like dicts.
        channel = self._valid()
        assert channel["voice"] == "v1"
        assert channel.get("missing", "default") == "default"


class TestSparseSave:
    """The wipe-on-save bug: settings saves rewrote the COMPLETE entry, so
    any field the form didn't know about was overwritten with a blank.
    A sparse write can only change what it carries."""

    def test_only_non_defaults_are_written(self):
        channel = channel_from_dict("test", {
            "content_mode": "topic", "voice": "v1", "style_prompt": "p",
            "topics": ["a"], "channel_display_name": "Test",
        })
        sparse = channel_to_sparse_dict(channel)
        assert "pacing" not in sparse       # entirely default
        assert "style" not in sparse
        assert "archived" not in sparse
        assert sparse["voice"] == "v1"

    def test_partial_overrides_keep_only_the_changed_field(self):
        channel = channel_from_dict("test", {
            "content_mode": "topic", "voice": "v1", "style_prompt": "p",
            "topics": ["a"], "pacing": {"segment_count": 5},
        })
        assert channel_to_sparse_dict(channel)["pacing"] == {"segment_count": 5}

    def test_round_trip_is_lossless(self):
        original = channel_from_dict("test", {
            "content_mode": "static_corpus", "voice": "v1", "style_prompt": "p",
            "source": "bible", "avoid_imagery": ["mosque"], "speed": 1.2,
            "pacing": {"segment_count": 4}, "style": {"font_size": 90},
            "monetization": {"merch_url": "https://example.com"},
            "socials": {"youtube_url": "https://yt.example"},
            "end_screen": {"enabled": True, "ctas": {"merch": {"enabled": True}}},
            "manual_checklist_overrides": ["patreon"],
        })
        assert channel_from_dict("test", channel_to_sparse_dict(original)) == original


class TestResolveActiveCtas:
    def test_enabled_but_empty_url_is_skipped(self):
        # A CTA that's switched on but points nowhere must render
        # nothing, not a blank line.
        end_screen = EndScreen(enabled=True, ctas={"patreon": {"enabled": True}})
        assert resolve_active_ctas(Monetization(), end_screen) == []

    def test_url_without_enabled_is_skipped(self):
        assert resolve_active_ctas(
            Monetization(patreon_url="https://p.example"), EndScreen()) == []

    def test_active_cta_is_returned_with_its_text(self):
        end_screen = EndScreen(enabled=True, ctas={"patreon": {"enabled": True}})
        active = resolve_active_ctas(Monetization(patreon_url="https://p.example"), end_screen)
        assert active == [{"type": "patreon", "text": "Support us on Patreon",
                           "url": "https://p.example"}]

    def test_blank_cta_text_falls_back_to_the_default(self):
        end_screen = EndScreen(ctas={"merch": {"enabled": True, "text": "  "}})
        assert end_screen.ctas["merch"].text == "Check out our merch"

    def test_affiliate_needs_at_least_one_link(self):
        end_screen = EndScreen(ctas={"affiliate": {"enabled": True}})
        assert resolve_active_ctas(Monetization(affiliate_links=[]), end_screen) == []
        active = resolve_active_ctas(
            Monetization(affiliate_links=[{"label": "Journal", "url": "u"}]), end_screen)
        assert active[0]["links"] == [{"label": "Journal", "url": "u"}]


# --- TTS text handling -------------------------------------------------

class TestCitationExpansion:
    @pytest.mark.parametrize("citation,expected", [
        ("John 3:16", "John, chapter 3, verse 16"),
        ("Genesis 2:8-9", "Genesis, chapter 2, verses 8 to 9"),
        ("1 Corinthians 13:4", "1 Corinthians, chapter 13, verse 4"),
        ("Song of Solomon 1:1", "Song of Solomon, chapter 1, verse 1"),
    ])
    def test_expands_book_chapter_verse(self, citation, expected):
        assert tts.expand_citation_for_speech(citation) == expected

    @pytest.mark.parametrize("citation", ["Shakespeare", "Hamlet, Act III", ""])
    def test_leaves_other_shapes_alone(self, citation):
        assert tts.expand_citation_for_speech(citation) == citation


class TestPronunciationOverrides:
    def test_respells_only_the_capitalized_word(self):
        assert tts.apply_pronunciation_overrides("Job said") == "Jobe said"
        # The common noun must never be touched.
        assert tts.apply_pronunciation_overrides("a job well done") == "a job well done"

    def test_revert_is_case_insensitive(self):
        """The real bug: revert used a case-SENSITIVE startswith, but the
        transcript-comparison path lowercases first, so it silently never
        fired there. Whisper transcribing the respelled "Jobe" back as
        "job" then read as a genuine mismatch and triggered a paid retry
        on perfectly good audio."""
        assert tts.revert_pronunciation_overrides("Jobe") == "Job"
        assert tts.revert_pronunciation_overrides("jobe") == "job"
        assert tts.revert_pronunciation_overrides("Jobe,") == "Job,"

    def test_transcript_normalisation_survives_the_respelling(self):
        expected = tts.normalize_words("Jobe, chapter 1, verse 8")
        actual = tts.normalize_words("Job chapter 1 verse 8")
        assert expected == actual

    def test_hyphenation_does_not_look_like_two_wrong_words(self):
        """Whisper sometimes hyphenates a word it's unsure of."""
        assert tts.normalize_words("pangram") == tts.normalize_words("pan-gram")
        assert tts.normalize_words("don't stop") == tts.normalize_words("dont stop")


class TestGlitchDetection:
    def _timings(self, words, step=0.5):
        return [WordTiming(w, i * step, i * step + 0.4) for i, w in enumerate(words)]

    def test_clean_synthesis_passes(self):
        words = "the quick brown fox jumps over the lazy dog today".split()
        assert not tts.looks_glitched(" ".join(words), self._timings(words))

    def test_backward_time_jump_is_caught(self):
        timings = self._timings("one two three four".split())
        timings[2].start = 0.1
        assert tts.looks_glitched("one two three four", timings)

    def test_repeated_phrase_is_caught(self):
        words = "when we do not know when we do not know the answer".split()
        assert tts.looks_glitched(" ".join(words), self._timings(words))

    def test_word_inflation_is_caught(self):
        expected = "one two three four five six"          # 6 words, past the short-text exemption
        words = "one two three four five six seven eight nine ten".split()
        assert tts.looks_glitched(expected, self._timings(words))

    def test_short_text_is_not_judged_on_word_count(self):
        # "Job 1:8" tokenizes unevenly; its expected count isn't a
        # reliable baseline.
        words = "Jobe chapter one verse eight".split()
        assert not tts.looks_glitched("Job 1:8", self._timings(words))

    def test_empty_timings_are_not_a_glitch(self):
        assert not tts.looks_glitched("anything", [])


class TestTtsPlan:
    def _pacing(self):
        from core.channels import Pacing
        return Pacing(pause_after_first_segment=0.7, pause_after_citation=0.5,
                      pause_between_segments=0.4)

    def test_citation_is_spoken_after_segment_zero_with_no_segment_of_its_own(self):
        segments = [Segment("quote"), Segment("one"), Segment("two")]
        plan = tts.build_plan(segments, "John 3:16", self._pacing())
        assert [p[2] for p in plan] == [0, None, 1, 2]
        assert plan[1][0] == "John, chapter 3, verse 16"

    def test_no_citation_means_no_extra_entry(self):
        segments = [Segment("a"), Segment("b")]
        plan = tts.build_plan(segments, None, self._pacing())
        assert [p[2] for p in plan] == [0, 1]

    def test_last_segment_has_no_trailing_pause(self):
        segments = [Segment("a"), Segment("b")]
        plan = tts.build_plan(segments, None, self._pacing())
        assert plan[-1][1] == 0.0


# --- captions and shots ------------------------------------------------

class TestGroupWords:
    def _pacing(self, max_group=4, gap=0.25):
        from core.channels import Pacing
        return Pacing(caption_max_group_size=max_group, caption_pause_gap_threshold=gap)

    def test_breaks_at_a_real_pause(self):
        words = [WordTiming("a", 0.0, 0.2), WordTiming("b", 0.25, 0.45),
                 WordTiming("c", 1.5, 1.7)]   # 1.05s gap
        groups = group_words(words, self._pacing())
        assert [[w.word for w in g] for g in groups] == [["a", "b"], ["c"]]

    def test_breaks_after_a_sentence_end(self):
        words = [WordTiming("Hi.", 0.0, 0.2), WordTiming("Next", 0.25, 0.5)]
        groups = group_words(words, self._pacing())
        assert len(groups) == 2

    def test_breaks_at_the_group_size_cap(self):
        words = [WordTiming(str(i), i * 0.2, i * 0.2 + 0.15) for i in range(9)]
        groups = group_words(words, self._pacing(max_group=4))
        assert [len(g) for g in groups] == [4, 4, 1]

    def test_no_words_makes_no_groups(self):
        assert group_words([], self._pacing()) == []


class TestSplitIntoShots:
    def test_short_segment_is_one_shot(self):
        shots = split_into_shots([Segment("x", start=0.0, end=3.0)], 5.0)
        assert len(shots) == 1
        assert (shots[0].start, shots[0].end) == (0.0, 3.0)

    def test_shots_are_even_with_no_short_remainder(self):
        # 12s at a 5s cap is 3 shots of 4s, not 5+5+2 — a short trailing
        # fragment reads as a mistake.
        shots = split_into_shots([Segment("x", start=0.0, end=12.0)], 5.0)
        assert len(shots) == 3
        durations = [round(s.duration, 6) for s in shots]
        assert durations == [4.0, 4.0, 4.0]

    def test_shots_tile_the_segment_exactly(self):
        shots = split_into_shots([Segment("x", start=2.0, end=13.0)], 5.0)
        assert shots[0].start == 2.0
        assert shots[-1].end == pytest.approx(13.0)
        for a, b in zip(shots, shots[1:]):
            assert a.end == pytest.approx(b.start)

    def test_every_shot_is_within_the_cap(self):
        shots = split_into_shots([Segment("x", start=0.0, end=17.3)], 5.0)
        assert all(s.duration <= 5.0 + 1e-9 for s in shots)

    def test_segment_index_is_carried(self):
        shots = split_into_shots(
            [Segment("a", start=0, end=6), Segment("b", start=6, end=9)], 5.0)
        assert {s.segment_index for s in shots} == {0, 1}


def test_wrap_words_never_loses_a_word():
    font = load_font(40)
    words = "the quick brown fox jumps over the lazy dog again and again".split()
    lines = wrap_words(words, font, 300)
    assert [w for line in lines for w in line] == words


# --- footage: duplicate detection --------------------------------------

class TestDuplicateDetection:
    """The false-positive incident: a single-frame average hash matched a
    crowd photo against a wave photo because they shared a coarse
    light/dark layout at one sampled moment. Real, distinct footage was
    nearly deleted."""

    IDENTICAL = [111, 222, 333]

    def test_identical_hashes_and_duration_are_a_duplicate(self):
        assert intake.is_duplicate(self.IDENTICAL, 10.0, self.IDENTICAL, 10.0)

    def test_one_differing_frame_defeats_the_match(self):
        other = [111, 222, 333 ^ 0xFFFFFFFF]
        assert not intake.is_duplicate(self.IDENTICAL, 10.0, other, 10.0)

    def test_different_durations_defeat_the_match(self):
        assert not intake.is_duplicate(self.IDENTICAL, 10.0, self.IDENTICAL, 30.0)

    def test_small_duration_differences_are_tolerated(self):
        assert intake.is_duplicate(self.IDENTICAL, 10.0, self.IDENTICAL, 10.5)

    def test_near_matches_within_threshold_count(self):
        near = [h ^ 0b1 for h in self.IDENTICAL]     # 1 bit each
        assert intake.is_duplicate(self.IDENTICAL, 10.0, near, 10.0)

    def test_mismatched_frame_counts_are_never_duplicates(self):
        assert not intake.is_duplicate([1, 2, 3], 10.0, [1, 2], 10.0)

    def test_empty_hashes_are_never_duplicates(self):
        assert not intake.is_duplicate([], 10.0, [], 10.0)


class TestClusterDuplicates:
    """A group is only auto-deletable when it's a full clique. A merely
    connected group (A~B, B~C, but not A~C) is exactly the shape that
    caused the false positive, so it's reported and left alone."""

    class FakeClip:
        def __init__(self, name, hashes, duration=10.0, use_count=0, added="2026-01-01"):
            self.filename, self.frame_hashes = name, hashes
            self.duration, self.use_count, self.added = duration, use_count, added

    def test_mutual_group_is_a_clique(self):
        clips = [self.FakeClip(f"{i}.mp4", [1, 2, 3]) for i in range(3)]
        _, cliques, ambiguous = intake.cluster_duplicates(clips)
        assert len(cliques) == 1 and len(cliques[0]) == 3
        assert ambiguous == []

    def test_chained_group_is_ambiguous_not_a_clique(self):
        # b sits within threshold of both a and c; a and c are 6 bits
        # apart from each other in opposite directions, so a~c fails.
        # a~b = 5 bits, b~c = 5 bits (both within the 6-bit threshold),
        # but a~c = 10 bits, which is outside it.
        a = self.FakeClip("a.mp4", [0b0000000000, 0b0000000000, 0b0000000000])
        b = self.FakeClip("b.mp4", [0b0000011111, 0b0000011111, 0b0000011111])
        c = self.FakeClip("c.mp4", [0b1111111111, 0b1111111111, 0b1111111111])
        _, cliques, ambiguous = intake.cluster_duplicates([a, b, c])
        assert cliques == []
        assert len(ambiguous) == 1

    def test_unrelated_clips_form_no_group(self):
        all_bits = (1 << 64) - 1        # 64 bits differing from zero
        clips = [self.FakeClip("a.mp4", [0, 0, 0]),
                 self.FakeClip("b.mp4", [all_bits, all_bits, all_bits])]
        pairs, cliques, ambiguous = intake.cluster_duplicates(clips)
        assert (pairs, cliques, ambiguous) == ([], [], [])

    def test_keeper_prefers_the_most_used(self):
        group = [self.FakeClip("a.mp4", [], use_count=1),
                 self.FakeClip("b.mp4", [], use_count=9)]
        assert intake.keeper(group).filename == "b.mp4"

    def test_keeper_breaks_ties_by_age(self):
        group = [self.FakeClip("new.mp4", [], added="2026-05-01"),
                 self.FakeClip("old.mp4", [], added="2024-01-01")]
        assert intake.keeper(group).filename == "old.mp4"


# --- footage: retrieval ------------------------------------------------

class TestRetrievalQuery:
    def test_stopwords_and_short_tokens_are_dropped(self):
        assert retrieval._terms("The cat is on a mat") == ["cat", "mat"]

    def test_keywords_are_weighted_by_repetition(self):
        # Twice, not three times: the keyword also appears in the text,
        # but the weighting should mean exactly what it says.
        query = retrieval.build_query(Segment("a storm at sea", keywords=["storm"]))
        assert query.count('"storm"') == 2
        assert query.count('"sea"') == 1

    def test_terms_are_quoted_so_operators_cannot_leak(self):
        # A segment containing "or" or "near" must not change the query's
        # meaning.
        query = retrieval.build_query(Segment("rain near the shore", keywords=[]))
        assert '"near"' in query
        assert " OR " in query

    def test_empty_segment_makes_no_query(self):
        assert retrieval.build_query(Segment("the a an", keywords=[])) == ""


class TestScriptSchema:
    """The schema is sent to a real API with real constraints. A 400 here
    fails every video, so the shape is worth asserting directly."""

    def test_no_array_bounds_anywhere(self):
        """`minItems`/`maxItems` other than 0 or 1 are rejected by the
        API with a 400 — which is exactly how this shipped broken. The
        segment count is stated in the prompt and checked in code
        instead."""
        from pipeline.script_gen import _segments_schema, QUOTE_SCHEMA_EXTRA

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("minItems", "maxItems"):
                        assert value in (0, 1), f"{key}={value} is rejected by the API"
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(_segments_schema())
        walk(_segments_schema(extra=QUOTE_SCHEMA_EXTRA))

    def test_every_segment_requires_a_shot_brief(self):
        from pipeline.script_gen import _segments_schema
        item = _segments_schema()["properties"]["segments"]["items"]
        assert set(item["required"]) == {"text", "shot_brief", "keywords"}
        assert item["additionalProperties"] is False

    def test_quote_mode_asks_for_the_quotes_own_brief(self):
        from pipeline.script_gen import _segments_schema, QUOTE_SCHEMA_EXTRA
        schema = _segments_schema(extra=QUOTE_SCHEMA_EXTRA)
        assert "quote_shot_brief" in schema["properties"]
        assert "quote_shot_brief" in schema["required"]

    def test_the_prompt_states_the_segment_count(self):
        # With no schema bound to enforce it, the wording is the only
        # thing asking for the right number.
        from pipeline.script_gen import _quote_instructions, _topic_instructions
        for text in (_quote_instructions(3), _topic_instructions(3)):
            assert "EXACTLY 3" in text

    def test_wrong_count_warns_but_does_not_raise(self):
        from pipeline.script_gen import _check_count
        _check_count([Segment("a"), Segment("b")], 3)     # must not raise


class TestShotBriefs:
    """Footage is matched against the brief, never the spoken line.

    Measured on the real library: 63% of the abstract keywords the old
    prompt produced ("integrity", "conviction") appeared in no clip
    description at all, because nothing can film an abstract noun."""

    def test_visual_text_prefers_the_brief(self):
        segment = Segment(text="Doubt is the road into faith.",
                          shot_brief="an empty country road at dusk")
        assert segment.visual_text == "an empty country road at dusk"

    def test_visual_text_falls_back_to_the_spoken_line(self):
        # Scripts generated before briefs existed must still match.
        assert Segment(text="a spoken line").visual_text == "a spoken line"

    def test_the_query_is_built_from_the_brief_not_the_line(self):
        segment = Segment(
            text="There is something quietly haunting about integrity.",
            shot_brief="weathered stone carvings in low evening light",
            keywords=["stone carvings"],
        )
        query = retrieval.build_query(segment)
        assert '"stone"' in query and '"carvings"' in query
        # Nothing from the abstract sentence leaks in.
        assert "haunting" not in query
        assert "integrity" not in query

    def test_a_brief_retrieves_better_than_an_abstract_line(self):
        """The core claim, as a property rather than a fixture: a
        concrete brief produces query terms that a literal clip
        description could plausibly contain; an abstract line does not."""
        abstract = Segment(text="This speaks to integrity and conviction.",
                           keywords=["integrity", "conviction"])
        concrete = Segment(text="This speaks to integrity and conviction.",
                           shot_brief="a single candle burning in a dark room",
                           keywords=["candle", "dark room"])
        assert set(retrieval._terms(concrete.visual_text)) & {"candle", "burning", "dark", "room"}
        assert not set(retrieval._terms(abstract.visual_text)) & {"candle", "burning"}


class TestAvoidList:
    class FakeClip:
        def __init__(self, description="", filename="c.mp4"):
            self.description, self.filename = description, filename

    def test_matches_in_the_description(self):
        clip = self.FakeClip(description="An outdoor Islamic prayer service at a mosque.")
        assert retrieval.clip_violates_avoid_list(clip, ["mosque"])

    def test_matches_in_the_filename(self):
        clip = self.FakeClip(filename="mosque_exterior.mp4")
        assert retrieval.clip_violates_avoid_list(clip, ["mosque"])

    def test_is_case_insensitive(self):
        clip = self.FakeClip(description="A MOSQUE at dusk")
        assert retrieval.clip_violates_avoid_list(clip, ["Mosque"])

    def test_empty_avoid_list_blocks_nothing(self):
        assert not retrieval.clip_violates_avoid_list(self.FakeClip("anything"), [])


class TestRoundRobin:
    """Several shortfalled segments' queries are combined into one fetch
    round. Taking candidates in order let whichever segment's queries were
    built first consume the entire round."""

    def test_one_per_query_before_any_second(self):
        by_query = {f"q{i}": [f"q{i}_a", f"q{i}_b"] for i in range(18)}
        from pipeline.footage.library import _round_robin
        chosen = _round_robin(by_query, 12)
        assert len(chosen) == 12
        assert len(set(chosen)) == 12
        # First pass only: every pick is each query's first candidate.
        assert all(c.endswith("_a") for c in chosen)

    def test_two_queries_split_the_cap_evenly(self):
        by_query = {"a": [f"a{i}" for i in range(10)], "b": [f"b{i}" for i in range(10)]}
        from pipeline.footage.library import _round_robin
        chosen = _round_robin(by_query, 12)
        assert sum(1 for c in chosen if c.startswith("a")) == 6
        assert sum(1 for c in chosen if c.startswith("b")) == 6

    def test_stops_when_candidates_run_out(self):
        from pipeline.footage.library import _round_robin
        assert len(_round_robin({"a": ["a1"], "b": ["b1"]}, 12)) == 2

    def test_uneven_buckets_do_not_loop_forever(self):
        from pipeline.footage.library import _round_robin
        chosen = _round_robin({"a": ["a1", "a2", "a3"], "b": ["b1"]}, 12)
        assert len(chosen) == 4


# --- originality -------------------------------------------------------

class TestSimilarity:
    def _script(self, *texts, citation=None):
        segments = [Segment(t) for t in texts]
        return Script(segments=segments, citation=citation)

    def test_the_source_quote_is_excluded_from_comparison(self):
        """Segment 0 of a quote script is someone else's words, identical
        every time that verse comes up. Including it would flag every
        repeated verse while hiding real drift in the analysis."""
        script = self._script("For God so loved the world", "My own analysis here",
                              citation="John 3:16")
        assert "For God so loved" not in similarity.script_text(script)
        assert "My own analysis here" in similarity.script_text(script)

    def test_topic_scripts_compare_every_segment(self):
        script = self._script("first bit", "second bit")
        assert "first bit" in similarity.script_text(script)

    def test_identical_text_scores_one(self):
        words = similarity._words("the shepherd guides his flock through the valley")
        assert similarity.cosine(words, words) == pytest.approx(1.0)
        assert similarity.trigram_overlap(words, words) == pytest.approx(1.0)

    def test_unrelated_text_scores_near_zero(self):
        a = similarity._words("a shepherd guides his flock through a quiet valley")
        b = similarity._words("quantum computers factor large integers efficiently")
        assert similarity.cosine(a, b) < 0.1
        assert similarity.trigram_overlap(a, b) < 0.1

    def test_reordering_defeats_trigrams_but_not_cosine(self):
        """This is why there are two measures: a reworded retread shares
        almost no phrases but nearly all of its vocabulary."""
        a = similarity._words("the shepherd guides his flock through the quiet valley at dusk")
        b = similarity._words("at dusk the quiet valley sees his flock guided by the shepherd")
        assert similarity.trigram_overlap(a, b) < 0.15
        assert similarity.cosine(a, b) > 0.7

    def test_no_history_means_no_flag(self, tmp_path):
        report = similarity.check("ch", self._script("something new"),
                                  path=tmp_path / "h.json")
        assert not report.flagged
        assert report.compared_against == 0

    def test_a_near_duplicate_is_flagged_and_named(self, tmp_path):
        path = tmp_path / "h.json"
        original = self._script(
            "Doubt is not the opposite of faith but a part of it, and that matters.")
        similarity.record("ch", "first_video", original, path=path)

        report = similarity.check("ch", original, path=path)
        assert report.flagged
        assert report.closest_title == "first_video"
        assert "first_video" in report.summary

    def test_a_genuinely_different_script_is_not_flagged(self, tmp_path):
        path = tmp_path / "h.json"
        similarity.record("ch", "first", self._script(
            "Doubt is not the opposite of faith but a part of it."), path=path)
        report = similarity.check("ch", self._script(
            "Rain fell for forty days and the ark carried every living kind."), path=path)
        assert not report.flagged

    def test_history_is_per_channel(self, tmp_path):
        path = tmp_path / "h.json"
        script = self._script("Doubt is not the opposite of faith but a part of it.")
        similarity.record("channel_a", "v1", script, path=path)
        assert not similarity.check("channel_b", script, path=path).flagged

    def test_history_is_capped(self, tmp_path):
        path = tmp_path / "h.json"
        for i in range(similarity.HISTORY_LIMIT + 20):
            similarity.record("ch", f"v{i}", self._script(f"unique text number {i}"), path=path)
        assert len(similarity._load(path)["ch"]) == similarity.HISTORY_LIMIT

    def test_corrupt_history_does_not_raise(self, tmp_path):
        path = tmp_path / "h.json"
        path.write_text("{not json", encoding="utf-8")
        assert similarity.check("ch", self._script("x"), path=path).compared_against == 0
