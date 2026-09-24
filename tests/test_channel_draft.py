"""
Pitch -> draft channel -> real channel.

The model call is faked. What's tested: a confident wrong answer (a voice
id that doesn't exist, a quote channel with nothing to quote, a length of
400 seconds) becomes a sensible default rather than a broken channel; a
draft is only ever a file until accepted; and accepting creates a channel
that can make its first video, with its topic plan and first topic
written.
"""

from __future__ import annotations

import pytest

from core import drafts
from core.errors import ConfigError
from pipeline import channel_draft

VOICES = [{"voice_id": f"voice{i:015d}", "name": f"Voice {i}", "description": "warm",
           "preview_url": ""} for i in range(5)]
VOICE_IDS = [v["voice_id"] for v in VOICES]


def model_answer(**overrides):
    answer = {
        "name_options": ["Orbit Notes", "Small Science", "The Lab Bench"],
        "summary": "One surprising science idea a day for curious teenagers.",
        "audience": "13-17, curious, no background",
        "content_mode": "topic", "corpus_source": "", "custom_quotes": [],
        "subject": "Everyday science",
        "style_prompt": "Write for a curious teenager who has never studied this.",
        "target_seconds": 50, "segment_count": 3, "speed": 1.0,
        "avoid_imagery": ["Weapons", " gore "],
        "voice_brief": "young, bright, clear",
        "voice_ids": [VOICE_IDS[2], VOICE_IDS[0], VOICE_IDS[4]],
        "palette_key": "cool_teal",
        "visual_approach": "diagrams", "visual_reason": "science needs showing",
        "needs_news_source": False,
        "risks": ["Generic science facts channels are common; the draft narrows to one idea a day."],
    }
    answer.update(overrides)
    return answer


class TestClean:
    def test_unknown_voices_and_palette_fall_back_to_real_ones(self):
        out = channel_draft.clean(model_answer(voice_ids=["made-up"], palette_key="neon"),
                                  VOICE_IDS)
        assert out["voice_ids"] == VOICE_IDS[:3]
        assert out["palette_key"] == "warm_gold"

    def test_numbers_are_held_to_what_renders(self):
        out = channel_draft.clean(model_answer(target_seconds=400, segment_count=0, speed=3),
                                  VOICE_IDS)
        assert (out["target_seconds"], out["segment_count"], out["speed"]) == (90, 2, 1.15)

    def test_a_quote_channel_with_nothing_to_quote_becomes_a_topic_channel(self):
        out = channel_draft.clean(model_answer(content_mode="static_corpus",
                                               corpus_source="custom", custom_quotes=[]),
                                  VOICE_IDS)
        assert out["content_mode"] == "topic" and out["corpus_source"] == ""

    def test_a_real_quote_list_is_kept(self):
        out = channel_draft.clean(model_answer(content_mode="static_corpus", corpus_source="custom",
                                               custom_quotes=["Know thyself. — Socrates", " "]),
                                  VOICE_IDS)
        assert out["corpus_source"] == "custom"
        assert out["custom_quotes"] == ["Know thyself. — Socrates"]

    def test_avoid_terms_are_normalised(self):
        assert channel_draft.clean(model_answer(), VOICE_IDS)["avoid_imagery"] == ["weapons", "gore"]

    def test_no_style_prompt_is_an_error_not_an_empty_channel(self):
        from core.errors import PipelineError
        with pytest.raises(PipelineError):
            channel_draft.clean(model_answer(style_prompt="  "), VOICE_IDS)


