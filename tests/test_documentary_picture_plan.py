"""
Pictures planned as a set, shots cut between neighbours, and an ending
(decision 092).

The owner, on the remade drill film: "there are maybe a dozen or more
different images that all show the earth with people looking up at it.
This is exactly the kind of picture duplication we want to avoid"; the
planet's cross-section had been made a cast member and turned up
everywhere; "in a video about amoebas ... I'm worried that the amoebas
would sometimes be shown in the lab"; "often it shows one picture and
then a zoomed in portion - this is quite repetitive"; and "the end of
the video seems like it sort of concludes and then stops".
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as N

import numpy as np
from PIL import Image

from pipeline.documentary import editor, outline as outlines, pictures, shots
from pipeline.documentary import render

OUTLINE = {
    "settings": [{"name": "The lab", "scale": "human", "description": "a bright university lab"},
                 {"name": "Under the microscope", "scale": "microscopic", "description": "a drop of pond water"}],
    "cast": [{"name": "Dr Okafor", "kind": "character", "settings": ["The lab"], "description": "a scientist"},
             {"name": "The amoeba", "kind": "character", "settings": ["Under the microscope"],
              "description": "a translucent blob"}],
}


def _scene(direction, setting, cast=(), medium="picture", **extra):
    return {"chapter": 1, "direction": direction, "setting": setting, "cast": list(cast), "framing": "wide",
            "narration": "x", "medium": medium, **extra}


def test_an_outline_names_its_settings_and_where_each_member_exists():
    raw = {"chapters": [{"title": "A", "says": "s", "turn": "t", "shows": "w", "sound": "none", "minutes": 1}],
           "settings": [{"name": "The lab", "scale": "human", "description": "a lab"}],
           "cast": [{"name": "Dr Okafor", "kind": "character", "settings": ["the lab", "Mars"], "description": "d"},
                    {"name": "The lab", "kind": "place", "settings": [], "description": "a lab again"}]}
    clean = outlines.clean(raw, 4)
    assert clean["cast"] == [{"name": "Dr Okafor", "kind": "character", "description": "d", "settings": ["The lab"]}]
    assert outlines.problems({**clean, "open_loops": ["?"], "settings": []}, 4)[-1].startswith("No settings")


def test_nothing_appears_where_it_doesnt_exist():
    scenes = [_scene("The amoeba on the bench beside Dr Okafor", "The lab", cast=("Dr Okafor", "The amoeba"))]
    assert pictures.validate(OUTLINE, scenes)[0]["cast"] == ["Dr Okafor"]


def test_the_picture_editor_reuses_or_redirects_repeats(monkeypatch):
    scenes = [_scene("The planet cut open, people looking up", "The lab"),
              _scene("Dr Okafor at the microscope", "The lab", cast=("Dr Okafor",)),
              _scene("The planet cut open, one more layer peeled, people looking up", "The lab"),
              _scene("The planet cut open again, people looking up", "The lab"),
              _scene("A card", "The lab", medium="card")]
    monkeypatch.setattr(pictures, "call_json", lambda *a, **k: {"pictures": []} if k.get("operation") ==
                        "documentary_looks" else {"changes": [
        {"scene": 2, "action": "reuse", "same_as": 0, "direction": "", "setting": "", "cast": [], "why": "the same"},
        {"scene": 3, "action": "redirect", "same_as": -1, "direction": "The amoeba engulfing a crumb",
         "setting": "under the microscope", "cast": ["The amoeba", "Dr Okafor"], "why": "moved on"},
        {"scene": 4, "action": "reuse", "same_as": 0, "direction": "", "setting": "", "cast": [], "why": "a card"}]})
    out = pictures.plan(OUTLINE, {"scenes": scenes})
    planned = out["scenes"]
    assert planned[2]["same_as"] == 0 and "same_as" not in planned[4]
    assert planned[3]["setting"] == "Under the microscope" and planned[3]["cast"] == ["The amoeba"]
    assert out["pictures"]["planned"] and out["pictures"]["shown_again"] == 1


def test_a_picture_is_shown_again_at_most_three_times_never_twice_in_a_row():
    scenes = [_scene(f"s{i}", "The lab") for i in range(7)]
    for i, j in ((1, 0), (2, 0), (4, 0), (6, 0), (5, 2)):
        scenes[i]["same_as"] = j
    out = pictures.validate(OUTLINE, scenes)
    assert [s.get("same_as") for s in out] == [None, None, 0, None, 0, None, None]


def test_a_rewritten_chapter_keeps_pictures_pointing_at_the_right_scenes(monkeypatch):
    from pipeline.documentary import script as scripts
    script = {"scenes": [{**_scene("a", "The lab"), "chapter": 1}, {**_scene("b", "The lab"), "chapter": 2},
                         {**_scene("c", "The lab"), "chapter": 3, "same_as": 0},
                         {**_scene("d", "The lab"), "chapter": 3, "same_as": 1}]}
    monkeypatch.setattr(scripts, "_chapter", lambda *a, **k: {"scenes": [
        {**_scene("b1", "The lab"), "chapter": 2}, {**_scene("b2", "The lab"), "chapter": 2}]})
    out = scripts.rewrite_chapter(None, "T", {"chapters": [{}, {}, {}]}, script, 2, "note")
    assert out["scenes"][3].get("same_as") == 0 and "same_as" not in out["scenes"][4]


def _unit(i, setting, pictures_, seconds=7.0):
    return {"i": i, "seconds": seconds, "beats": [], "setting": setting,
            "shots": [{"picture": Path(p), "seconds": seconds / len(pictures_), "move": "push_in", "from": i}
                      for p in pictures_]}


def test_shots_cut_between_neighbours_in_one_setting():
    units = [_unit(0, "The lab", ["A", "A_crop"]), _unit(1, "The lab", ["B", "B_crop"]),
             _unit(2, "The lab", ["C", "C_crop"]), _unit(3, "Under the microscope", ["D", "D_crop"])]
    shots.interleave(units)
    names = [[s["picture"].name for s in u["shots"]] for u in units]
    assert names == [["A"], ["B", "A_crop"], ["C", "B_crop"], ["D", "D_crop"]]    # another setting: untouched
    assert all(abs(sum(s["seconds"] for s in u["shots"]) - 7.0) < 1e-6 for u in units)
    long = [_unit(0, "The lab", ["A", "A_crop"], 10.0), _unit(1, "The lab", ["B", "B_crop"], 10.0)]
    shots.interleave(long)
    assert len(long[0]["shots"]) == 2                     # A alone would hold 10 s, past the limit


def test_the_last_line_is_made_an_ending(monkeypatch):
    script = {"scenes": [{"chapter": 1, "narration": "First."}, {"chapter": 1, "narration": "So what now?"}]}
    monkeypatch.setattr(editor, "call_json", lambda *a, **k: {"keep": False, "line": "You're standing on the lid.",
                                                              "why": "it asked a question"})
    out, why = editor.final_line(N(style_prompt="brief"), "T", script)
    assert out["scenes"][-1]["narration"] == "You're standing on the lid." and why
    monkeypatch.setattr(editor, "call_json", lambda *a, **k: {"keep": True, "line": "", "why": ""})
    assert editor.final_line(N(style_prompt="brief"), "T", script) == (script, "")


def test_the_last_picture_fades_out(tmp_path):
    import imageio_ffmpeg
    import subprocess
    still = tmp_path / "s.png"
    Image.new("RGB", (64, 36), (255, 255, 255)).save(still)
    clip = tmp_path / "c.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-loop", "1", "-i", str(still), "-t", "2",
                    "-r", "10", "-pix_fmt", "yuv420p", str(clip)], check=True)
    faded = render.fade_out(clip, 2.0, 1.0)
    reader = imageio_ffmpeg.read_frames(str(faded))
    meta = next(reader)
    frames = [np.frombuffer(f, dtype=np.uint8) for f in reader]
    assert frames[0].mean() > 200 and frames[-1].mean() < 40 and meta["size"] == (64, 36)
    assert render.END_HOLD >= 4


def test_one_off_pictures_have_no_cast_and_never_cut_together():
    scenes = pictures.validate(OUTLINE, [_scene("Pressure as elephants stacked on a chair", "one-off",
                                                cast=("Dr Okafor",))])
    assert scenes[0]["setting"] == "one-off" and scenes[0]["cast"] == []
    units = [_unit(0, "one-off", ["A", "A_crop"]), _unit(1, "one-off", ["B", "B_crop"])]
    shots.interleave(units)
    assert [len(u["shots"]) for u in units] == [2, 2]


def test_the_rules_are_checked_without_a_model():
    lab = [_scene(f"Dr Okafor at work {i}", "The lab", cast=("Dr Okafor",)) for i in range(6)]
    lab[3]["direction"] = "Dr Okafor stands among the amoeba"                 # names someone not there
    misplaced = _scene("The amoeba beside Dr Okafor's hand", "Under the microscope", cast=("The amoeba",))
    found = pictures.audit(OUTLINE, lab + [misplaced], kind="explainer")
    problems = {p["scene"]: p["problem"] for p in found}
    assert "doesn't exist in Under the microscope" in problems[6]
    assert "in a row" in problems[4] or "carries" in problems[4]
    assert any("carries" in p for p in problems.values())
    assert pictures.audit(OUTLINE, lab[:3], kind="story") == []


def test_what_the_checks_still_find_goes_back_once(monkeypatch):
    scenes = [_scene("Dr Okafor watches the amoeba crawl across the bench", "The lab", cast=("Dr Okafor",))]
    asked = []

    def editor_(system, user, schema, operation, **kw):
        if operation == "documentary_looks":
            return {"pictures": [{"scene": 0, "subject": "Dr Okafor"}]}
        asked.append(user)
        if len(asked) == 1:
            return {"changes": []}                       # the editor misses it
        return {"changes": [{"scene": 0, "action": "redirect", "same_as": -1,
                             "direction": "Dr Okafor watches the monitor, where the amoeba crawls", "setting": "The lab",
                             "cast": ["Dr Okafor"], "why": "seen through the screen"}]}
    monkeypatch.setattr(pictures, "call_json", editor_)
    out = pictures.plan(OUTLINE, {"scenes": scenes}, kind="explainer")
    assert len(asked) == 2 and "nothing else" not in asked[0]               # the whole film first
    assert "- scene 0: The amoeba doesn't exist in The lab" in asked[1]     # then what the checks found
    assert out["pictures"]["unfixed"] == []


def test_the_model_names_subjects_and_the_code_groups_and_counts_them(monkeypatch):
    """Thirteen pictures of the drill bit in its shaft got through as
    "different" when the editor alone judged sameness; asked to group them
    itself, it split one subject by framing, then lumped a whole place."""
    scenes = [_scene(f"The drill bit in the shaft, coated a little more {i}", "The lab") for i in range(6)]
    calls = []

    def fake(system, user, schema, operation, **kw):
        calls.append(operation)
        if operation == "documentary_looks":
            return {"pictures": [{"scene": i, "subject": "The drill bit" if i % 2 else "the Drill Bit"}
                                 for i in range(6)]}
        if calls.count("documentary_pictures") == 1:    # the first round fixes only one
            return {"changes": [{"scene": 4, "action": "reuse", "same_as": 0, "direction": "", "setting": "",
                                 "cast": [], "why": "same"}]}
        return {"changes": [{"scene": 5, "action": "redirect", "same_as": -1, "direction": "Pressure as elephants",
                             "setting": "one-off", "cast": [], "why": "an idea"}]}
    monkeypatch.setattr(pictures, "call_json", fake)
    groups = pictures.looks(OUTLINE, scenes)
    assert len(pictures.crowded(groups, scenes, "explainer")) == 2          # six of one look; four may stay
    calls.clear()
    out = pictures.plan(OUTLINE, {"scenes": scenes}, kind="explainer")
    edits = [c for c in calls if c == "documentary_pictures"]
    assert calls[0] == "documentary_looks" and len(edits) >= 2              # sent back after the first pass
    assert calls.count("documentary_looks") >= 2                            # and the new pictures sorted again
    assert not any("same look" in p["problem"] for p in out["pictures"]["unfixed"])   # four left: allowed
    assert out["scenes"][4]["same_as"] == 0 and out["scenes"][5]["setting"] == "one-off"


def test_one_off_metaphors_are_counted_too(monkeypatch):
    scenes = [_scene(f"Wet clay swallowing a ring {i}", "one-off") for i in range(3)]
    monkeypatch.setattr(pictures, "call_json", lambda *a, **k: {"pictures": [
        {"scene": i, "subject": "wet clay"} for i in range(3)]})
    groups = pictures.looks(OUTLINE, scenes)
    assert len(groups) == 1 and [p["scene"] for p in pictures.crowded(groups, scenes, "explainer")] == [2]


def test_a_picture_shown_again_is_where_that_picture_is():
    scenes = [_scene("The amoeba engulfing a crumb", "Under the microscope", cast=("The amoeba",)),
              _scene("Dr Okafor writes", "The lab", cast=("Dr Okafor",)),
              _scene("x", "The lab", cast=("Dr Okafor",), same_as=0)]
    out = pictures.validate(OUTLINE, scenes)
    assert out[2]["setting"] == "Under the microscope" and out[2]["cast"] == ["The amoeba"]


def test_a_picture_described_word_for_word_again_is_shown_again():
    door = "A thin curtain billows in an open window while a heavy door stays shut."
    scenes = [_scene(door, "one-off"), _scene("x", "The lab"), _scene("y", "The lab"), _scene(door + " ", "one-off"),
              _scene("z", "The lab"), _scene(door[:-1] + ", now still and final.", "one-off")]
    out = pictures.validate(OUTLINE, scenes)
    assert out[3]["same_as"] == 0 and out[5]["same_as"] == 0                 # the callback is the same picture


def test_a_cutaway_is_one_look_and_a_look_is_on_screen_only_so_often(monkeypatch):
    """The shaft cut open was on screen eleven times, named "the drill bit"
    in some pictures and "the borehole shaft" in others."""
    outline = {**OUTLINE, "settings": OUTLINE["settings"] + [
        {"name": "The shaft", "scale": "cutaway", "description": "the borehole cut open"}]}
    scenes = [_scene(f"shaft {i}", "The shaft") for i in range(4)] + [_scene("lab", "The lab")] * 4
    for i in (5, 6, 7):
        scenes[i] = {**scenes[i], "same_as": i - 5}
    monkeypatch.setattr(pictures, "call_json", lambda *a, **k: {"pictures": [
        {"scene": i, "subject": "the drill bit" if i % 2 else "the borehole shaft"} for i in range(4)]})
    groups = pictures.looks(outline, scenes)
    assert [g["scenes"] for g in groups if g["look"].startswith("the view")] == [[0, 1, 2, 3]]
    found = pictures.crowded(groups, scenes, "explainer")
    assert [p["scene"] for p in found] == [7] and "on screen 7 times" in found[0]["problem"]


def test_a_number_card_is_only_corrected_with_a_number(monkeypatch):
    card = {"kind": "number", "heading": "h", "value": "300C", "caption": "", "items": []}
    scenes = [{"chapter": 1, "narration": "x", "medium": "card", "card": card}]
    monkeypatch.setattr(editor, "call_json", lambda *a, **k: {"fixes": [
        {"scene": 0, "problem": "p", "narration": "y", "card": "Rock turns ductile near|..."}]})
    assert editor.fact_check({"scenes": scenes})[0]["scenes"][0]["card"]["value"] == "300C"


def test_a_line_that_only_repeats_an_earlier_point_is_rewritten(monkeypatch):
    """Decision 093: the drill film made the same points again in new words."""
    script = {"scenes": [{"chapter": 1, "narration": "Clear the atmosphere and resistance falls to nothing."},
                         {"chapter": 2, "narration": "Space empties out as you climb."},
                         {"chapter": 2, "narration": "The sky above runs empty."}]}
    monkeypatch.setattr(editor, "call_json", lambda *a, **k: {"repeats": [
        {"scene": 1, "earlier": 0, "narration": "A rocket's engines fall silent eight minutes after launch."},
        {"scene": 2, "earlier": 0, "narration": "the last line is never touched"},
        {"scene": 0, "earlier": 1, "narration": "an earlier line can't repeat a later one"}]})
    out, notes = editor.restatements(script)
    assert [n["scene"] for n in notes] == [1] and out["scenes"][1]["narration"].startswith("A rocket's")
    assert out["scenes"][2]["narration"] == "The sky above runs empty."


def test_an_untitled_chapter_is_written_again_or_named_by_what_it_says():
    raw = {"chapters": [{"title": "Cold open", "says": "Every river is dissolving rock right now. More.",
                         "turn": "The question is stated as a promise: why?", "shows": "w", "sound": "none",
                         "minutes": 1}], "settings": [{"name": "A river", "scale": "landscape", "description": "d"}]}
    clean = outlines.clean(raw, 4)
    assert clean["chapters"][0]["title"] == "Every river is dissolving rock right now"
    assert any("no real title" in p for p in outlines.problems({**clean, "open_loops": ["?"]}, 4))


def test_a_rewritten_line_never_keeps_the_chapter_marker_it_was_shown(monkeypatch):
    script = {"scenes": [{"chapter": 1, "narration": "Salt goes in."}, {"chapter": 3, "narration": "Salt goes in again."},
                         {"chapter": 3, "narration": "End."}]}
    monkeypatch.setattr(editor, "call_json", lambda *a, **k: {"repeats": [
        {"scene": 1, "earlier": 0, "narration": "[chapter 3] [wry] Salt leaves by seafloor mud."}]})
    assert editor.restatements(script)[0]["scenes"][1]["narration"] == "[wry] Salt leaves by seafloor mud."


def test_the_fact_check_is_told_to_doubt_the_films_own_thesis():
    assert "central claims" in editor.FACTS and "never" in editor.FACTS


def test_a_list_card_is_corrected_with_its_line(monkeypatch):
    card = {"kind": "list", "heading": "The valve", "value": "", "caption": "",
            "items": ["Salt arrives", "Water leaves", "Salt stays, with nowhere to drain"]}
    scenes = [{"chapter": 1, "narration": "Salt never leaves.", "medium": "card", "card": card}]
    monkeypatch.setattr(editor, "call_json", lambda *a, **k: {"fixes": [
        {"scene": 0, "problem": "salt leaves slowly", "narration": "Salt leaves, but slowly.",
         "card": "Salt arrives ; Water leaves ; Salt leaves slowly, into seafloor mud"}]})
    out = editor.fact_check({"scenes": scenes})[0]["scenes"][0]["card"]
    assert out["items"][-1] == "Salt leaves slowly, into seafloor mud"


def test_the_drawer_gets_neither_the_writers_motif_nor_a_sheet_of_props(tmp_path):
    """Decision 093: a style sheet with an old man, a child and a cup, and a
    visual concept about "the same two glasses ... wherever the scene allows",
    put people and glasses into pictures that never asked for them."""
    import inspect
    from pipeline.animation import bible
    from pipeline.documentary import stills
    board = stills.board({"visual_concept": "the same two glasses wherever the scene allows", "cast": []}, "x")
    assert board["colour_script"] == ""
    assert "No people" in bible.FILM_STYLE_SHEET and "film=True" in inspect.getsource(stills.draw)


def test_the_description_is_checked_against_the_corrected_script(monkeypatch):
    script = {"scenes": [{"chapter": 1, "narration": "About 175 times weaker."}],
              "description": "A journey: rivers are two hundred times too diluted to taste."}
    seen = []

    def fake(system, user, schema, **kw):
        seen.append(user)
        return {"fixes": [], "description": "Rivers carry salt about 175 times too diluted to taste."}
    monkeypatch.setattr(editor, "call_json", fake)
    out, notes = editor.fact_check(script)
    assert "two hundred" in seen[0] and out["description"].startswith("Rivers carry salt about 175")
    assert notes == [{"scene": -1, "problem": "the description"}]
