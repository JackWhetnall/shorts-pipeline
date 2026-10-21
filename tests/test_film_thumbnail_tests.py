"""
Film thumbnail tests run by the app (core.thumbnail_tests, decision 117).
The owner, of the Studio A/B tests: "the A/B testing is something i need
you to do, providing the thumbnails and titles to check for this. can it
be done over the API or does this also have to be manual?" Studio's test
can't be driven through the API, so films are rotated like shorts:

- films planned within a week share a style or refine round, for more
  impressions; a content round is one film's own;
- a film starts rotating once it's out, and only once click-through can
  be measured, on its own variant straight away (decision 125: every
  film had shown A, so nothing looked tested);
- a content round's titles change with its thumbnails, when the channel
  may be managed, and the winning title becomes the film's;
- any other round's films have their titles tested on their own
  schedule, offset from the thumbnails, and judged apart;
- a round is judged when its films have rotated and the figures are in;
  a tie crowns no style;
- a discarded film doesn't hold its round up.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core import gallery, reach, thumbnail_tests as tt, youtube
from pipeline import thumbnail_variants as tv

DAY = 86400
T0 = 1_000_000_000.0          # a time to start from (0 means "now" to the code)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(tt, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(reach, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    monkeypatch.setattr(tv, "render_long", lambda channel, video, recipe, out: out.write_bytes(b"j") or out)
    monkeypatch.setattr("pipeline.documentary.thumbs.other_angles", lambda video: [
        {"title": "Second title", "words": "SECOND WORDS", "subject": ""},
        {"title": "Third title", "words": "THIRD WORDS", "subject": ""}])
    sent = {"thumbs": [], "titles": [], "manage": True}
    monkeypatch.setattr(youtube, "set_thumbnail", lambda key, vid, path: sent["thumbs"].append((vid, path.name)))
    monkeypatch.setattr(youtube, "set_title", lambda key, vid, title: sent["titles"].append((vid, title)))
    monkeypatch.setattr(youtube, "connection", lambda key: {"connected": True, "manage": sent["manage"]})
    monkeypatch.setattr("pipeline.documentary.title_variants.write", lambda title, about: {
        "B": f"{title} statement", "C": f"{title} to you"})
    monkeypatch.setattr("pipeline.documentary.title_variants.about_film", lambda path: "")
    channel = SimpleNamespace(key="why", publishing=SimpleNamespace(thumbnail_tests=True))
    films = []
    for n in range(5):
        film = tmp_path / "out" / "why" / "longform" / f"2026-10-1{n}" / f"film_{n}.mp4"
        film.parent.mkdir(parents=True)
        film.write_bytes(b"film")
        film.with_name(f"film_{n}_production.json").write_text(json.dumps({"documentary": True}))
        gallery.save_title_and_description(film, f"Film {n}", "About it.")
        films.append(film)
    return channel, films, sent


def _out(film, n):
    gallery.save_publish_info(film, {"youtube_url": f"https://youtu.be/vid{n:08d}"})


def _measurable(on=True):
    reach._save("why", {"videos": {}, "fetched": [], **({"job_id": "j1"} if on else {})})


def test_a_doc_round_left_for_studio_loads_as_a_film_round(world, tmp_path):
    path = tmp_path / "channels" / "why" / "thumbnail_tests.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"rounds": [{"id": "r1", "kind": "studio", "doc": True, "status": "running",
                                            "variants": [], "videos": []},
                                           {"id": "r2", "kind": "studio", "status": "running",
                                            "variants": [], "videos": []}]}))
    kinds = [r["kind"] for r in tt.load("why")["rounds"]]
    assert kinds == ["film", "studio"]                         # a long quiz's stays Studio's


def test_films_planned_within_a_week_share_a_style_round(world):
    channel, films, _ = world
    rounds = [tt.studio_round(channel, f) for f in films]
    assert len({r["id"] for r in rounds[:tt.FILM_ROUND_SIZE]}) == 1      # four films, one round
    assert rounds[4]["id"] != rounds[0]["id"]                            # a fifth starts the next
    shared = tt.load("why")["rounds"][0]
    assert [v["stem"] for v in shared["videos"]] == [f.stem for f in films[:4]]
    assert all(tv.variant_path(f, l).exists() for f in films[:4] for l in "ABC")


def test_a_content_round_is_one_films_own(world):
    channel, films, _ = world
    tt.update("why", lambda data: tt.program(data).update(phase="content"))
    first, second = tt.studio_round(channel, films[0]), tt.studio_round(channel, films[1])
    assert first["id"] != second["id"] and first["variants"][1]["title"] == "Second title"


def test_a_film_starts_rotating_once_its_out_and_its_figures_can_be_read(world):
    channel, films, sent = world
    tt.studio_round(channel, films[0])
    _measurable(False)
    _out(films[0], 0)
    tt.rotate(channel, 1_000.0)
    assert not tt.load("why")["rounds"][0]["videos"][0].get("video_id")   # nothing to measure it by yet
    _measurable()
    tt.rotate(channel, 1_000.0)
    video = tt.load("why")["rounds"][0]["videos"][0]
    assert video["video_id"] == "vid00000000" and video["log"] == [[1_000.0, "A"]] and sent["thumbs"] == []
    tt.rotate(channel, 1_000.0 + 3 * DAY)
    assert sent["thumbs"] == [("vid00000000", "film_0_thumb_b.jpg")]


def test_a_content_round_changes_titles_with_thumbnails_when_it_may(world):
    channel, films, sent = world
    tt.update("why", lambda data: tt.program(data).update(phase="content"))
    tt.studio_round(channel, films[0])
    _measurable()
    _out(films[0], 0)
    tt.rotate(channel, T0)
    tt.rotate(channel, T0 + 3 * DAY)
    assert sent["titles"] == [("vid00000000", "Second title")]       # its own, not a written one
    tt.rotate(channel, T0 + 9 * DAY)                # back to A: the title it went out with
    assert sent["titles"][-1] == ("vid00000000", "Film 0")
    sent["manage"] = False                          # without the permission, thumbnails only
    tt.rotate(channel, T0 + 12 * DAY)
    assert len(sent["titles"]) == 2 and sent["thumbs"][-1][1] == "film_0_thumb_b.jpg"


def test_a_round_is_judged_when_its_films_have_rotated_and_the_winner_kept(world, monkeypatch):
    channel, films, sent = world
    tt.update("why", lambda data: tt.program(data).update(phase="content"))
    round_ = tt.studio_round(channel, films[0])
    _measurable()
    _out(films[0], 0)
    start = 1_000_000_000.0
    tt.rotate(channel, start)
    joined = tt.load("why")["rounds"][0]["videos"][0]["joined"]

    def day(n):
        return datetime.fromtimestamp(joined + n * DAY, timezone.utc).date().isoformat()
    # B (days 3 to 5 and 12 to 14 for an offset of 0, the first of each a change) clicks best.
    figures = {day(n): (150, 0.08 if n in (4, 5, 13, 14) else 0.03) for n in range(1, 21)}
    monkeypatch.setattr(reach, "days", lambda key, vid: figures)
    for n in range(0, 22):
        tt.rotate(channel, joined + n * DAY + 3600)
    assert tt.finish_rotations(channel, joined + 10 * DAY) == []            # still rotating
    assert tt.finish_rotations(channel, joined + 30 * DAY) == [round_["id"]]
    tt.rotate(channel, joined + 30 * DAY)
    assert sent["thumbs"][-1] == ("vid00000000", "film_0_thumb_b.jpg")
    assert sent["titles"][-1] == ("vid00000000", "Second title")
    assert gallery.load_publish_info(films[0])["title"] == "Second title"   # the winner is its title now


def test_a_rounds_films_start_on_a_b_and_c_in_turn(world):
    channel, films, sent = world
    for f in films[:3]:
        tt.studio_round(channel, f)
    _measurable()
    for n in range(3):
        _out(films[n], n)
    tt.rotate(channel, T0)
    videos = tt.load("why")["rounds"][0]["videos"]
    assert [v["log"][-1][1] for v in videos[:3]] == ["A", "B", "C"]
    assert sent["thumbs"] == [("vid00000001", "film_1_thumb_b.jpg"), ("vid00000002", "film_2_thumb_c.jpg")]


def test_films_in_different_rounds_dont_all_start_on_a(world):
    channel, films, sent = world
    tt.update("why", lambda data: tt.program(data).update(phase="content"))     # a round each
    for n in range(3):
        tt.studio_round(channel, films[n])
        _out(films[n], n)
    _measurable()
    tt.rotate(channel, T0)
    assert [r["videos"][0]["log"][-1][1] for r in tt.load("why")["rounds"]] == ["A", "B", "C"]


def test_titles_are_tested_on_their_own_schedule_outside_a_content_round(world):
    channel, films, sent = world
    for f in films[:2]:
        tt.studio_round(channel, f)
    _measurable()
    _out(films[0], 0)
    _out(films[1], 1)
    tt.rotate(channel, T0)                          # out; their titles are written on the next pass
    tt.rotate(channel, T0 + 60)
    videos = tt.load("why")["rounds"][0]["videos"]
    assert videos[0]["titles"] == {"B": "Film 0 statement", "C": "Film 0 to you"}
    # One segment on from the thumbnail for the first film, two for the
    # second, so a title doesn't always share its turn with one thumbnail.
    assert [v["title_log"][-1][1] for v in videos[:2]] == ["B", "A"]
    assert [v["log"][-1][1] for v in videos[:2]] == ["A", "B"]
    assert sent["titles"] == [("vid00000000", "Film 0 statement")]
    tt.rotate(channel, T0 + 3 * DAY)
    assert sent["titles"][-1] == ("vid00000001", "Film 1 statement")
    sent["manage"] = False                          # without the permission, no title changes
    tt.rotate(channel, T0 + 6 * DAY)
    assert len(sent["titles"]) == 3


def test_a_title_that_clicks_clearly_better_is_kept_and_learnt(world, monkeypatch):
    channel, films, sent = world
    tt.studio_round(channel, films[0])
    _measurable()
    _out(films[0], 0)
    tt.rotate(channel, T0)
    joined = tt.load("why")["rounds"][0]["videos"][0]["joined"]

    def day(n):
        return datetime.fromtimestamp(joined + n * DAY, timezone.utc).date().isoformat()
    for n in range(0, 22):
        tt.rotate(channel, joined + n * DAY + 3600)
    # The first film's title runs one segment ahead: C is up on days 3 to 5
    # and 12 to 14, the first of each a change.
    figures = {day(n): (150, 0.09 if n in (4, 5, 13, 14) else 0.03) for n in range(1, 21)}
    monkeypatch.setattr(reach, "days", lambda key, vid: figures)
    added = []
    monkeypatch.setattr("core.lessons.add", lambda key, new, source="": added.extend(new))
    assert len(tt.finish_rotations(channel, joined + 30 * DAY)) == 1
    data = tt.load("why")
    assert data["rounds"][0]["result"]["title_winner"] == "C" and data["title_formats"]["C"]["wins"] == 1
    tt.rotate(channel, joined + 30 * DAY)
    assert sent["titles"][-1] == ("vid00000000", "Film 0 to you")
    assert gallery.load_publish_info(films[0])["title"] == "Film 0 to you"     # the winner is its title now
    assert added and "to the viewer" in added[0]


def test_a_tie_crowns_no_style(world):
    data = {"recipe": {}, "steps": {}, "tried": {}, "rounds": []}
    variants = tt.doc_variants(data)
    round_ = {"kind": "film", "status": "done", "doc": True, "phase": "style", "variants": variants, "result": {}}
    tt.doc_learn(data, round_, "A", clear=False)
    program = tt.program(data)
    assert program["defences"] == 0 and program["families"]["band"]["rounds"] == 1
    assert program["families"]["panel"]["wins"] == 0


def test_a_discarded_film_doesnt_hold_its_round_up(world, monkeypatch):
    channel, films, _ = world
    round_ = tt.studio_round(channel, films[0])
    tt.studio_round(channel, films[1])
    _measurable()
    _out(films[0], 0)
    gallery.set_discarded(films[1], True)
    tt.rotate(channel, T0)
    monkeypatch.setattr(reach, "days", lambda key, vid: {})
    assert tt.finish_rotations(channel, T0 + 40 * DAY) == []                # judged, but on nothing
    done = tt.load("why")["rounds"][0]
    assert done["id"] == round_["id"] and done["status"] == "done"
    assert done["result"]["verdict"] == "too few impressions to tell"


def test_a_films_page_says_how_its_test_is_going(world):
    channel, films, _ = world
    round_ = tt.studio_round(channel, films[0])
    assert tt.film_status("why", tt.load("why")["rounds"][0], films[0].stem)["state"] == "waiting"
    _measurable()
    _out(films[0], 0)
    tt.rotate(channel, T0)
    status = tt.film_status("why", tt.load("why")["rounds"][0], films[0].stem, now=T0 + 6 * DAY)
    assert status["state"] == "rotating" and status["day"] == 7 and status["days"] == tt.FILM_DAYS
    assert round_["kind"] == "film"


def test_a_title_change_keeps_the_rest_of_the_videos_details(monkeypatch):
    calls = []

    class Reply:
        status_code = 200

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data
    monkeypatch.setattr(youtube, "access_token", lambda key: "t")
    snippet = {"title": "Old", "description": "Words", "tags": ["a"], "categoryId": "27",
               "publishedAt": "2026-10-13", "thumbnails": {}, "channelId": "c"}
    monkeypatch.setattr(youtube.requests, "get", lambda url, params, headers, timeout: Reply({"items": [{"snippet": snippet}]}))
    monkeypatch.setattr(youtube.requests, "put", lambda url, params, headers, json, timeout:
                        calls.append(json) or Reply({}))
    youtube.set_title("why", "vid", "New <title>")
    sent = calls[0]["snippet"]
    assert sent == {"title": "New title", "description": "Words", "tags": ["a"], "categoryId": "27"}


def test_a_written_title_that_breaks_the_rules_is_asked_for_again_never_cut(monkeypatch):
    # Found on 21 Oct: titles cut to sixty characters mid-word ("...mapped
    # in detail, whi"), and a "You Won't Believe".
    from pipeline.documentary import title_variants
    answers = [{"statement": "Most of the ocean floor has never been mapped in detail, which is odd",
                "viewer": "You Won't Believe How Little We Know"},
               {"statement": "We Mapped Mars Before Our Own Ocean Floor", "viewer": "The Seabed You've Never Seen"}]
    asked = []
    monkeypatch.setattr(title_variants.llm, "call_json", lambda system, prompt, *a, **k: asked.append(prompt)
                        or answers[len(asked) - 1])
    assert title_variants.write("Why We Know Mars Better", "") == {
        "B": "We Mapped Mars Before Our Own Ocean Floor", "C": "The Seabed You've Never Seen"}
    assert "over 60" in asked[1] and "banned phrase" in asked[1] and "Title Case" in asked[1]
    assert title_variants.problems("Why Rivers Are Salty", "x", "B") and not title_variants.problems(
        "Why Rivers Are Salty", "x", "C")
