"""
Long-form documentaries made in approved stages (pipeline.documentary,
core.production, decision 074).

The owner (6 Oct): a video "should start with a text outline of what the
video is going to talk about, and how it is going to show it ... we then
can generate the full narration script (with stage directions too), as
if it were a play. from there we can generate the still images of the
scenes ... giving a proper storyboard", every stage approved; the look
"extremely consistent between clips in one video, and also between
different videos in a single channel"; and teaser shorts that are "a mini
channel video that leaves the user wanting to see more".

The model calls and picture service are faked; the camera move runs
ffmpeg for real on a tiny picture.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from core import curriculum, production
from core.channels import ChannelConfig
from core.errors import PipelineError
from pipeline.documentary import cast as library
from pipeline.documentary import outline as outlines
from pipeline.documentary import render, run, stills
from pipeline.documentary import script as scripts
from pipeline.documentary import teasers


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    monkeypatch.setattr(production, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(library, "CHANNELS_DIR", tmp_path / "channels")
    curriculum.start("hist", "People", [{"title": "Presidents", "summary": "US", "level": "foundation",
                                         "target_subtopics": 10}])
    curriculum.add_subtopics("hist", "u01", [{"title": "George Washington", "angle": "the reluctant founder"},
                                             {"title": "John Adams"}])
    channel = ChannelConfig(key="hist", channel_display_name="History", content_mode="topic",
                            format="documentary", voice="21m00Tcm4TlvDq8ikWAM", style_prompt="Tell lives well.")
    channel.documentary.minutes = 2
    channel.documentary.scene_seconds = 20
    return channel, curriculum.subtopics("hist")[0]


OUTLINE = {"title_options": ["The Man Who Gave Up Power"], "through_line": "Why he walked away",
           "visual_concept": "Candlelight to dawn", "cast": [
               {"name": "George Washington (president)", "kind": "character", "description": "tall, grey hair, black coat"},
               {"name": "Mount Vernon", "kind": "place", "description": "white house above a river"}],
           "chapters": [{"title": "The surveyor", "says": "Young man.", "shows": "Woods.", "minutes": 1.0},
                        {"title": "The farewell", "says": "He leaves.", "shows": "A hall.", "minutes": 1.0}]}


PITCH = {"angles": [{"title": "Why Washington Walked Away", "thumbnail": {"subject": "his face", "words": "HE QUIT"},
                     "promise": "Why the most powerful man in America gave it up.",
                     "hook": "In 1783 George Washington could have been king. He went home instead.",
                     "open_loop": "Why would anyone give that up?", "scores": {}, "why": "", "score": 8.0}],
         "chosen": 0}


def _scene(chapter, text, cast=()):
    return {"chapter": chapter, "direction": f"A picture of {text}", "cast": list(cast), "framing": "wide",
            "camera": "push_in", "caption": "", "narration": text}


# --- the record --------------------------------------------------------------------

def test_each_stage_waits_for_the_one_before(world):
    channel, row = world
    data = production.load("hist", row["id"], row["title"])
    assert production.current(data) == "pitch" and not production.can_start(data, "outline")
    production.update("hist", row["id"], lambda d: production.made(d, "pitch", PITCH))
    data = production.approve("hist", row["id"], "pitch")
    assert production.current(data) == "outline" and not production.can_start(data, "script")
    production.update("hist", row["id"], lambda d: production.made(d, "outline", OUTLINE))
    with pytest.raises(PipelineError):
        production.approve("hist", row["id"], "script")
    data = production.approve("hist", row["id"], "outline")
    assert production.can_start(data, "script") and production.current(data) == "script"


def test_changing_an_earlier_stage_makes_what_followed_stale(world):
    channel, row = world
    production.update("hist", row["id"], lambda d: production.made(d, "outline", OUTLINE))
    production.approve("hist", row["id"], "outline")
    production.update("hist", row["id"], lambda d: production.made(d, "script", {"scenes": [], "description": ""}))
    data = production.edited("hist", row["id"], "outline", {**OUTLINE, "through_line": "Something else"})
    assert production.state(data, "outline") == "approved"       # the owner's edit is looked at
    assert production.state(data, "script") == "stale"
    assert production.state(data, "stills") == "todo"


# --- outline and script ------------------------------------------------------------

def test_an_outline_is_fitted_to_the_running_time_and_its_cast_kept_once(world):
    data = {"title_options": ["T"], "through_line": "x", "visual_concept": "y",
            "chapters": [{"title": "A", "says": "a", "shows": "s", "minutes": 3},
                         {"title": "B", "says": "b", "shows": "s", "minutes": 1},
                         {"title": "C", "says": "", "shows": "s", "minutes": 1}],
            "cast": [{"name": "Ada", "kind": "character", "description": "d"},
                     {"name": "ada", "kind": "character", "description": "again"}]}
    out = outlines.clean(data, 10)
    assert [c["minutes"] for c in out["chapters"]] == [7.5, 2.5]
    assert [m["name"] for m in out["cast"]] == ["Ada"]


def test_the_outline_writer_sees_the_cast_library_and_the_other_films(world, monkeypatch):
    channel, row = world
    library.merge("hist", "earlier", [{"name": "Martha Washington", "kind": "character", "description": "small, kind"}])
    production.update("hist", "t0002", lambda d: production.made(d, "outline", {**OUTLINE, "through_line": "Adams' temper"}))
    seen = {}

    def fake(system, user, schema, **kw):
        seen["user"] = user
        return OUTLINE
    monkeypatch.setattr(outlines, "call_json", fake)
    outlines.write(channel, row, "start at Valley Forge")
    assert "Martha Washington (character): small, kind" in seen["user"]
    assert "Adams' temper" in seen["user"] and "start at Valley Forge" in seen["user"]


def test_the_script_is_written_a_chapter_at_a_time_each_knowing_the_last(world, monkeypatch):
    channel, row = world
    calls = []

    def fake(system, user, schema, **kw):
        calls.append(user)
        n = len(calls)
        return {"scenes": [{"chapter": 9, "direction": "d", "cast": ["George Washington (president)", "Nobody"],
                            "framing": "wide", "camera": "zoom", "caption": "", "narration": f"Line {n}."}],
                "description": "About him." if n == 2 else ""}
    monkeypatch.setattr(scripts, "call_json", fake)
    monkeypatch.setattr(scripts, "SHORT_OF", 0)          # its chapters are short on purpose
    out = scripts.write(channel, row["title"], OUTLINE)
    assert len(calls) == 2 and "[1] Line 1." in calls[1]
    assert [s["chapter"] for s in out["scenes"]] == [1, 2]
    assert out["scenes"][0]["cast"] == ["George Washington (president)"]     # only the outline's cast
    assert out["scenes"][0]["camera"] == "push_in" and out["description"] == "About him."


def test_one_chapter_can_be_written_again(world, monkeypatch):
    channel, row = world
    script = {"scenes": [_scene(1, "One."), _scene(2, "Two."), _scene(2, "Three.")], "description": "d"}
    monkeypatch.setattr(scripts, "call_json", lambda *a, **k: {
        "scenes": [{"chapter": 2, "direction": "x", "cast": [], "framing": "wide", "camera": "still",
                    "caption": "", "narration": "New two."}], "description": ""})
    out = scripts.rewrite_chapter(channel, row["title"], OUTLINE, script, 2, "shorter")
    assert [s["narration"] for s in out["scenes"]] == ["One.", "New two."]
    assert out["description"] == "d"


# --- consistency -------------------------------------------------------------------

def test_a_cast_member_keeps_one_description_for_the_channels_life(world):
    library.merge("hist", "a", [{"name": "George Washington (president)", "kind": "character",
                                 "description": "tall, grey hair"}])
    kept = library.merge("hist", "b", [{"name": "George Washington (President)", "kind": "character",
                                        "description": "short and bald"}])
    assert kept[0]["description"] == "tall, grey hair" and kept[0]["videos"] == ["a", "b"]


def test_stills_are_drawn_with_the_style_sheet_and_the_casts_sheets(world, monkeypatch, tmp_path):
    channel, row = world
    from pipeline.animation import bible, keyframes
    style_ref = tmp_path / "style.png"
    monkeypatch.setattr(bible, "reference", lambda channel, look, film=False: style_ref)
    monkeypatch.setattr(stills, "look_for", lambda channel, frame="wide": {"identity": "abc", "frame": frame})
    sheets_drawn = []
    monkeypatch.setattr(library, "sheet", lambda channel, look, member, ref: sheets_drawn.append(member["name"])
                        or tmp_path / f"{member['name']}.png")
    drawn = []

    def fake_draw(shot, board, look, ref, sheets, folder, model, fix=None, combined=False):
        drawn.append((shot["index"], sorted(sheets), fix))
        path = Path(folder) / f"kf_{shot['index']:02d}.jpg"
        path.write_bytes(b"x")
        return path
    monkeypatch.setattr(keyframes, "draw", fake_draw)
    monkeypatch.setattr(keyframes, "check", lambda *a: {})
    scenes = [_scene(1, "a", ["George Washington (president)", "Mount Vernon"]), _scene(1, "b", ["Mount Vernon"])]
    out = stills.draw(channel, OUTLINE, scenes, tmp_path / "stills", notes={1: "make it dusk"})
    assert set(out) == {0, 1}
    assert sorted(sheets_drawn) == ["George Washington (president)", "Mount Vernon"]
    assert ("the owner asks: make it dusk" in " ".join(dict((i, f) for i, _, f in drawn)[1]).lower())


# --- running a stage ----------------------------------------------------------------

def test_a_stage_runs_marks_itself_ready_and_a_failure_says_why(world, monkeypatch):
    channel, row = world
    from pipeline.documentary import pitch
    monkeypatch.setattr(pitch, "write", lambda channel, row, note="": PITCH)
    seen = {}
    monkeypatch.setattr(outlines, "write",
                        lambda channel, row, note="", angle=None: seen.update(angle=angle) or OUTLINE)
    with pytest.raises(PipelineError):
        run.run_stage(channel, row["id"], "outline")                  # the angle comes first
    run.run_stage(channel, row["id"], "pitch")
    production.approve("hist", row["id"], "pitch")
    run.run_stage(channel, row["id"], "outline")
    assert seen["angle"]["title"] == "Why Washington Walked Away"     # the outline keeps the angle's promise
    assert production.state(production.load("hist", row["id"]), "outline") == "ready"
    with pytest.raises(PipelineError):
        run.run_stage(channel, row["id"], "script")                   # outline not approved
    production.approve("hist", row["id"], "outline")

    def broken(*a, **k):
        raise PipelineError("x", user_message="The script service was down.")
    monkeypatch.setattr(scripts, "write", broken)
    with pytest.raises(PipelineError):
        run.run_stage(channel, row["id"], "script")
    stage = production.load("hist", row["id"])["stages"]["script"]
    assert stage["state"] == "failed" and stage["error"] == "The script service was down."


# --- the video -----------------------------------------------------------------------

def test_chapters_get_a_longer_pause_and_marks_from_the_real_timings(world):
    scenes = [_scene(1, "a"), _scene(1, "b"), _scene(2, "c")]
    segments = render.segments_for(scenes)
    assert [s.pause_after for s in segments] == [render.RUN_ON_GAP, render.CHAPTER_GAP, render.END_HOLD]
    for s, start in zip(segments, (0.0, 4.0, 9.5)):
        s.start = start
    assert render.chapter_marks(scenes, segments, OUTLINE) == [(0.0, "The surveyor"), (9.5, "The farewell")]
    assert render.stamp(9.5) == "0:09" and render.stamp(3725) == "1:02:05"


def test_titles_and_captions_are_drawn_to_lay_over_the_picture():
    label = render.label_overlay((960, 540), "The farewell", 2, "Mount Vernon, 1797")
    assert label.mode == "RGBA" and label.size == (960, 540)
    assert label.getbbox() is not None
    assert render.label_overlay((960, 540)).getbbox() is None


def test_a_still_is_moved_across_by_the_camera(tmp_path):
    from pipeline.animation import finish
    image = tmp_path / "still.png"
    Image.new("RGB", (320, 180), (200, 120, 40)).save(image)
    overlay = tmp_path / "label.png"
    render.label_overlay((1920, 1080), "Chapter", 1).save(overlay)
    look = {"frame": "wide", "grade": {}}
    out = finish.camera_shot(image, tmp_path / "shot.mp4", 1.0, look, "pan_left", overlay, 0.9)
    assert out.exists() and out.stat().st_size > 1000


# --- teasers -------------------------------------------------------------------------

def test_teasers_are_cleaned_capped_and_keep_only_the_films_cast(world, monkeypatch):
    channel, row = world
    channel.documentary.teasers = 2
    seen = {}

    def fake(system, user, schema, **kw):
        seen["system"] = system[0].text
        teaser = {"title": "The crossing", "description": "d", "scenes": [
            {"direction": "ice", "cast": ["George Washington (president)", "Someone"], "framing": "wide",
             "camera": "push_in", "narration": "It was Christmas night."}]}
        return {"teasers": [teaser, teaser, teaser]}
    monkeypatch.setattr(teasers, "call_json", fake)
    out = teasers.write(channel, "T", OUTLINE, {"scenes": [_scene(1, "Line.")]})
    assert len(out) == 2 and out[0]["scenes"][0]["cast"] == ["George Washington (president)"]
    assert "never mentions the documentary" in seen["system"] and "subscribing" in seen["system"]


# --- the pages and the scheduler --------------------------------------------------------

class TestPages:
    @pytest.fixture
    def client(self, world, monkeypatch):
        from web import create_app
        channel, row = world
        monkeypatch.setattr("web.blueprints.productions.channel_or_404", lambda key: channel)
        monkeypatch.setattr("core.jobs.active_in_order", lambda: [])
        app = create_app()
        app.config.update(TESTING=True)
        return app.test_client()

    def _token(self, html):
        marker = 'name="csrf-token" content="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_a_stage_is_queued_as_a_job_at_batch_prices(self, client, world, monkeypatch):
        channel, row = world
        started = []
        monkeypatch.setattr("core.jobs.start_job", lambda key, seed, ahead=True, behind=False:
                            started.append((seed, ahead, behind)) or "j")
        page = client.get(f"/channels/hist/productions/{row['id']}")
        assert page.status_code == 200 and "Pitch angles" in page.get_data(as_text=True)
        client.post(f"/channels/hist/productions/{row['id']}/start/pitch", data={"note": "Valley Forge"},
                    headers={"X-CSRF-Token": self._token(page.get_data(as_text=True))})
        seed, ahead, behind = started[0]
        assert (seed["type"], seed["stage"], seed["note"], ahead, behind) == \
            ("production", "pitch", "Valley Forge", True, True)

    def test_an_edited_outline_is_saved_approved_and_its_cast_filed(self, client, world):
        channel, row = world
        production.update("hist", row["id"], lambda d: production.made(d, "outline", OUTLINE))
        page = client.get(f"/channels/hist/productions/{row['id']}")
        html = page.get_data(as_text=True)
        assert "Candlelight to dawn" in html and "Mount Vernon" in html
        client.post(f"/channels/hist/productions/{row['id']}/outline", headers={"X-CSRF-Token": self._token(html)},
                    data={"through_line": "His farewell", "visual_concept": "v", "title_options": "A\nB",
                          "chapter_title": ["One"], "chapter_says": ["It begins."], "chapter_shows": ["Woods"],
                          "chapter_minutes": ["2"], "cast_name": ["Martha", ""], "cast_kind": ["character", "character"],
                          "cast_description": ["kind", ""]})
        data = production.load("hist", row["id"])
        assert data["outline"]["through_line"] == "His farewell" and production.state(data, "outline") == "approved"
        assert [m["name"] for m in data["outline"]["cast"]] == ["Martha"]
        assert library.find("hist", "Martha")

    def test_the_productions_list_shows_whats_coming(self, client, world):
        html = client.get("/channels/hist/productions").get_data(as_text=True)
        assert "George Washington" in html and "John Adams" in html


def test_a_documentary_channel_isnt_made_by_the_shorts_scheduler(world, monkeypatch):
    from core import scheduler, storyboard
    channel, row = world
    channel.publishing.enabled = True
    assert "Productions" in scheduler.generation_block("hist", channel, active={})
    started = []
    monkeypatch.setattr("core.jobs.active_in_order", lambda: [])
    monkeypatch.setattr("core.jobs.start_job", lambda key, seed, **kw: started.append(seed["subtopic_id"]))
    production.update("hist", row["id"], lambda d: None)                 # this one has begun
    assert storyboard.outline_ahead(channel) == 1
    assert started == [curriculum.subtopics("hist")[1]["id"]]


# --- the first film's notes (8 Oct, decision 079) --------------------------------------
# The owner on the first History Unmystified film: "the start of some lines
# are briefly stuttered at the end of the preceding line"; the "Chapter"
# text "appearing too frequently ... makes the video seem disjoint"; it was
# "shorter than ... the plan suggested"; "gaps in pauses that seem
# unnatural"; and the music "seems to fade out and then back in ... a gap
# of silence"; and the plan couldn't be found again once it was made.

def test_the_pause_after_a_scene_follows_how_its_words_end():
    assert render.gap_after("He wrote it himself.") == render.SENTENCE_GAP
    assert render.gap_after("and so, by candlelight,") == render.CLAUSE_GAP
    assert render.gap_after("and the crowd waited for") == render.RUN_ON_GAP
    assert render.gap_after('He asked, "Why?"') == render.SENTENCE_GAP
    assert render.CHAPTER_GAP > 3 * render.SENTENCE_GAP          # infrequent and longer


def test_a_documentarys_lines_are_not_told_what_follows_and_are_cut_close(tmp_path, monkeypatch):
    import numpy as np
    from pipeline import tts
    from pipeline.plan import Segment, WordTiming
    seen = {}

    def fake_segment(text, voice_id, out_path, speed=1.0, **kwargs):
        seen[text] = kwargs.get("next_text")
        return [WordTiming(text, 0.1, 1.0)], np.ones((tts.SAMPLE_RATE * 2, 1)) * 0.5, tts.SAMPLE_RATE
    monkeypatch.setattr(tts, "synthesize_segment", fake_segment)
    monkeypatch.setattr(tts.job_context, "report_detail", lambda *a, **k: None)
    pacing = SimpleNamespace(pause_after_first_segment=0.1, pause_after_citation=0.1,
                             pause_between_segments=0.1, end_hold=0.5)
    segments = [Segment(text="One,", pause_after=0.06), Segment(text="two."), Segment(text="three.")]
    tts.generate_voiceover(segments, None, "v", str(tmp_path / "a.mp3"), pacing, close=True)
    assert seen == {"One,": "", "two.": "", "three.": ""}
    assert segments[0].end - segments[0].start == pytest.approx(1.0 + tts.HELD_TRAILING_PAD + 0.06, abs=0.01)
    # Without it (every short), the next line is still given.
    seen.clear()
    tts.generate_voiceover([Segment(text="One,"), Segment(text="two.")], None, "v",
                           str(tmp_path / "b.mp3"), pacing)
    assert seen["One,"] == "two."


def test_chapter_titles_are_off_unless_asked_for():
    from core.channels import Documentary
    assert Documentary().chapter_titles is False


def test_a_short_chapter_is_written_again_at_length(world, monkeypatch):
    channel, row = world
    calls = []

    def fake(system, user, schema, **kw):
        calls.append(user)
        words = 5 if len(calls) == 1 else 60
        return {"scenes": [{"chapter": 1, "direction": "d", "cast": [], "framing": "wide", "camera": "still",
                            "caption": "", "narration": " ".join(["word"] * words)}], "description": ""}
    monkeypatch.setattr(scripts, "call_json", fake)
    out = scripts._chapter(channel, row["title"], OUTLINE, 1, [])
    assert len(calls) == 2 and "was 5 words" in calls[1]
    assert scripts.words(out) == 60


def test_a_seamless_bed_doesnt_dip_to_silence_where_a_track_loops(monkeypatch, tmp_path):
    import numpy as np
    from pipeline import longform, sound
    fps = 8000
    t = np.arange(fps * 20) / fps
    tone = 0.5 * np.sin(2 * np.pi * 220 * t)
    # Mastered with a three-second fade-out and two seconds of silence.
    tone[-5 * fps:-2 * fps] *= np.linspace(1, 0, 3 * fps)
    tone[-2 * fps:] = 0
    track = np.stack([tone, tone], axis=1)
    monkeypatch.setattr(sound, "music_tracks", lambda key: [tmp_path / "one.mp3"])
    monkeypatch.setattr("pipeline.audio.decode_audio_file", lambda path, fps=0, nchannels=2: track.copy())
    monkeypatch.setattr(sound, "speech_envelope", lambda voice, fps: np.zeros(len(voice)))
    channel = SimpleNamespace(key="c", sound=SimpleNamespace(music_level=1.0))
    voice = np.zeros((fps * 45, 2), dtype=np.float32)

    def quietest(bed):
        level = np.abs(bed[:, 0])
        middle = level[fps * 6: len(level) - fps * 8]
        return np.convolve(middle, np.ones(fps // 5) / (fps // 5), mode="valid").min()
    assert quietest(longform.music_bed(channel, voice, fps, "s", [], seamless=True)) > 0.15
    assert quietest(longform.music_bed(channel, voice, fps, "s", [])) < 0.05     # as long quizzes have it
