"""
Composited styles (decisions 052, 053): the theme a style gives the
stage, the compositor's layouts and timing (continuities and entrances),
the beats storyboard made safe, the kit, the composited pipeline, and the
captions and the director's side of it.

Styles come from starting points (pipeline/animation/style), compiled as
the pipeline compiles them. Models and services are faked; the one real
render is marked slow.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.channels import ChannelConfig
from pipeline.animation import beats, compose, frame as frames, kit, stage, storyboard, style
from pipeline.animation.compositor import diagrams, expr, layouts, mathtext, script, theme
from pipeline.plan import Segment, WordTiming


def words_for(text: str, start: float = 0.0, step: float = 0.4) -> list:
    return [WordTiming(w, round(start + i * step, 2), round(start + i * step + 0.3, 2))
            for i, w in enumerate(text.split())]


def compiled(sid: str, **changes) -> tuple:
    """(fmt, look) for a starting point, with any answers changed."""
    return style.compile(SimpleNamespace(style={**style.starting_point(sid)["answers"],
                                                **changes}))


TABLETOP, FELT = compiled("felt_science")                 # move, drop, seen from above
CANVAS, FLAT = compiled("diagram_host")                   # persist, canvas areas, a host
THEATRE, PAPER = compiled("stubby_paper_history")         # scene, puppets
BOARD, MARKER = compiled("whiteboard")                    # clear, drawn in
PINNED, KNIT = compiled("knitted_wellbeing")              # move, pinned on
MEEPLES, MATTE = compiled("meeple_logic")                 # a board at a low angle


# --- the theme ---------------------------------------------------------------------

class TestTheme:
    def test_a_style_gives_the_stage_its_inks_and_rate(self):
        t = theme.theme(TABLETOP, FELT)
        assert t["step"] == pytest.approx(1 / 12) and t["jitter"] > 0
        assert t["labels"]["color"] == theme.inks(FELT)["ink"]
        t = theme.theme(CANVAS, FLAT)
        assert t["step"] == 0 and t["jitter"] == 0

    def test_labels_stay_legible_on_a_dark_surface(self):
        fmt, look = compiled("chalk_maths")
        assert theme.dark(fmt, look) and not theme.dark(TABLETOP, FELT)
        labels = theme.theme(fmt, look)["labels"]
        assert labels["color"] == theme.inks(look)["paper"]

    def test_pieces_on_an_angled_board_overlap_front_to_back(self):
        assert theme.theme(MEEPLES, MATTE)["depth_sort"] is True
        assert theme.theme(TABLETOP, FELT)["depth_sort"] is False


# --- layouts -------------------------------------------------------------------------

def item(key, label="a label", count=1, highlight=False, **more):
    return {"key": key, "label": label, "count": count, "highlight": highlight, **more}


CASES = {
    "hero": [item("brain")], "pair": [item("a"), item("b")], "row": [item("a"), item("b"), item("c")],
    "grid": [item(k) for k in "abcdef"], "steps": [item(k) for k in "abcd"],
    "cycle": [item(k) for k in "abcde"], "group": [item("coin", count=30, highlight=True)],
    "travel": [item("yawn"), item("face"), item("dog")], "scale": [item(k) for k in "abcd"],
    "statement": [item("a")], "presenter": [item("a")],
    "lineup": [item("meeple", says="Red?") for _ in range(4)], "table": [item("a")],
    "scene": [item("caesar", role="left", says="Alea iacta est"), item("horse", role="right"),
              item("river", role="prop")],
}
TABLE = [["", "Cooperate", "Defect"], ["Cooperate", "3, 3", "0, 5"], ["Defect", "5, 0", "1, 1"]]


CASES["diagram"] = [item("a"), item("b")]


class TestLayouts:
    @pytest.mark.parametrize("frame", ["vertical", "wide"])
    @pytest.mark.parametrize("layout", sorted(CASES))
    @pytest.mark.parametrize("aspect", [0.45, 1.0, 2.2])
    def test_everything_stays_in_the_frame_and_above_the_captions(self, layout, aspect, frame):
        f = frames.get(frame)
        its = [dict(i) for i in CASES[layout]]
        placed, marks = layouts.arrange(layout, its, {i["key"]: aspect for i in its},
                                        relation="arrow", title="A title here", table=TABLE,
                                        backdrop="rubicon", frame=frame)
        assert placed or layout == "statement"
        top, bottom = f.title_y + 50, f.content[3] + 70
        for p in placed:
            if p.get("layer") == "back":
                assert (p["w"], p["h"]) == (f.w, f.h)
                continue
            assert p["x"] - p["w"] / 2 >= -1 and p["x"] + p["w"] / 2 <= f.w + 1, (layout, p)
            assert p["y"] - p["h"] / 2 >= top and p["y"] + p["h"] / 2 <= bottom, (layout, p)
        for m in marks:
            if m["kind"] == "label":
                assert 40 <= m["x"] <= f.w - 40 and m["y"] <= bottom + 40, (layout, m)
            if m["kind"] == "diagram":
                x0, y0, x1, y1 = m["box"]
                assert f.content[0] <= x0 < x1 <= f.content[2] and y1 <= f.content[3]
                assert all(p["y"] + p["h"] / 2 <= y0 + 5 if f.vertical else
                           p["x"] + p["w"] / 2 <= x0 + 5 for p in placed), (frame, placed)

    def test_vertical_layouts_are_where_they_always_were(self):
        """The frame-relative rewrite (decision 054) left the tuned
        vertical geometry exactly as it was."""
        placed, _ = layouts.arrange("hero", [item("a")], {"a": 1.0})
        assert (placed[0]["x"], placed[0]["y"]) == (540, 800)
        placed, _ = layouts.arrange("row", [item(k) for k in "abc"], {k: 1 for k in "abc"})
        assert [p["x"] for p in placed] == [190, 540, 890]
        placed, _ = layouts.arrange("grid", [item(k) for k in "abcd"], {k: 1 for k in "abcd"})
        assert [(p["x"], p["y"]) for p in placed] == [(300, 580), (780, 580), (300, 1000), (780, 1000)]

    def test_a_wide_frame_spreads_things_across(self):
        its = [item(k) for k in "abcd"]
        placed, marks = layouts.arrange("steps", its, {k: 1 for k in "abcd"}, frame="wide")
        assert len({round(p["y"]) for p in placed}) == 1                  # one row
        assert [p["x"] for p in placed] == sorted(p["x"] for p in placed)  # left to right
        badges = [m for m in marks if m["kind"] == "badge"]
        assert all(b["y"] < placed[0]["y"] for b in badges)
        placed, _ = layouts.arrange("grid", [item(k) for k in "abcdef"], {k: 1 for k in "abcdef"},
                                    frame="wide")
        assert len({round(p["y"]) for p in placed}) == 2                  # three across, two down
        placed, marks = layouts.arrange("statement", [item("a")], {"a": 1}, title="42",
                                        frame="wide")
        big = next(m for m in marks if m["role"] == "statement")
        assert placed[0]["x"] < big["x"] and abs(placed[0]["y"] - big["y"]) < 1   # side by side

    def test_a_wide_stage_has_its_floor_and_wings(self):
        placed, _ = layouts.arrange("scene", [item("a", role="left"), item("b", role="right")],
                                    {"a": 0.5, "b": 0.5}, backdrop="hall", frame="wide")
        people = [p for p in placed if p.get("layer") != "back"]
        assert {round(p["y"] + p["h"] / 2) for p in people} == {frames.WIDE.floor}
        assert people[0]["x"] < 960 < people[1]["x"]

    def test_bubbles_know_the_frame_they_must_stay_in(self):
        placed, marks = layouts.arrange("lineup", [item("m", says="Red?") for _ in range(3)],
                                        {"m": 0.6}, title="The hats", frame="wide")
        bubble = next(m for m in marks if m["kind"] == "bubble")
        assert (bubble["min_x"], bubble["max_x"]) == (24, 1920 - 24)
        assert bubble["min_y"] == frames.WIDE.title_y + 70                # below the title

    def test_a_joined_pair_leaves_room_for_what_joins_it(self):
        placed, marks = layouts.arrange("pair", [item("a"), item("b")], {"a": 1.0, "b": 1.0},
                                        relation="arrow")
        a, b = placed
        assert (b["x"] - b["w"] / 2) - (a["x"] + a["w"] / 2) >= 180
        assert [m["kind"] for m in marks if m["role"] == "relation"] == ["arrow"]

    def test_a_group_circles_the_highlighted_one(self):
        placed, marks = layouts.arrange("group", [item("coin", "1 in 10", count=10,
                                                       highlight=True)], {"coin": 1.0})
        assert len(placed) == 10 and [m["kind"] for m in marks].count("ring") == 1

    def test_a_traveller_goes_from_its_start_to_its_end(self):
        placed, _ = layouts.arrange("travel", [item("yawn"), item("you", place="end")],
                                    {"yawn": 1, "you": 1})
        mover = placed[0]
        assert mover["from"][1] > mover["y"]        # sets off low, arrives high (towards the end)
        end = next(p for p in placed if p["key"] == "you")
        assert end["y"] < 700                         # the end sits at the top right

    def test_areas_offset_everything(self):
        placed, marks = layouts.arrange("hero", [item("a")], {"a": 1.0}, origin=(2000, 3000))
        assert placed[0]["x"] == 2540 and all(m["x"] > 2000 for m in marks)

    def test_a_lineup_keeps_every_copy_of_a_figure_with_its_own_bubble(self):
        """Regression: the hats puzzle's four prisoners collapsed into two
        when the same meeple stood in the line more than once."""
        its = [item("meeple", "A"), item("meeple", "B"), item("meeple", "C"),
               item("meeple", "D", says="Red?", thinks=True)]
        placed, marks = layouts.arrange("lineup", its, {"meeple": 0.6})
        assert [p["copy"] for p in placed] == [0, 1, 2, 3]
        assert len({p["x"] for p in placed}) == 4 and len({p["y"] + p["h"] / 2 for p in placed}) == 1
        assert [m["anchor"] for m in marks if m["kind"] == "label"] == [("meeple", n) for n in range(4)]
        bubble, = [m for m in marks if m["kind"] == "bubble"]
        assert bubble["anchor"] == ("meeple", 3) and bubble["thinks"] is True

    def test_a_table_is_a_grid_of_words_with_room_for_two_things(self):
        placed, marks = layouts.arrange("table", [item("a"), item("b"), item("c")],
                                        {"a": 1, "b": 1, "c": 1}, table=[["x"], ["y", "z"]])
        grid, = [m for m in marks if m["kind"] == "table"]
        assert grid["rows"] == [["x", ""], ["y", "z"]]              # squared up
        assert len(placed) == 2 and all(p["y"] < grid["y"] for p in placed)

    def test_a_scene_has_its_backdrop_behind_and_players_facing_the_middle(self):
        its = [item("caesar", role="right"), item("horse"), item("river", role="prop")]
        placed, marks = layouts.arrange("scene", its, {"caesar": 0.5, "horse": 0.8, "river": 2},
                                        backdrop="rubicon", caption="49 BC")
        back = next(p for p in placed if p.get("layer") == "back")
        assert (back["key"], back["w"], back["h"]) == ("rubicon", 1080, 1920)
        caesar = next(p for p in placed if p["key"] == "caesar")
        horse = next(p for p in placed if p["key"] == "horse")
        assert caesar["x"] > 540 and caesar["flip"] == -1           # on the right, facing left
        assert horse["x"] < 540 and horse["flip"] == 1
        feet = {round(p["y"] + p["h"] / 2) for p in placed if p.get("layer") != "back"}
        assert feet == {layouts.STAGE_FLOOR}
        assert any(m["role"] == "caption" and m["text"] == "49 BC" for m in marks)


# --- the script: timing, continuity, entrances -----------------------------------------

STYLE = {"step": 1 / 12, "jitter": 1.0, "surface": {"color": "#fff"},
         "shadow": {"mode": "none"}, "labels": {"font": "Ink Free"}}


def beat(start, end, layout, its, **more):
    return {"start": start, "end": end, "layout": layout, "items": its, "title": "",
            "relation": "", "avatar": "", **more}


WORDS = words_for(" ".join(f"w{i}" for i in range(60)), step=0.5)       # 30 seconds


def keys_of(stage_data, sprite_id):
    return next(s for s in stage_data["sprites"] if s["id"] == sprite_id)["keys"]


class TestScript:
    def test_objects_arrive_on_their_words(self):
        st = script.build([beat(0, 10, "pair", [item("a", on_word=2), item("b", on_word=8)])],
                          WORDS, 0.0, 10, {"a": 1, "b": 1}, TABLETOP, STYLE)
        a, b = keys_of(st, "a_0"), keys_of(st, "b_0")
        assert a[1]["t"] == pytest.approx(0.88)          # word 2 at 1.0s, a moment ahead
        assert b[1]["t"] == pytest.approx(3.88)

    def test_the_first_object_never_leaves_the_table_empty(self):
        st = script.build([beat(0, 8, "hero", [item("a", on_word=15)])], WORDS, 0.0, 8,
                          {"a": 1}, TABLETOP, STYLE)
        assert keys_of(st, "a_0")[1]["t"] <= 2.0 + 1e-6      # capped at a quarter of the beat

    def test_a_carried_object_moves_instead_of_arriving_again(self):
        st = script.build([beat(0, 5, "hero", [item("a")]), beat(5, 10, "pair", [item("a"), item("b")])],
                          WORDS, 0.0, 10, {"a": 1, "b": 1}, TABLETOP, STYLE)
        a = keys_of(st, "a_0")
        assert [k.get("lift") for k in a if k.get("lift") == 1] == [1, 1]   # one arrival only
        assert any(k.get("ease") == "inout" and k.get("hop") for k in a)     # it walks over

    def test_a_leaving_object_is_fully_there_until_it_goes(self):
        """Regression: an exit without a visible key spread its fade over
        the object's whole time on the table; short-lived objects barely
        showed."""
        st = script.build([beat(0, 5, "hero", [item("a")]), beat(5, 10, "hero", [item("b")])],
                          WORDS, 0.0, 10, {"a": 1, "b": 1}, TABLETOP, STYLE)
        a = keys_of(st, "a_0")
        exit_start = next(k for k in a if k["t"] == pytest.approx(4.95))
        assert exit_start["alpha"] == 1 and a[-1]["alpha"] == 0

    def test_an_object_that_comes_back_is_the_same_object_again(self):
        """Regression: re-entering overwrote the sprite, losing its first
        appearance."""
        st = script.build([beat(0, 4, "hero", [item("a")]), beat(4, 8, "hero", [item("b")]),
                           beat(8, 12, "hero", [item("a")])],
                          WORDS, 0.0, 12, {"a": 1, "b": 1}, TABLETOP, STYLE)
        ids = [s["id"] for s in st["sprites"]]
        assert ids.count("a_0") == 1
        a = keys_of(st, "a_0")
        assert a[0]["t"] == 0 and max(k["t"] for k in a) > 8           # both appearances

    def test_a_canvas_keeps_each_beat_in_its_own_area_and_travels_there(self):
        st = script.build([beat(0, 5, "hero", [item("a")]), beat(5, 10, "hero", [item("a")])],
                          WORDS, 0.0, 10, {"a": 1}, CANVAS, dict(STYLE, step=0, jitter=0))
        assert {s["id"] for s in st["sprites"]} == {"a_0_0", "a_0_1"}
        xs = [k["x"] for k in st["camera"]]
        assert min(xs) == 540 and max(xs) == 540 + 1080 + script.AREA_GAP
        assert st["world"]["w"] == 2 * 1080 + script.AREA_GAP
        assert all(m["t1"] is None for m in st["marks"])             # what's drawn stays drawn

    def test_the_host_talks_only_on_presenter_beats(self):
        style_ = dict(STYLE, avatar={"poses": {"talk": "n_talk"}, "x": 300, "y": 1270, "h": 900})
        st = script.build([beat(0, 5, "presenter", [], avatar="talk"), beat(5, 10, "hero", [item("a")])],
                          WORDS, 0.0, 10, {"a": 1}, CANVAS, style_)
        assert [k["pose"] for k in st["avatar"]["keys"]] == ["talk", None]
        assert st["avatar"]["talk"] and all(b <= 5 for _, b in st["avatar"]["talk"])

    def test_marks_follow_their_objects(self):
        st = script.build([beat(0, 10, "pair", [item("a", "left", on_word=0), item("b", "right", on_word=8)],
                                relation="arrow", title="Hello")],
                          WORDS, 0.0, 10, {"a": 1, "b": 1}, TABLETOP, STYLE)
        by = {m.get("text") or m["kind"]: m for m in st["marks"]}
        assert by["Hello"]["t0"] < by["left"]["t0"] < by["right"]["t0"]
        assert by["arrow"]["t0"] >= by["right"]["t0"] - 0.2

    def test_a_board_is_wiped_for_each_idea_and_drawn_in_by_hand(self):
        st = script.build([beat(0, 5, "hero", [item("a")]), beat(5, 10, "hero", [item("a")])],
                          WORDS, 0.0, 10, {"a": 1}, BOARD, STYLE)
        assert {s["id"] for s in st["sprites"]} == {"a_0_0", "a_0_1"}  # drawn again, not moved
        first = keys_of(st, "a_0_0")
        assert first[0]["reveal"] == 0 and any(k.get("reveal") == 1 for k in first[1:])
        wiped = [k for k in first if k["t"] >= 4.95]
        assert wiped[-1]["alpha"] == 0 and wiped[-1]["t"] == pytest.approx(4.95 + script.ERASE)

    def test_pinned_pieces_press_on_rather_than_drop(self):
        st = script.build([beat(0, 5, "hero", [item("a")])], WORDS, 0.0, 5, {"a": 1}, PINNED, STYLE)
        keys = keys_of(st, "a_0")
        assert keys[0]["lift"] == 0.5 and keys[-1]["ease"] == "back" and keys[-1]["scale"] == 1.0

    def test_puppets_walk_on_from_the_wings_and_their_labels_wait(self):
        st = script.build([beat(0, 6, "scene", [item("caesar", "Caesar", role="left")])],
                          WORDS, 0.0, 6, {"caesar": 0.5}, THEATRE, STYLE)
        keys = keys_of(st, "caesar_0")
        assert keys[0]["x"] < 0 and keys[0]["alpha"] == 1              # waiting in the wing
        arrived = next(k for k in keys if k.get("ease") == "out")
        assert arrived["t"] - keys[1]["t"] == pytest.approx(script.WALK)

    def test_in_a_scene_players_walk_between_places_and_sway_as_they_speak(self):
        st = script.build([
            beat(0, 5, "scene", [item("caesar", role="left")], backdrop="rome"),
            beat(5, 10, "scene", [item("caesar", role="right", says="Onwards")], backdrop="rubicon"),
        ], WORDS, 0.0, 10, {"caesar": 0.5, "rome": 0.56, "rubicon": 0.56}, THEATRE, STYLE)
        caesar = next(s for s in st["sprites"] if s["id"] == "caesar_0")
        walk = [k for k in caesar["keys"] if k.get("hop") == 16]
        assert walk and any(k.get("flip") == 1 for k in caesar["keys"] if 4 < k["t"] < 6)
        assert caesar["sway"] and caesar["sway"][0][0] > 5
        backs = [s for s in st["sprites"] if s.get("layer") == "back"]
        assert [s["src"] for s in backs] == ["rome", "rubicon"]
        assert backs[0]["keys"][-1]["x"] < 0                         # the old place slides off

    def test_a_bubble_appears_after_its_speaker_arrives(self):
        st = script.build([beat(0, 8, "lineup", [item("m", on_word=0), item("m", says="Red?", on_word=4)])],
                          WORDS, 0.0, 8, {"m": 0.6}, MEEPLES, STYLE)
        bubble = next(m for m in st["marks"] if m["kind"] == "bubble")
        speaker = keys_of(st, "m_1")
        assert bubble["t0"] > speaker[1]["t"]
        assert st["depth_sort"] is False                             # the theme decides, not the fmt


# --- frames, and the fade continuity ------------------------------------------------

BLACK, MINIMAL = compiled("quant_minimal")    # plain black: fade, typeset


class TestFramesAndFade:
    def test_a_stage_is_made_for_its_frame(self):
        wide = dict(TABLETOP, frame="wide")
        st = script.build([beat(0, 5, "hero", [item("a")])], WORDS, 0.0, 5, {"a": 1}, wide, STYLE)
        assert st["frame"] == {"w": 1920, "h": 1080} and st["world"] == {"w": 1920, "h": 1080}
        canvas = script.build([beat(0, 5, "hero", [item("a")]), beat(5, 10, "hero", [item("a")])],
                              WORDS, 0.0, 10, {"a": 1}, dict(CANVAS, frame="wide"), STYLE)
        assert canvas["world"]["w"] == 2 * 1920 + script.AREA_GAP

    def test_the_default_frame_is_a_vertical_short(self):
        assert frames.get(None) is frames.VERTICAL and frames.get("nope") is frames.VERTICAL
        assert style.compile(SimpleNamespace(style={}))[0]["frame"] == "vertical"

    def test_on_a_plain_background_things_fade_rather_than_leave(self):
        st = script.build([beat(0, 5, "hero", [item("a")]), beat(5, 10, "hero", [item("b")])],
                          WORDS, 0.0, 10, {"a": 1, "b": 1}, BLACK, STYLE)
        a = keys_of(st, "a_0")
        assert a[0]["alpha"] == 0 and a[0]["scale"] < 1                  # faded up
        leaving = [k for k in a if k["t"] >= 4.9]
        assert leaving[-1]["alpha"] == 0 and "x" not in leaving[-1]       # fades where it stands

    def test_the_same_title_stays_up_across_beats(self):
        st = script.build([beat(0, 5, "hero", [item("a")], title="The hats"),
                           beat(5, 10, "hero", [item("b")], title="The hats"),
                           beat(10, 15, "hero", [item("c")], title="Why")],
                          WORDS, 0.0, 15, {k: 1 for k in "abc"}, BLACK, STYLE)
        titles = [m for m in st["marks"] if m["kind"] == "title"]
        assert [m["text"] for m in titles] == ["The hats", "Why"]
        assert titles[0]["t1"] == pytest.approx(10.05)


# --- diagrams --------------------------------------------------------------------------

@pytest.fixture
def math_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(mathtext, "CACHE", tmp_path / "mathtext")
    return tmp_path / "mathtext"


INK = {"ink": "#FFFFFF", "accent": "#58C4DD", "series": ["#58C4DD", "#F9E45B", "#83C167"],
       "line": 3, "math_face": True}
BOX = (50, 400, 1030, 1200)


def settled(**raw):
    return diagrams.settle({"id": "d", **raw})


class TestExpressions:
    @pytest.mark.parametrize("text", ["x^2", "exp(-x^2/2)/sqrt(2*pi)", "normal(x, 0, 1)",
                                      "abs(sin(x)) + e", "-x + 3*x^3 - 2"])
    def test_maths_is_allowed(self, text):
        assert len(expr.sample(text, -2, 2, 10)) == 11

    @pytest.mark.parametrize("text", ["__import__('os').system('x')", "x.real", "(lambda y: y)(x)",
                                      "[x for x in (1,)]", "open('f')", "sin", "x if x else 1",
                                      "a + 1", "'text'", "x" * 200, ""])
    def test_anything_else_is_refused(self, text):
        with pytest.raises(expr.BadExpression):
            expr.parse(text)

    def test_undefined_points_break_the_curve(self):
        points = expr.sample("log(x)", -1, 1, 4)
        assert points[0] is None and points[-1] == (1.0, 0.0)


class TestMathtext:
    def test_a_formula_is_typeset_once_and_cached(self, math_cache):
        path, w, h = mathtext.render(r"$\frac{1}{2}$ of $x^2$", "#FFFFFF", 48)
        again = mathtext.render(r"$\frac{1}{2}$ of $x^2$", "#FFFFFF", 48)
        assert (path, w, h) == again and w > h > 40 and len(list(math_cache.iterdir())) == 1

    def test_what_cannot_be_typeset_becomes_words(self, math_cache):
        path, w, _ = mathtext.render(r"$\nosuchcommand{x$", "#FFFFFF", 40)
        assert path.exists() and w > 0

    def test_entries_are_set_as_maths_but_numbers_stay_numbers(self):
        assert mathtext.as_math("42") == "42" and mathtext.as_math("-3.5") == "-3.5"
        assert mathtext.as_math("x_1") == "$x_1$" and mathtext.as_math(r"\rho") == r"$\rho$"
        assert mathtext.as_math("Heads") == "Heads"


class TestDiagrams:
    def test_settle_bounds_and_drops_what_cannot_be_drawn(self):
        assert settled(kind="chart", bars=[]) is None
        assert settled(kind="nope") is None and diagrams.settle(None) is None
        assert settled(kind="plot", curves=[{"expr": "import os", "label": "", "on_word": 0}]) is None
        f = settled(kind="formula", lines=[{"text": f"$x_{i}$", "on_word": i} for i in range(9)])
        assert len(f["lines"]) == diagrams.MAX_LINES
        m = settled(kind="matrix", rows=[["1", "2", "3"], ["4"]])
        assert m["rows"] == [["1", "2", "3"], ["4", "", ""]]
        g = settled(kind="graph", nodes=[{"id": "a", "label": ""}, {"id": "b", "label": ""}],
                    edges=[{"from": "a", "to": "b", "label": "", "on_word": 0},
                           {"from": "a", "to": "zzz", "label": "", "on_word": 0}])
        assert [e["to"] for e in g["edges"]] == ["b"] and g["arrangement"] == "circle"
        n = settled(kind="number_line", range=[0, 5], points=[{"at": 9, "label": "", "on_word": 0}])
        assert n["range"] == (0, 9)                     # everything named is on the line

    @pytest.mark.parametrize("raw", [
        dict(kind="formula", lines=[{"text": r"$E = \frac{1}{2}(1 + E_H)$", "on_word": 1},
                                    {"text": "$E = 6$", "on_word": 4}]),
        dict(kind="bullets", lines=[{"text": "$A$ is symmetric", "on_word": -1},
                                    {"text": "and invertible", "on_word": -1}]),
        dict(kind="matrix", rows=[["1", "0"], ["0", "x_1"]]),
        dict(kind="chart", bars=[{"label": "X_1", "value": -2, "on_word": -1},
                                 {"label": "X_2", "value": 3, "on_word": -1}]),
        dict(kind="number_line", range=[-3, 3], points=[{"at": 0, "label": "start", "on_word": -1}],
             jumps=[{"from": 0, "to": 2, "label": "+2", "on_word": -1}], shade=[1, 2]),
        dict(kind="plot", range=[-3, 3], y_range=[0, 0], shade=[-1, 1],
             curves=[{"expr": "normal(x)", "label": r"\phi", "on_word": -1}],
             points=[{"at": 0, "y": 0.4, "label": "peak", "on_word": -1}]),
        dict(kind="graph", arrangement="row", directed=True,
             nodes=[{"id": "a", "label": "Idea"}, {"id": "b", "label": "Test"}],
             edges=[{"from": "a", "to": "b", "label": "", "on_word": -1}]),
    ])
    @pytest.mark.parametrize("frame", ["vertical", "wide"])
    def test_every_kind_is_drawn_inside_its_box(self, raw, frame, math_cache):
        box = layouts.diagram_box(frame, 0, True)
        prims, assets = diagrams.build(settled(**raw), box, INK, frame)
        assert prims and all(p["pid"].startswith("d:") for p in prims)
        assert all(path.exists() for path in assets.values())
        x0, y0, x1, y1 = box
        for p in prims:
            points = p.get("points") or [[p["x"], p.get("y", p.get("base"))]]
            for x, y in points:
                assert x0 - 60 <= x <= x1 + 60 and y0 - 90 <= y <= y1 + 90, (raw["kind"], p)

    def test_a_chart_labels_each_bar_beyond_its_end(self, math_cache):
        prims, _ = diagrams.build(settled(kind="chart", bars=[
            {"label": "up", "value": 2, "on_word": -1}, {"label": "down", "value": -1, "on_word": -1}]),
            BOX, INK, "vertical")
        bars = {p["pid"].split(":")[-1]: p for p in prims if p["kind"] == "bar"}
        labels = {p["pid"].split(":")[-1]: p for p in prims if "barlabel" in p["pid"]}
        assert bars["up"]["h"] > 0 > bars["down"]["h"]
        assert labels["up"]["y"] < bars["up"]["base"] - bars["up"]["h"]
        assert labels["down"]["y"] > bars["down"]["base"] - bars["down"]["h"]


class TestContinuedDiagrams:
    def build(self, *diagram_beats, fmt=None):
        beats_ = [beat(i * 4, i * 4 + 4, "diagram", [], diagram=settled(**d))
                  for i, d in enumerate(diagram_beats)]
        return script.build(beats_, WORDS, 0.0, 4 * len(beats_), {}, fmt or BLACK,
                            dict(STYLE, diagram=INK))

    def test_a_formula_builds_up_line_by_line(self, math_cache):
        one = [{"text": "$a = b$", "on_word": -1}]
        st = self.build(dict(kind="formula", lines=one),
                        dict(kind="formula", lines=one + [{"text": "$b = c$", "on_word": -1}]))
        maths = [m for m in st["marks"] if m["kind"] == "math"]
        assert len(maths) == 2                            # the first line wasn't drawn again
        assert maths[0]["t1"] == pytest.approx(8.05) and maths[1]["t0"] >= 4

    def test_a_continued_chart_moves_its_bars_on_one_scale(self, math_cache):
        st = self.build(dict(kind="chart", bars=[{"label": "a", "value": 1, "on_word": -1},
                                                 {"label": "b", "value": 2, "on_word": -1}]),
                        dict(kind="chart", bars=[{"label": "a", "value": 3, "on_word": -1},
                                                 {"label": "b", "value": -1, "on_word": -1}]))
        bars = [m for m in st["marks"] if m["kind"] == "bar"]
        assert len(bars) == 2 and all(len(b["keys"]) == 2 for b in bars)
        assert bars[0]["keys"][-1]["h"] > bars[0]["h"] and bars[1]["keys"][-1]["h"] < 0
        assert len([m for m in st["marks"] if m["kind"] == "stroke"]) == 2    # one set of axes
        assert st["math"]                                                     # labels typeset

    def test_a_new_diagram_replaces_the_last(self, math_cache):
        st = self.build(dict(kind="formula", lines=[{"text": "$a$", "on_word": -1}]),
                        dict(kind="formula", id="other", lines=[{"text": "$a$", "on_word": -1}]))
        maths = [m for m in st["marks"] if m["kind"] == "math"]
        assert len(maths) == 2 and maths[0]["t1"] == pytest.approx(4.05)

    def test_a_canvas_keeps_every_diagram(self, math_cache):
        st = self.build(dict(kind="formula", lines=[{"text": "$a$", "on_word": -1}]),
                        dict(kind="formula", lines=[{"text": "$a$", "on_word": -1}]),
                        fmt=CANVAS)
        assert all(m["t1"] is None for m in st["marks"] if m["kind"] == "math")


class TestDiagramInk:
    def test_data_colours_read_against_the_background(self):
        look = {"palette": ["#000000", "#111111", "#58C4DD", "#FFFFFF", "#F9E45B"]}
        assert theme.series(look, "#000000", "#FFFFFF") == ["#58C4DD", "#F9E45B"]

    def test_typeset_and_handwritten_maths(self):
        assert theme.theme(BLACK, MINIMAL)["diagram"]["math_face"] is True
        board_fmt, board_look = compiled("whiteboard")
        ink = theme.theme(board_fmt, board_look)["diagram"]
        assert ink["math_face"] is False and ink["hand"] == "Ink Free"


# --- the beats storyboard made safe -------------------------------------------------

def windows_and_words():
    words = words_for("one two three four five six seven eight nine ten eleven twelve", step=1.0)
    segments = [Segment(text="x", start=0.0, end=6.0), Segment(text="y", start=6.0, end=12.3)]
    return segments, words, storyboard.spans(segments, [(0, 1)], words)


def raw_beat(word, layout="hero", its=None, **more):
    return {"start_word": word, "layout": layout, "title": "", "relation": "", "avatar": "",
            "items": its if its is not None else [{"key": "Brain", "label": "the brain",
                                                   "on_word": word, "count": 1, "highlight": False}],
            "why": "", **more}


def raw_item(key, **more):
    return {"key": key, "label": key, "on_word": 0, "count": 1, "highlight": False, **more}


class TestSettle:
    def settle(self, raw_beats, fmt=TABLETOP, kit=None):
        segments, words, windows = windows_and_words()
        raw = {"concept": "c", "kit": kit or [{"key": "Brain", "name": "Brain", "description": "pink"}],
               "beats": raw_beats}
        return beats.settle(raw, windows, words, fmt)

    def test_the_first_beat_opens_the_window_and_times_come_from_words(self):
        settled, kit_used, _ = self.settle([raw_beat(3), raw_beat(7)])
        assert settled[0]["start"] == 0.0 and settled[1]["start"] == pytest.approx(6.9)
        assert settled[0]["end"] == settled[1]["start"] and settled[-1]["end"] == 12.3
        assert kit_used == {"brain": {"name": "Brain", "kind": "object", "description": "pink"}}

    def test_a_layout_that_cannot_take_its_objects_is_changed(self):
        its = [raw_item(k) for k in "abcd"]
        settled, _, _ = self.settle([raw_beat(0, "hero", its)])
        assert settled[0]["layout"] == "grid"

    def test_no_host_means_no_presenter(self):
        settled, _, _ = self.settle([raw_beat(0, "presenter", [], avatar="talk")])
        assert settled[0]["layout"] != "presenter" and settled[0]["avatar"] == ""
        settled, _, _ = self.settle([raw_beat(0, "presenter", [], avatar="talk")], fmt=CANVAS)
        assert settled[0]["layout"] == "presenter" and settled[0]["avatar"] == "talk"

    def test_a_beat_too_short_to_read_gives_way_to_the_next(self):
        settled, _, _ = self.settle([raw_beat(0), raw_beat(1), raw_beat(7)])
        assert [b["start_word"] for b in settled] == [0, 7]
        assert settled[0]["items"][0]["on_word"] == 1          # the next beat's, opening earlier

    def test_a_word_outside_its_beat_is_dropped(self):
        its = [raw_item("brain", on_word=11)]
        settled, _, _ = self.settle([raw_beat(0, its=its), raw_beat(7)])
        assert settled[0]["items"][0]["on_word"] == -1

    def test_a_traveller_keeps_its_start_and_end_when_a_repeat_is_dropped(self):
        its = [raw_item(k) for k in ("yawn", "yawn", "you")]
        settled, _, _ = self.settle([raw_beat(0, "travel", its)])
        assert [(i["key"], i.get("place")) for i in settled[0]["items"]] == [("yawn", None),
                                                                            ("you", "end")]

    def test_only_styles_that_draw_diagrams_are_asked_for_them(self):
        beat_shape = lambda fmt: beats.schema(fmt)["properties"]["beats"]["items"]  # noqa: E731
        assert "diagram" in beat_shape(BLACK)["required"]
        assert "diagram" not in beat_shape(TABLETOP)["properties"]
        assert "diagram" in beats.allowed_layouts(BLACK)
        assert "diagram" not in beats.allowed_layouts(TABLETOP)
        assert "diagram" in beats.brief(BLACK, MINIMAL, {}) and "DIAGRAMS" in beats.brief(BLACK, MINIMAL, {})

    def test_a_diagram_makes_a_diagram_beat(self):
        chart = {"kind": "chart", "id": "c", "rows": [], "range": [0, 0], "y_range": [0, 0],
                 "shade": [0, 0], "arrangement": "circle", "directed": False,
                 "elements": [{"role": "bar", "text": "A", "ref": "", "to": "", "a": 2, "b": 0,
                               "on_word": 1},
                              {"role": "bar", "text": "B", "ref": "", "to": "", "a": 3, "b": 0,
                               "on_word": 11}]}
        its = [raw_item(k) for k in "abc"]
        settled, _, _ = self.settle([raw_beat(0, "row", its, diagram=chart), raw_beat(7)], fmt=BLACK)
        first = settled[0]
        assert first["layout"] == "diagram" and len(first["items"]) == 2
        assert [b["on_word"] for b in first["diagram"]["bars"]] == [1, -1]   # 11 is the next beat's

    def test_a_diagram_that_cannot_be_drawn_leaves_an_ordinary_beat(self):
        empty = {"kind": "chart", "id": "c", "elements": []}
        settled, _, _ = self.settle([raw_beat(0, "diagram", [raw_item("brain")], diagram=empty)],
                                    fmt=BLACK)
        assert settled[0]["layout"] != "diagram" and settled[0]["diagram"] is None
        settled, _, _ = self.settle([raw_beat(0, "hero", [raw_item("brain")], diagram=empty)])
        assert settled[0]["diagram"] is None                  # a tabletop never draws them

    def test_only_a_lineup_may_repeat_a_figure(self):
        its = [raw_item("meeple") for _ in range(4)]
        settled, _, _ = self.settle([raw_beat(0, "lineup", its), raw_beat(7, "row", its)],
                                    fmt=MEEPLES)
        assert len(settled[0]["items"]) == 4 and len(settled[1]["items"]) == 1

    def test_labels_counts_and_speech_are_bounded(self):
        its = [raw_item("coin", label="a very long label that goes on and on", count=500,
                        highlight=True, says="x" * 200)]
        settled, _, _ = self.settle([raw_beat(0, "group", its)])
        it = settled[0]["items"][0]
        assert len(it["label"]) <= 28 and it["count"] == layouts.MAX_COUNT and len(it["says"]) <= 48

    def test_a_table_is_bounded_and_a_table_beat_without_one_is_changed(self):
        grid = [[f"a long cell number {c}" for c in range(6)] for _ in range(6)]
        settled, _, _ = self.settle([raw_beat(0, "table", [], table=grid),
                                     raw_beat(7, "table", [raw_item("brain")], table=[])])
        assert len(settled[0]["table"]) == 4 and all(len(r) == 4 for r in settled[0]["table"])
        assert all(len(c) <= 16 for r in settled[0]["table"] for c in r)
        assert settled[1]["layout"] != "table"

    def test_a_scene_backdrop_joins_the_kit_and_carries_on(self):
        kit = [{"key": "rubicon", "name": "the Rubicon", "description": "a river at dawn"},
               {"key": "caesar", "name": "Caesar", "kind": "character", "description": "stubby"}]
        settled, kit_used, _ = self.settle([
            raw_beat(0, "scene", [raw_item("caesar", role="left")], backdrop="rubicon"),
            raw_beat(7, "scene", [raw_item("caesar", role="right")])], fmt=THEATRE, kit=kit)
        assert [b["backdrop"] for b in settled] == ["rubicon", "rubicon"]
        assert kit_used["rubicon"]["kind"] == "backdrop" and kit_used["caesar"]["kind"] == "character"
        assert settled[0]["items"][0]["role"] == "left"


# --- the kit -----------------------------------------------------------------------

def png(path: Path, size=(400, 300)):
    from PIL import Image
    im = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    for x in range(300, 300 + size[0]):
        for y in range(400, 400 + size[1], 4):
            im.putpixel((x, y), (200, 50, 50, 255))
    im.save(path)
    return path


class TestKit:
    @pytest.fixture
    def channel(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.paths.CHANNELS_DIR", tmp_path)
        drawn = []

        def fake_draw(prompt, out, model, **kw):
            drawn.append((Path(out).name, kw.get("transparent"), kw.get("references"), prompt))
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            if str(out).endswith(".jpg"):
                from PIL import Image
                Image.new("RGB", (1008, 1792), (240, 235, 225)).save(out)
            else:
                png(Path(out))
            return Path(out)
        monkeypatch.setattr(kit.images, "draw", fake_draw)
        channel = ChannelConfig(key="demo")
        channel.animation.style = dict(style.starting_point("felt_science")["answers"])
        return SimpleNamespace(channel=channel, drawn=drawn,
                               look=style.compile(channel.animation)[1])

    def test_objects_are_drawn_once_and_reused(self, channel):
        wanted = {"brain": {"name": "Brain", "kind": "object", "description": "pink"}}
        first = kit.objects(channel.channel, channel.look, TABLETOP, wanted)
        again = kit.objects(channel.channel, channel.look, TABLETOP, wanted)
        assert first == again and len(channel.drawn) == 1 and channel.drawn[0][1] is True
        assert kit.index("demo", channel.look, "top")["brain"]["name"] == "Brain"
        assert kit.aspects(first)["brain"] > 1          # trimmed to the object

    def test_each_view_has_its_own_kit(self, channel):
        wanted = {"brain": {"name": "Brain", "kind": "object", "description": "pink"}}
        kit.objects(channel.channel, channel.look, TABLETOP, wanted)          # from above
        kit.objects(channel.channel, channel.look, CANVAS, wanted)            # face-on
        assert len(channel.drawn) == 2

    def test_characters_are_drawn_as_the_style_draws_people(self, channel):
        kit.objects(channel.channel, channel.look, TABLETOP,
                    {"caesar": {"name": "Caesar", "kind": "character", "description": "a general"}})
        assert channel.look["people"] and channel.look["people"] in channel.drawn[0][3]

    def test_a_backdrop_is_a_whole_frame_not_a_cut_out(self, channel):
        from PIL import Image
        pictures = kit.objects(channel.channel, channel.look, THEATRE,
                               {"rubicon": {"name": "the Rubicon", "kind": "backdrop",
                                            "description": "a river at dawn"}})
        assert channel.drawn[0][1] is False and pictures["rubicon"].suffix == ".jpg"
        assert Image.open(pictures["rubicon"]).size == (1080, 1920)
        assert "a river at dawn" in channel.drawn[0][3]

    def test_the_surface_is_drawn_once_at_frame_size(self, channel):
        from PIL import Image
        first = kit.surface(channel.channel, channel.look, TABLETOP)
        assert kit.surface(channel.channel, channel.look, TABLETOP) == first
        assert Image.open(first).size == (1080, 1920) and len(channel.drawn) == 1
        assert "completely empty" in channel.drawn[0][3]     # no doodles on the board

    def test_a_wide_frame_has_its_own_surface_and_backdrops_but_shares_the_rest(self, channel):
        from PIL import Image
        wide = dict(TABLETOP, frame="wide")
        surface = kit.surface(channel.channel, channel.look, wide)
        assert surface.name.endswith("_wide.jpg") and Image.open(surface).size == (1920, 1080)
        wanted = {"brain": {"name": "Brain", "kind": "object", "description": "pink"}}
        kit.objects(channel.channel, channel.look, TABLETOP, wanted)
        kit.objects(channel.channel, channel.look, wide, wanted)             # the same cut-out
        backdrop = {"hall": {"name": "hall", "kind": "backdrop", "description": "a great hall"}}
        tall = kit.objects(channel.channel, channel.look, THEATRE, backdrop)
        broad = kit.objects(channel.channel, channel.look, dict(THEATRE, frame="wide"), backdrop)
        assert tall["hall"] != broad["hall"] and Image.open(broad["hall"]).size == (1920, 1080)
        assert len(channel.drawn) == 1 + 1 + 2
        assert "hall@wide" not in kit.index("demo", channel.look, "front")    # not shown to the storyboard
        assert "hall@wide" in kit.index("demo", channel.look, "front", every_frame=True)

    def test_the_host_has_every_pose_open_and_closed_cropped_together(self, channel):
        from PIL import Image
        poses = kit.narrator(channel.channel, channel.look, CANVAS)
        assert set(poses) == {p + s for p in kit.POSES for s in ("", "_open")}
        sizes = {Image.open(p).size for p in poses.values()}
        assert len(sizes) == 1                                    # one shared box
        edits = [d for d in channel.drawn if d[2]]
        assert len(edits) == len(poses) - 1                       # all but the first from a reference


# --- the composited pipeline -----------------------------------------------------

class TestCompose:
    def test_a_video_is_beats_kit_stage_render(self, monkeypatch, tmp_path):
        from pipeline.animation.compositor import render
        segments = [Segment(text="one two three four", start=0.0, end=4.0)]
        words = words_for("one two three four", step=1.0)
        channel = ChannelConfig(key="demo")
        channel.animation.style = dict(style.starting_point("felt_science")["answers"])
        plan = SimpleNamespace(channel=channel, seed=SimpleNamespace(title="demo"),
                               script=SimpleNamespace(segments=segments),
                               voiceover=SimpleNamespace(word_timings=words))
        monkeypatch.setattr(beats, "write", lambda *a, **k: {
            "concept": "c", "kit": [{"key": "brain", "name": "Brain", "description": "pink"},
                                    {"key": "ghost", "name": "Ghost", "description": ""}],
            "beats": [raw_beat(0, "pair", [raw_item("brain"), raw_item("ghost", on_word=2)])]})
        monkeypatch.setattr(kit, "index", lambda *a: {})
        pic = png(tmp_path / "brain.png")
        monkeypatch.setattr(kit, "objects", lambda ch, lk, fmt, wanted: {"brain": pic})
        monkeypatch.setattr(kit, "surface", lambda *a: tmp_path / "surface.jpg")
        rendered = []
        monkeypatch.setattr(render, "render", lambda st, assets, out: rendered.append((st, assets))
                            or Path(out))
        monkeypatch.setattr(compose.finish, "grade", lambda src, out, look: Path(out))
        result = stage.make(plan, [0], {}, tmp_path / "work", tail=0.5)
        assert [c["kind"] for c in result.clips] == ["animation"]
        st, assets = rendered[0]
        assert st["surface"] == {"image": "surface"} and set(assets) == {"brain", "surface"}
        assert [s["src"] for s in st["sprites"]] == ["brain"]          # the ghost was left out
        assert any("couldn't be drawn" in n for n in result.notes)
        assert st["duration"] == pytest.approx(4.5)
        saved = json.loads((tmp_path / "work" / "beats.json").read_text())
        assert saved["style"] == style.compile(channel.animation)[1]["key"]

    def test_a_scene_has_no_surface_under_its_backdrops(self, tmp_path, monkeypatch):
        channel = ChannelConfig(key="demo")
        monkeypatch.setattr(kit, "surface", lambda *a: pytest.fail("a scene drew a surface"))
        stage_theme, assets = compose.dress(channel, PAPER, THEATRE, {"rubicon": tmp_path / "r.jpg"})
        assert "surface" not in assets and stage_theme["surface"] == {"color": stage_theme["surface"]["color"]}


# --- captions ------------------------------------------------------------------------

class TestCaptions:
    def test_name_cards_ask_the_storyboard_for_captions(self):
        shot = storyboard.schema(captions=True)["properties"]["shots"]["items"]
        assert "caption" in shot["required"]
        assert "caption" not in storyboard.schema()["properties"]["shots"]["items"]["properties"]
        fmt, _ = compiled("painted_history")
        assert fmt["captions"] and not compiled("storybook_scripture")[0]["captions"]

    def test_captions_are_laid_over_the_shots_that_have_them(self, monkeypatch, tmp_path):
        from pipeline.animation.compositor import render
        made, laid = [], []
        monkeypatch.setattr(render, "caption_png", lambda text, labels, out: made.append(text) or out)
        monkeypatch.setattr(stage.finish, "overlay_captions",
                            lambda clip, caps, out: laid.append(caps) or out)
        shots = [{"index": 0, "start": 10.0, "end": 14.0, "caption": "Moses"},
                 {"index": 1, "start": 14.0, "end": 16.0, "caption": ""}]
        fmt, look = compiled("painted_history")
        out = stage._captions(tmp_path / "a.mp4", shots, {"start": 10.0}, fmt, look, tmp_path)
        assert made == ["Moses"] and out.name == "a_c.mp4"
        (_, start, end), = laid[0]
        assert start == pytest.approx(0.35) and end == pytest.approx(3.75)


# --- the director ----------------------------------------------------------------

class TestDirector:
    def test_a_style_that_draws_its_own_diagrams_is_offered_no_templates(self, monkeypatch):
        from pipeline import director
        seen = {}

        def fake_call(system, user, schema, **kw):
            seen["enum"] = schema["properties"]["segments"]["items"]["properties"]["medium"]["enum"]
            return {"segments": []}
        monkeypatch.setattr(director, "call_json", fake_call)
        director.direct([Segment(text="t", start=0, end=3)], "s", 100, animation=True,
                        own_diagrams=True)
        assert "template" not in seen["enum"] and "diagram" not in seen["enum"]
        director.direct([Segment(text="t", start=0, end=3)], "s", 100, animation=True)
        assert "template" in seen["enum"]


# --- the real thing ----------------------------------------------------------------

@pytest.mark.slow
def test_a_stage_renders_in_chrome(tmp_path):
    from PIL import Image
    from pipeline.animation.compositor import render
    pic = png(tmp_path / "a.png")
    st = script.build([beat(0, 2, "hero", [item("a", "a label")], title="Hello")],
                      WORDS, 0.0, 2.0, {"a": 4 / 3}, TABLETOP, theme.theme(TABLETOP, FELT))
    frame = render.still(st, {"a": pic}, 1.8, tmp_path / "f.jpg")
    assert Image.open(tmp_path / "f.jpg").size == (1080, 1920) and frame


def test_a_composited_style_animates_without_a_fal_key(monkeypatch, tmp_path):
    """Composited styles have no video model, so a missing FAL_KEY must
    not turn them into still illustrations (it briefly did)."""
    from pipeline import director, visuals
    from pipeline.animation import stage as animation_stage
    from tests.test_animation import visuals_plan
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(visuals.stage, "_restore", lambda: None)
    monkeypatch.setattr(visuals.stage, "_save", lambda plan: None)
    seen = {}

    def fake_direct(segments, *a, **k):
        seen.update(k)
        return [{"index": i, "medium": "animation", "template": "", "brief": "b", "need": 9,
                 "reason": "r"} for i in range(len(segments))]
    monkeypatch.setattr(director, "direct", fake_direct)
    result = animation_stage.Result()
    result.clips = [{"first": 0, "last": 1, "clip": str(tmp_path / "a.mp4"), "kind": "animation"}]
    monkeypatch.setattr(animation_stage, "make", lambda *a, **k: result)
    plan = visuals.run(visuals_plan(tmp_path, start="felt_science"))
    assert seen["animation"] is True and seen["own_diagrams"] is True
    assert plan.scene_clips == result.clips
    assert not any("FAL_KEY" in n for n in plan.scene_notes)
