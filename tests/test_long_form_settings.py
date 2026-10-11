"""
A long-form channel's own settings page and setup steps (decision 076).

The owner, setting up History Unmystified's first film: there were "so
many settings that are left over from the old workflow", "it is unclear
what is needed and when", and it was unclear whether the setup was done
and whether a "create video" button still had to be pressed. So a
long-form channel gets its own short page holding only what its films
use, its look builder offers only styles its kind of pictures can draw,
and both Settings and Productions say what's done and what's next.
"""

from __future__ import annotations

import json
import re

import pytest

from core.channels import ChannelConfig, channel_to_sparse_dict, load_channels, write_raw

VOICE = "JBFqnCBsd6RMkjVDRZzb"
STYLE = {"approach": "acted", "stage": "storybook", "material": "gouache", "people": "cartoon",
         "mood": "vintage"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    from core import curriculum, production
    config = tmp_path / "channels.json"
    monkeypatch.setattr("core.channels.CHANNELS_JSON_PATH", config)
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    monkeypatch.setattr(production, "CHANNELS_DIR", tmp_path / "channels")

    films = ChannelConfig(key="films", channel_display_name="Films", format="documentary",
                          content_mode="topic", voice=VOICE, style_prompt="Calm history.")
    films.animation.style = dict(STYLE)
    films.pacing.pause_between_segments = 0.7          # a shorts setting the page doesn't show
    films.scenes.share = 40
    films.output_dir = str(tmp_path / "out" / "films")
    shorts = ChannelConfig(key="shorts", channel_display_name="Shorts", voice=VOICE,
                           style_prompt="Quick facts.", content_mode="topic", topics=["owls"])
    shorts.output_dir = str(tmp_path / "out" / "shorts")
    write_raw({"films": channel_to_sparse_dict(films), "shorts": channel_to_sparse_dict(shorts)}, config)

    curriculum.start("films", "History", [{"title": "Rulers", "summary": "", "level": "foundation",
                                           "target_subtopics": 2}])
    curriculum.add_subtopics("films", "u01", [{"title": "Elizabeth I", "angle": "a queen"},
                                              {"title": "Lincoln", "angle": "a president"}])
    from web import create_app
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app.test_client()


def _channel(key="films"):
    return load_channels(validate=False)[key]


def test_a_long_form_channel_has_its_own_short_settings_page(world):
    page = world.get("/channels/films/settings").get_data(as_text=True)
    for wanted in ("Writing brief", "Seconds a picture serves", "Teaser shorts", "Films go out at",
                   # Decision 086: a film's paintings, and a channel that makes its own films.
                   "Real paintings of the period", "Makes its own films"):
        assert wanted in page
    # The shorts page's leftovers: timings after a quoted passage, captions,
    # the money/end-screen panel, the cadence presets.
    for gone in ("pacing_pause_after_first_segment", "Every timing number",
                 "style_captions_enabled", "end_screen_present", "Cadence preset", "scene_share"):
        assert gone not in page
    shorts = world.get("/channels/shorts/settings").get_data(as_text=True)
    assert "Every timing number" in shorts and "Writing brief" not in shorts


def test_saving_it_changes_only_what_it_shows(world):
    html = world.get("/channels/films/settings").get_data(as_text=True)
    token = html.split('name="csrf-token" content="')[1].split('"')[0]
    response = world.post("/channels/films/settings", data={
        "csrf_token": token, "channel_display_name": "Films", "style_prompt": "Slow, calm history.",
        "documentary_present": "1", "format": "documentary", "documentary_pictures": "drawn",
        "documentary_minutes": "14", "documentary_scene_seconds": "18", "documentary_teasers": "1",
        "avoid_imagery": "gore\nweapons", "speed": "0.9",
        "publishing_plan_present": "1", "long_slots": "19:00", "long_weekdays": ["5"],
        "slots": "12:00", "weekdays": ["1", "3"], "sound_present": "1", "sound_music": "on"})
    assert response.status_code == 302
    channel = _channel()
    assert (channel.documentary.minutes, channel.documentary.scene_seconds, channel.documentary.teasers) == (14, 18, 1)
    assert channel.avoid_imagery == ["gore", "weapons"] and channel.publishing.long_slots == ["19:00"]
    assert channel.publishing.long_weekdays == [5] and channel.publishing.weekdays == [1, 3]
    # Untouched: what the page doesn't carry.
    assert channel.pacing.pause_between_segments == 0.7 and channel.scenes.share == 40
    assert channel.animation.style == STYLE and channel.format == "documentary"


def test_a_drawn_channel_is_offered_only_styles_it_can_draw(world):
    from web.blueprints.animation import long_form_context
    with world.application.test_request_context():
        context = long_form_context(_channel())
    approach = next(q for q in context["anim_grammar"]["questions"] if q["id"] == "approach")
    assert {o["id"] for o in approach["options"]} == {"acted", "scenic"}
    assert {sp["answers"]["approach"] for sp in context["anim_starts"]} <= {"acted", "scenic"}
    # Asked only of animation, never of a still.
    assert set(context["anim_hidden_questions"]) == {"presenter", "motion", "words"}
    page = world.get("/channels/films/settings").get_data(as_text=True)
    assert 'data-frame="wide"' in page and 'name="anim_enabled" value="on"' in page


def test_diagram_films_are_shown_as_not_built_rather_than_offered(world):
    from core import long_form
    page = world.get("/channels/films/settings").get_data(as_text=True)
    assert re.search(r'value="diagrams"[^>]*disabled', page) and "Not built yet" in page
    channel = _channel()
    channel.documentary.pictures = "diagrams"
    look = next(s for s in long_form.steps(channel) if s.id == "look")
    assert look.blocked and not look.done


def test_the_setup_says_the_next_thing_is_to_start_the_first_film(world):
    from core import long_form, production
    channel = _channel()
    assert long_form.next_step(channel).id == "first"
    page = world.get("/channels/films/productions").get_data(as_text=True)
    assert "Next: open" in page and "Elizabeth I" in page and "Pitch angles" in page
    film = world.get("/channels/films/productions/t0001").get_data(as_text=True)
    # Decision 081: no paragraph of instructions, the first stage's button and its price.
    assert "Pitch angles" in film and "speed-batch" in film and "Now: press" not in film

    # Started: the list steps back on Productions, and the film says what's next.
    data = production.load("films", "t0001", "Elizabeth I")
    production.made(data, "outline", {"chapters": [], "cast": [], "title_options": []})
    production.save("films", data)
    assert long_form.next_step(_channel()) is None
    assert "lf-setup" not in world.get("/channels/films/productions").get_data(as_text=True)
    film = world.get("/channels/films/productions/t0001").get_data(as_text=True)
    assert "To approve" in film and ">Approve<" in film


def test_without_a_look_the_next_step_is_choosing_one(world):
    from core import long_form
    channel = _channel()
    channel.animation.style = {}
    assert long_form.next_step(channel).id == "look"


def test_never_show_reaches_the_outline_and_every_still(monkeypatch):
    from pipeline.animation import keyframes
    from pipeline.documentary import outline
    channel = ChannelConfig(key="films", format="documentary", content_mode="topic", voice=VOICE,
                            style_prompt="x", avoid_imagery=["gore", "weapons"])
    channel.animation.style = dict(STYLE)
    sent = {}
    monkeypatch.setattr(outline, "call_json", lambda system, user, schema, **k: sent.setdefault("user", user)
                        and {"chapters": [{"title": "One", "says": "s", "shows": "x", "minutes": 1}]})
    monkeypatch.setattr("core.curriculum.find_topic", lambda key, topic: {})
    monkeypatch.setattr(outline, "earlier", lambda key, sid: "")
    outline.write(channel, {"id": "t0001", "title": "Lincoln", "topic": "u01"})
    assert "Never show" in sent["user"] and "gore, weapons" in sent["user"]

    shot = {"framing": "wide", "image": "a field", "elements": []}
    look = {"key": "k", "label": "l", "description": "d"}
    monkeypatch.setattr(keyframes.looks, "style_text", lambda look: "")
    monkeypatch.setattr(keyframes.looks, "frame_rules", lambda look: "")
    text = keyframes.prompt_for(shot, {"elements": {}, "never": ["gore"]}, look, [])
    assert "Never show any of these: gore." in text
    assert "Never show" not in keyframes.prompt_for(shot, {"elements": {}}, look, [])


def test_a_long_form_channel_launches_by_its_own_steps(world):
    """Its films always wait for review, so the shorts' launch (the checks
    proving themselves, then autopilot) could never finish."""
    from core import launch
    stages, grow = launch.stages(_channel())
    assert [s.id for s in stages] == list(launch.LONG_FORM_LAUNCH)
    assert launch.current(stages).id == "first"
    assert {g.id for g in grow} == {"profile", "audit"}
    page = world.get("/channels/films").get_data(as_text=True)
    assert "Let the automatic checks prove themselves" not in page