def test_the_draft_call_offers_only_real_voices_and_palettes(monkeypatch):
    seen = {}

    def fake(system, user, schema, **kwargs):
        seen["user"], seen["schema"], seen["kwargs"] = user, schema, kwargs
        return model_answer()

    monkeypatch.setattr(channel_draft, "call_json", fake)
    channel_draft.draft("science for teenagers", VOICES, note="UK spelling")
    assert "science for teenagers" in seen["user"] and "UK spelling" in seen["user"]
    props = seen["schema"]["properties"]
    assert props["voice_ids"]["items"]["enum"] == VOICE_IDS
    assert "cool_teal" in props["palette_key"]["enum"]
    assert seen["kwargs"]["operation"] == "channel_draft"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", tmp_path / "channels.json")
    monkeypatch.setattr("core.curriculum.CURRICULA_DIR", tmp_path / "curricula")
    monkeypatch.setattr("core.corpus.CORPORA_DIR", tmp_path / "corpora")
    monkeypatch.setattr("core.channel_admin.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(drafts.voice_lab, "get_cached_voices", lambda: VOICES)
    answers = {"body": model_answer()}
    monkeypatch.setattr(channel_draft, "draft",
                        lambda pitch, voices, note="", previous=None:
                        channel_draft.clean(answers["body"], VOICE_IDS))
    monkeypatch.setattr(channel_draft, "outline", lambda style, subject, name: [
        {"title": "What things are made of", "summary": "atoms", "level": "foundation",
         "target_subtopics": 20},
        {"title": "Forces", "summary": "pushes", "level": "intermediate", "target_subtopics": 20},
    ])
    from pipeline import curriculum_gen
    monkeypatch.setattr(curriculum_gen, "write_subtopics", lambda channel, data, topic: [
        {"title": "Why you can't see atoms", "angle": "scale"},
        {"title": "What a molecule is", "angle": "joining"},
    ])
    return answers


def test_a_draft_is_only_a_file_until_accepted(world):
    from core.channels import read_raw
    record = drafts.create("science for teenagers")
    assert drafts.load(record["id"])["channel"]["name_options"][0] == "Orbit Notes"
    assert [v["voice_id"] for v in record["voices"]] == [VOICE_IDS[2], VOICE_IDS[0], VOICE_IDS[4]]
    assert read_raw() == {}


def test_accepting_creates_a_channel_that_can_make_a_video(world):
    from core import curriculum
    from core.channels import load_channels

    record = drafts.create("science for teenagers")
    channel = drafts.accept(record["id"], {
        "name": "Small Science", "voice": VOICE_IDS[0], "palette": "crimson",
        "target_seconds": "40", "avoid_imagery": ["weapons"],
    })
    assert channel.key == "small_science"
    saved = load_channels()["small_science"]        # validates: it can render
    assert saved.voice == VOICE_IDS[0] and saved.pacing.target_seconds == 40
    assert saved.style.highlight_color == "#FF3B4E"
    assert [s["title"] for s in curriculum.subtopics("small_science")] == [
        "Why you can't see atoms", "What a molecule is"]
    assert drafts.load(record["id"]) is None


def test_a_quote_channel_gets_its_list(world):
    from core import corpus
    world["body"] = model_answer(content_mode="static_corpus", corpus_source="custom",
                                 custom_quotes=["All the world's a stage, and all the men and women merely players. — William Shakespeare",
                                                "The unexamined life is not worth living. — Socrates"])
    record = drafts.create("daily ancient wisdom")
    drafts.accept(record["id"], {"name": "Old Words"})
    assert corpus.count("old_words") == 2


def test_a_name_that_is_already_taken_is_refused(world):
    first = drafts.create("science for teenagers")
    drafts.accept(first["id"], {"name": "Small Science"})
    second = drafts.create("science for teenagers")
    with pytest.raises(ConfigError):
        drafts.accept(second["id"], {"name": "Small Science"})
    assert drafts.load(second["id"]) is not None, "a refused accept keeps the draft"


class TestPages:
    def test_pitch_review_accept(self, world, monkeypatch):
        from web import create_app
        app = create_app()
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        client = app.test_client()
        html = client.get("/channels/new").get_data(as_text=True)
        token = html.split('name="csrf-token" content="')[1].split('"')[0]

        response = client.post("/channels/pitch", data={"csrf_token": token,
                                                        "pitch": "science for teenagers"})
        assert response.status_code == 302
        review_url = response.headers["Location"]
        page = client.get(review_url).get_data(as_text=True)
        assert "Orbit Notes" in page and "What things are made of" in page
        assert "aren't built yet" in page      # diagrams flagged honestly

        draft_id = review_url.rstrip("/").split("/")[-1]
        response = client.post(f"/channels/drafts/{draft_id}/accept", data={
            "csrf_token": token, "name_choice": "__custom__", "name_custom": "My Science",
            "voice": VOICE_IDS[1], "palette": "cool_teal", "style_prompt": "Edited prompt.",
            "target_seconds": "45", "segment_count": "3", "speed": "1.0",
            "avoid_imagery": "weapons, Gore",
        })
        assert response.status_code == 302 and "/channels/my_science" in response.headers["Location"]
        from core.channels import load_channels
        saved = load_channels()["my_science"]
        assert saved.style_prompt == "Edited prompt." and saved.avoid_imagery == ["weapons", "gore"]
