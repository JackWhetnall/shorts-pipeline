"""
Documentaries built to be watched (decision 086).

The owner, after the first History Unmystified film: make the code
changes that make videos "more likely to be successful", keeping costs
low, with viewer numbers and retention mattering more than fact-checking.
The review of that film found: a 62-character title opening on a label;
a thumbnail that was the opening still with the whole title over it; an
opening of a date and the weather; 43% background before the speech the
title promised; long written sentences and a word used nine times; one
kind of picture, each held 14.8 seconds; narration at 118 words a minute.

- the angle (title, thumbnail idea, promise, first line) comes first,
  scored, a long or label-first title marked down;
- the outline keeps the promise, opens cold for a minute at most, and
  turns in every chapter, or is written once more;
- scenes have a medium: drawn, a museum painting, or an animated card;
- an editor's pass finds long sentences, worn-out words and an opening
  that doesn't keep the angle, and rewrites the worst chapters;
- several shots are cut from each still;
- the thumbnail is designed: a subject and four words at most;
- each film is scored against the recipe, and its viewers' drops are put
  on the scene playing, and become lessons for the next film;
- a channel can make its own films, the finished video still waiting
  for a look.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from core import curriculum, lessons, production, retention, scorecard
from core.channels import ChannelConfig
from pipeline.documentary import cards, editor, media, pitch, shots, thumbs
from pipeline.documentary import outline as outlines
from pipeline.documentary import script as scripts


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    monkeypatch.setattr(production, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(lessons, "CHANNELS_DIR", tmp_path / "channels")
    curriculum.start("doc", "Days", [{"title": "Cities", "summary": "", "level": "foundation", "target_subtopics": 5}])
    curriculum.add_subtopics("doc", "u01", [{"title": "A Day in Plague London", "angle": "1665"},
                                            {"title": "A Day in Rome"}])
    channel = ChannelConfig(key="doc", channel_display_name="One Day In History", content_mode="topic",
                            format="documentary", voice="21m00Tcm4TlvDq8ikWAM", style_prompt="Second person.")
    channel.documentary.minutes = 4
    channel.documentary.scene_seconds = 10
    return channel, curriculum.subtopics("doc")[0]


def _angle(title, words="5 A.M.", curiosity=8, scores=None):
    return {"title": title, "thumbnail": {"subject": "a frightened apprentice", "words": words},
            "promise": "What a day in plague London was like.", "hook": "It's five in the morning and the "
            "bells have started counting the dead.", "open_loop": "Will you make it to nightfall?",
            "scores": scores or {"curiosity": curiosity, "familiarity": 7, "clarity": 8, "payoff": 8}, "why": ""}


# --- the angle ---------------------------------------------------------------------------

def test_a_long_or_label_first_title_is_marked_down_and_the_best_angle_chosen():
    assert pitch.title_problems("Lincoln and the Gettysburg Address: The Speech Nobody Expected") == [
        "62 characters (a phone shows about 55)", "opens on a label"]
    assert pitch.title_problems("Why Lincoln's 2-Minute Speech Beat a 2-Hour One") == []
    # The title, or its thumbnail's words, names what the film is about.
    assert pitch.title_problems("The Morning Your Master Doesn't Come Down", "He was fine",
                                "A Day in Plague London, 1665") == ["doesn't name its subject (1665, london, plague)"]
    assert pitch.title_problems("The Baker Who Couldn't Flee the Plague", "", "A Day in Plague London, 1665") == []
    out = pitch.clean({"angles": [
        _angle("Lincoln and the Gettysburg Address: The Speech Nobody Expected", curiosity=9),
        _angle("Why You Wouldn't Survive a Day in Plague London", words="you would not last long"),
        _angle("A Day in London", curiosity=4)]})
    assert out["chosen"] == 1
    assert out["angles"][1]["thumbnail"]["words"] == "you would not last"          # four words at most
    assert out["angles"][0]["score"] < out["angles"][1]["score"]


def test_a_film_started_before_angles_carries_on(world):
    channel, row = world
    production.update("doc", row["id"], lambda d: production.made(d, "outline", {"chapters": [], "cast": []}))
    data = production.load("doc", row["id"])
    assert production.state(data, "pitch") == "approved" and data["stages"]["pitch"].get("legacy")
    assert production.can_start(data, "outline") and production.chosen_angle(data) == {}


def test_choosing_another_angle_makes_what_followed_from_the_first_stale(world):
    channel, row = world
    made = pitch.clean({"angles": [_angle("Why You Wouldn't Survive a Day in London"), _angle("Plague Day", curiosity=3)]})
    production.update("doc", row["id"], lambda d: production.made(d, "pitch", made))
    production.approve("doc", row["id"], "pitch")
    production.update("doc", row["id"], lambda d: production.made(d, "outline", {"chapters": [], "cast": []}))
    production.update("doc", row["id"], lambda d: production.mark(d, "pitch", "ready"))
    data = production.approve("doc", row["id"], "pitch", choice=1)
    assert production.chosen_angle(data)["title"] == "Plague Day"
    assert production.state(data, "outline") == "stale"


# --- the outline ---------------------------------------------------------------------------

def _outline(first_minutes=0.8, turns=True, loops=("Will you live?",)):
    return {"title_options": ["T"], "through_line": "x", "promise": "p", "open_loops": list(loops),
            "visual_concept": "v", "cast": [],
            "chapters": [{"title": "Five a.m.", "says": "s", "turn": "t" if turns else "", "shows": "w",
                          "minutes": first_minutes},
                         {"title": "Noon", "says": "s", "turn": "t" if turns else "", "shows": "w",
                          "minutes": 4 - first_minutes}]}


def test_an_outline_that_opens_slowly_or_never_turns_is_written_once_more_keeping_the_angle(world, monkeypatch):
    channel, row = world
    assert outlines.problems(outlines.clean(_outline(), 4), 4) == []
    slow = outlines.problems(outlines.clean(_outline(first_minutes=2.0, turns=False, loops=()), 4), 4)
    assert len(slow) == 3 and "cold open" in slow[0]
    calls = []

    def fake(system, user, schema, **kw):
        calls.append(user)
        return _outline(first_minutes=2.0) if len(calls) == 1 else _outline()
    monkeypatch.setattr(outlines, "call_json", fake)
    out = outlines.write(channel, row, angle=_angle("Why You Wouldn't Survive a Day in London"))
    assert len(calls) == 2 and "broke these rules" in calls[1] and "Will you make it to nightfall?" in calls[0]
    assert out["title_options"][0] == "Why You Wouldn't Survive a Day in London"
    assert out["chapters"][0]["minutes"] <= outlines.COLD_OPEN_MAX


# --- scenes and their media ------------------------------------------------------------------

def test_a_scene_is_drawn_unless_its_card_or_painting_can_be_shown(world):
    outline = outlines.clean(_outline(), 4)
    raw = {"scenes": [
        {"chapter": 1, "direction": "d", "cast": [], "framing": "wide", "camera": "push_in", "caption": "",
         "narration": "You wake.", "medium": "card", "art_query": "",
         "card": {"kind": "map", "heading": "London", "value": "", "caption": "1665", "items": [], "lat": 51.5, "lon": -0.12}},
        {"chapter": 1, "direction": "d", "cast": [], "framing": "wide", "camera": "push_in", "caption": "",
         "narration": "Bread costs a penny.", "medium": "card", "art_query": "",
         "card": {"kind": "number", "heading": "", "value": "", "caption": "", "items": [], "lat": 0, "lon": 0}},
        {"chapter": 2, "direction": "d", "cast": [], "framing": "wide", "camera": "push_in", "caption": "",
         "narration": "The market.", "medium": "painting", "art_query": "Dutch market",
         "card": {"kind": "none", "heading": "", "value": "", "caption": "", "items": [], "lat": 0, "lon": 0}}],
        "description": ""}
    with_art = scripts.clean(raw, outline, paintings=True)["scenes"]
    assert [s["medium"] for s in with_art] == ["card", "picture", "painting"]   # an empty number isn't a card
    assert with_art[0]["card"]["lat"] == 51.5 and with_art[2]["art_query"] == "Dutch market"
    assert [s["medium"] for s in scripts.clean(raw, outline, paintings=False)["scenes"]] == ["card", "picture", "picture"]
    assert scripts.clean_card({"kind": "map", "heading": "Nowhere", "lat": 0, "lon": 0}) == {}


def test_a_painting_that_cant_be_found_is_drawn_instead(world, monkeypatch, tmp_path):
    channel, row = world
    from pipeline import artwork
    monkeypatch.setattr(artwork, "search", lambda q: [])
    scenes = [{"narration": "x", "medium": "painting", "art_query": "plague doctor"},
              {"narration": "y", "medium": "picture"}]
    made, credits, draw_instead = media.make(channel, scenes, tmp_path)
    assert made == {} and draw_instead == [0]


def test_a_painting_is_set_whole_into_the_widescreen_frame():
    tall = Image.new("RGB", (300, 600), (200, 40, 40))
    framed = media.compose(tall)
    assert framed.size == media.FRAME
    assert framed.getpixel((media.FRAME[0] // 2, media.FRAME[1] // 2))[0] > 150      # the work, in the middle
    assert framed.getpixel((10, 10))[0] < 120                                     # a darkened copy behind


def test_every_card_kind_builds_with_its_words():
    style = {"key": "clean_flat", "colors": {"ink": "#222222", "ink_soft": "#555555", "label_fill": "#FFFFFF",
             **{f"accent{i}": "#E3A93D" for i in range(1, 6)}}, "background": {"color": "#FBF4E6"},
             "font_display": "Segoe UI Black", "font_text": "Candara"}
    pages = {
        "number": {"kind": "number", "heading": "A day's pay", "value": "6d", "caption": "for twelve hours"},
        "versus": {"kind": "versus", "items": ["Baker|4 a.m.", "Lord|10 a.m."]},
        "quote": {"kind": "quote", "caption": "Bring out your dead", "heading": "the cart men"},
        "timeline": {"kind": "timeline", "items": ["1665|Plague", "1666|Fire"]},
        "list": {"kind": "list", "heading": "What could kill you", "items": ["Plague", "Fire", "Rats"]}}
    for kind, card in pages.items():
        html = cards.build(card, style, 6.0)
        for word in (card.get("caption") or card.get("heading") or card["items"][0].split("|")[-1]).split()[:1]:
            assert word in html, kind
        assert "TEMPLATE_DURATION = 6.000" in html and "1920px" in html


def test_a_map_picks_out_the_country_the_place_is_in():
    from pipeline import pictures
    if not (pictures.FOLDER / "ne_50m_admin_0_countries.geojson").exists():
        pytest.skip("Natural Earth shapes aren't cached here")
    paths, home, (x, y) = cards.map_svg(51.507, -0.128)
    assert home == "United Kingdom" and abs(x - cards.SIZE[0] / 2) < 1 and abs(y - cards.SIZE[1] / 2) < 1
    assert any(is_home for is_home, _ in paths) and len(paths) > 5


# --- the editor ------------------------------------------------------------------------------

def test_the_editor_finds_long_sentences_worn_words_and_an_opening_that_isnt_the_angle():
    outline = outlines.clean(_outline(), 4)
    long_line = ("And so the whole of the long and difficult afternoon passed for the small apprentice in the "
                 "small bakery beside the small river while the small chimes rang on and on without end.")
    script = {"scenes": [{"chapter": 1, "narration": "The sun was up over London.", "medium": "picture"}]
              + [{"chapter": 2, "narration": long_line, "medium": "picture"} for _ in range(3)]
              + [{"chapter": 2, "narration": "A card.", "medium": "card"},
                 {"chapter": 2, "narration": "Another card.", "medium": "card"}]}
    found = editor.checks(script, outline, _angle("T"))
    assert any("open with the chosen first line" in p for p in found[1])
    assert any("Sentences average" in p for p in found[2])
    assert any('"small" is used 12 times' in p for p in found[2])
    assert any("Two cards in a row" in p for p in found[2])


def test_the_editor_rewrites_the_weakest_chapters_and_says_why(world, monkeypatch):
    channel, row = world
    outline = outlines.clean(_outline(), 4)
    script = {"scenes": [{"chapter": 1, "narration": "It's five in the morning and the bells have started counting the dead.",
                          "medium": "picture"},
                         {"chapter": 2, "narration": "Things happened.", "medium": "picture"}], "description": ""}
    monkeypatch.setattr(editor, "critique", lambda s, o, a=None: {1: {"score": 8.5, "fix": ""},
                                                                  2: {"score": 4.0, "fix": "Say what the bread cost."}})
    rewritten = []

    def fake_rewrite(channel, title, outline, script, chapter, note, angle=None):
        rewritten.append((chapter, note))
        return {**script, "scenes": [s if s["chapter"] != chapter else {**s, "narration": "Bread was a penny."}
                                     for s in script["scenes"]]}
    monkeypatch.setattr(scripts, "rewrite_chapter", fake_rewrite)
    out = editor.edit(channel, "T", outline, script, _angle("T"))
    assert [c for c, _ in rewritten] == [2] and "Say what the bread cost." in rewritten[0][1]
    assert out["edits"][0]["chapter"] == 2 and out["scenes"][1]["narration"] == "Bread was a penny."


# --- shots, thumbnail, scorecard -------------------------------------------------------------

def test_a_long_scene_is_cut_into_shots_from_its_still(tmp_path):
    still = tmp_path / "kf_00.jpg"
    Image.new("RGB", (320, 180), (90, 120, 200)).save(still)
    assert shots.box(0.95, 0.05, 5.0) == [0.5455, 0.0, 0.4545, 0.4545]            # kept inside, zoom capped
    assert shots.count(4.0, 2) == 1 and shots.count(11.0, 2) == 2 and shots.count(17.0, 2) == 3
    assert shots.count(17.0, 0) == 1                                              # nothing worth a closer look
    cut = shots.cut(still, [[0.1, 0.1, 0.5, 0.5], [0.4, 0.3, 0.5, 0.5]], 16.0, "push_in", tmp_path, "s000")
    assert [round(s, 2) for _, s, _ in cut] == [5.33, 5.33, 5.33]
    assert cut[0][0] == still and Image.open(cut[1][0]).size == (320, 180) and cut[1][2] == "pan_right"


def test_shots_already_planned_arent_paid_for_again(tmp_path, monkeypatch):
    still = tmp_path / "kf_00.jpg"
    Image.new("RGB", (320, 180)).save(still)
    calls = []

    def fake(system, content, schema, **kw):
        calls.append(1)
        return {"pictures": [{"picture": 1, "framings": [{"x": 0.3, "y": 0.4, "zoom": 1.8}]}]}
    monkeypatch.setattr(shots, "call_json", fake)
    first, problem = shots.plan({0: still}, tmp_path / "shots.json")
    again, _ = shots.plan({0: still}, tmp_path / "shots.json")
    assert len(calls) == 1 and first == again and len(first[0]) == 1 and problem == ""


def test_the_thumbnail_is_a_subject_and_a_few_big_words(tmp_path):
    picture = tmp_path / "art.jpg"
    Image.new("RGB", (1536, 864), (200, 150, 100)).save(picture)
    made = thumbs.compose(picture, "you would not last a day", {"accent1": "#FFD400", "accent2": "#2E8B8B"})
    assert made.size == thumbs.SIZE
    assert made.getpixel((100, 360))[0] > 150                                     # the picture on the left
    assert made.getpixel((1260, 20)) == (22, 24, 30)                              # the words' panel
    assert thumbs._lines("2 MIN BEAT 2 HOURS") == ["2 MIN", "BEAT 2 HOURS"]
    assert thumbs.compose(picture, "", {}).size == thumbs.SIZE                     # no words: the picture alone


def test_a_film_is_scored_against_the_recipe():
    angle = _angle("Why You Wouldn't Survive a Day in Plague London")
    scenes = [{"narration": "It's five in the morning and the bells have started counting the dead."}]
    numbers = {"video_seconds": 600, "pictures": 110, "longest_hold": 7.5, "first_30s_pictures": 6,
               "words": 1500, "media": ["card", "drawn", "painting"]}
    card = {c["key"]: c for c in scorecard.score(angle["title"], angle, scenes, numbers)}
    assert all(c["ok"] for c in card.values()), [c for c in card.values() if not c["ok"]]
    slow = {c["key"]: c for c in scorecard.score("Lincoln and the Gettysburg Address: The Speech Nobody Expected",
                                                 {}, [{"narration": "It is the morning of November 19th."}],
                                                 {"video_seconds": 741, "pictures": 50, "longest_hold": 22,
                                                  "first_30s_pictures": 2, "words": 1451, "media": ["drawn"]})}
    assert [k for k, c in slow.items() if c["ok"] is False] == [
        "title", "first_30s", "hold", "per_minute", "wpm", "kinds"]
    assert slow["wpm"]["value"] == "117"


# --- viewers and lessons ---------------------------------------------------------------------

def test_where_viewers_left_is_put_on_the_scene_playing():
    curve = [[0.0, 1.0], [0.05, 0.62], [0.3, 0.55], [0.4, 0.38], [0.99, 0.30]]
    times = [[0, 30], [30, 180], [180, 240], [240, 600]]
    found = retention.summary(curve, times, 600)
    assert found["kept_30s"] == 62 and found["end"] == 30
    assert found["drops"][0]["scene"] == 2 and found["drops"][0]["lost"] == 17.0


def test_lessons_are_kept_short_and_read_by_the_writers(world):
    channel, row = world
    for n in range(10):
        lessons.add("doc", [f"Lesson {n}"], source=f"film_{n}")
    assert len(lessons.load("doc")) == lessons.MAX_LESSONS and lessons.texts("doc")[-1] == "Lesson 9"
    assert lessons.learned_from("doc", "film_3") and not lessons.learned_from("doc", "film_x")
    lessons.replace("doc", ["Open on the surprise.", "", "Lesson 9"])
    assert lessons.texts("doc") == ["Open on the surprise.", "Lesson 9"]
    assert "Open on the surprise." in lessons.for_prompt("doc")


def test_a_week_old_film_teaches_the_channel_once(world, monkeypatch, tmp_path):
    channel, row = world
    from core import gallery
    from datetime import datetime, timedelta, timezone
    video = tmp_path / "out" / "film.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    video.with_name("film_production.json").write_text(json.dumps(
        {"documentary": True, "subtopic_id": row["id"], "scenes": [[0, 30], [30, 300]]}))
    week_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    monkeypatch.setattr(gallery, "load_publish_info", lambda p: {"title": "T", "published_at": week_ago})
    monkeypatch.setattr(gallery, "load_stats", lambda p: {"curve": [[0, 1], [0.1, 0.4], [0.99, 0.3]]})
    monkeypatch.setattr(gallery, "load_report", lambda p: {"video_seconds": 300})
    calls = []

    def fake(system, user, schema, **kw):
        calls.append(user)
        return {"lessons": ["Say what the film is about in the first ten seconds."]}
    monkeypatch.setattr("pipeline.llm.call_json", fake)
    assert retention.learn(channel, video) == ["Say what the film is about in the first ten seconds."]
    assert retention.learn(channel, video) == [] and len(calls) == 1
    assert "Still watching after 30 seconds" in calls[0]


# --- a channel that makes its own films ------------------------------------------------------

@pytest.fixture
def auto(world, monkeypatch):
    from core import auto_films, jobs
    channel, row = world
    channel.documentary.auto_make = True
    channel.publishing.enabled = True
    channel.animation.style = {"approach": "acted"}
    started = []
    monkeypatch.setattr(jobs, "active_in_order", lambda: [])
    monkeypatch.setattr(jobs, "start_job", lambda key, seed, ahead=True, behind=False: started.append(seed) or "j")
    monkeypatch.setattr("core.storyboard.upcoming", lambda channel, count=1: [row][:count])
    return auto_films, channel, row, started


def test_it_starts_a_stage_approves_it_when_ready_and_starts_the_next(auto):
    auto_films, channel, row, started = auto
    assert "started the angle" in auto_films.step(channel) and started[-1]["stage"] == "pitch"
    production.update("doc", row["id"], lambda d: production.made(d, "pitch", pitch.clean({"angles": [_angle("T")]})))
    assert "approved the angle" in auto_films.step(channel)
    data = production.load("doc", row["id"])
    assert production.state(data, "pitch") == "approved" and data["history"][-1]["by"] == "autopilot"
    assert "started the outline" in auto_films.step(channel)


def test_it_never_approves_the_finished_video_and_retries_a_failure_once(auto):
    auto_films, channel, row, started = auto
    for stage in ("pitch", "outline", "script", "stills"):
        production.update("doc", row["id"], lambda d, s=stage: production.made(d, s, {} if s != "outline" else
                                                                                {"chapters": [], "cast": []}))
        production.approve("doc", row["id"], stage)
    production.update("doc", row["id"], lambda d: production.made(d, "video", {"path": "x.mp4"}))
    assert auto_films.step(channel) == ""                                         # the owner's look first
    production.update("doc", row["id"], lambda d: production.mark(d, "video", "failed", "boom"))
    assert "started the video" in auto_films.step(channel)
    production.update("doc", row["id"], lambda d: production.mark(d, "video", "failed", "boom"))
    assert auto_films.step(channel) == ""                                         # once, then it's left for you


def test_its_off_unless_asked(auto):
    auto_films, channel, row, started = auto
    channel.documentary.auto_make = False
    assert auto_films.step(channel) == "" and started == []


def test_chapter_titles_read_as_a_chapter_list_not_production_notes():
    assert outlines.chapter_title("Cold Open - Locked In With the Plague") == "Locked In With the Plague"
    assert outlines.chapter_title("Chapter 2: The Oven") == "The Oven"
    assert outlines.chapter_title("Dawn - Bound by Contract") == "Dawn: Bound by Contract"


def test_a_film_waiting_for_a_look_holds_back_the_next_even_if_its_angle_was_pitched_ahead(auto, monkeypatch):
    auto_films, channel, row, started = auto
    for stage in ("pitch", "outline", "script", "stills"):
        production.update("doc", row["id"], lambda d, s=stage: production.made(d, s, {} if s != "outline" else
                                                                                {"chapters": [], "cast": []}))
        production.approve("doc", row["id"], stage)
    production.update("doc", row["id"], lambda d: production.made(d, "video", {"path": "x.mp4"}))
    nxt = curriculum.subtopics("doc")[1]
    monkeypatch.setattr("core.storyboard.upcoming", lambda channel, count=1: [nxt][:count])
    # The scheduler pitched the next film's angle ahead of time.
    production.update("doc", nxt["id"], lambda d: production.made(d, "pitch", pitch.clean({"angles": [_angle("T")]})))
    assert auto_films.step(channel) == "" and started == []
    channel.documentary.ahead = 2
    assert "approved the angle" in auto_films.step(channel)
