"""
The Voice Lab filtered by gender and accent. The owner, on 21 Oct: "it
would be nice to be able to filter the voice lab by gender and
nationality; it is hard to browse at the moment."

- every voice carries ElevenLabs' labels, lower case, the account's from
  their `labels` and the shortlist's from the library's own fields;
- the page offers a filter for each label it has, and each row says
  its own, for the filter to match;
- a Voice Library search asks only for what's wanted, most used first.
"""

from __future__ import annotations

import json

from core import voice_lab


def test_voices_carry_their_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_lab, "LIBRARY_PATH", tmp_path / "library.json")
    assert voice_lab.labels_of({"gender": "Female", "accent": "British", "use_case": "narrative_story"}) == {
        "gender": "female", "accent": "british", "age": "", "use_case": "narrative story"}
    voice_lab.shortlist([{"voice_id": "v1", "name": "Tamsin", "gender": "female", "accent": "british"}])
    assert voice_lab.library_voices()[0]["accent"] == "british"


def test_the_page_filters_by_gender_and_accent(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_lab, "VOICES_CACHE_PATH", tmp_path / "voices.json")
    monkeypatch.setattr(voice_lab, "LIBRARY_PATH", tmp_path / "library.json")
    (tmp_path / "voices.json").write_text(json.dumps([
        {"voice_id": "a", "name": "Old cache, no labels", "category": "premade"},
        {"voice_id": "b", "name": "Tom", "category": "cloned", "gender": "male", "accent": "yorkshire"}]))
    voice_lab.shortlist([{"voice_id": "c", "name": "Tamsin", "gender": "female", "accent": "british"}])
    from web import create_app
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        page = client.get("/voice-lab").get_data(as_text=True)
    assert 'data-filter="gender"' in page and '<option value="female">Female</option>' in page
    assert '<option value="yorkshire">Yorkshire</option>' in page
    assert 'data-gender="female" data-accent="british"' in page and 'data-gender="" data-accent=""' in page


def test_a_library_search_asks_for_what_is_wanted(monkeypatch):
    asked = {}

    class Reply:
        ok = True

        def json(self):
            return {"voices": [{"voice_id": "v", "name": "Verity", "gender": "female", "accent": "british",
                                "age": "young", "use_case": "conversational", "preview_url": "https://x/v.mp3"}]}
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setattr(voice_lab.requests, "get", lambda url, headers, params, timeout: asked.update(params) or Reply())
    found = voice_lab.search_library(gender="female", accent="british")
    assert asked["gender"] == "female" and asked["accent"] == "british" and "use_cases" not in asked
    assert asked["sort"] == "usage_character_count_1y"
    assert found[0]["voice_id"] == "v" and found[0]["age"] == "young" and found[0]["category"] == "library"
