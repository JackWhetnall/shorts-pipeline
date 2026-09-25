"""
Motion-graphics templates (pipeline.templates) and the visual director
(pipeline.director, pipeline.visuals). The model is faked; one slow test
films a template in real Chrome.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.channels import ChannelConfig
from core.errors import ExternalServiceError
from pipeline import director, illustrate, visuals
from pipeline.plan import Segment, WordTiming
from pipeline.scenes import art
from pipeline.templates import fill, library, page, samples, tex, theme

WORDS = [(w, round(i * 0.4, 2)) for i, w in enumerate(
    "Dogs catch yawns from owners but strangers barely trigger one and toddlers never do".split())]


def no_icons(name):
    return ""


# --- the templates ---------------------------------------------------------------

@pytest.mark.parametrize("name", list(library.TEMPLATES))
def test_every_template_builds_from_its_sample(name):
    slots = samples.SAMPLES[name]
    times = samples.sample_times(name, slots)
    html = page.build(name, slots, times, art.resolve({"preset": "clean_flat"}), 6.0, no_icons)
    assert "window.__start" in html and "data-in=" in html
    for beat in library.TEMPLATES[name]["beats"](slots):
        assert beat in times


def test_every_sample_uses_only_its_templates_slots():
    for name, slots in samples.SAMPLES.items():
        assert all(slots.get(k) for k in library.TEMPLATES[name]["required"]), name


def test_the_catalogue_names_every_template():
    text = library.catalogue()
    assert all(f"- {name}:" in text for name in library.TEMPLATES)


def test_text_on_a_fill_is_whichever_reads_best():
    # Regression: white text on white cards, and light text on a pale
    # yellow on the chalkboard look (where ink and white are both light).
    assert theme.text_on("#FFFFFF", "#FFFFFF") == "#15161C"
    assert theme.text_on("#F7D56B", "#F4F1E8", "#23332B") in ("#23332B", "#15161C")
    assert theme.text_on("#1F2233", "#1F2233") == "#FFFFFF"


def test_a_filled_card_keeps_its_fill_whatever_the_finish():
    for key in art.presets():
        css = theme.css(art.resolve({"preset": key}))
        assert css.rstrip().endswith("!important; }") and ".card.filled" in css.split("}")[-3]


def test_the_tex_subset_becomes_html():
    out = tex.to_html(r"\color{accent1}{a^2} + \frac{1}{2} = \sqrt{x}")
    assert "tex-accent1" in out and "<sup>2</sup>" in out
    assert "class='frac'" in out and "class='sqrt'" in out and " + " in out
    assert "\\" not in out
    assert tex.to_html("-b") == "−b"                        # a leading minus stays tight


def test_text_that_might_break_the_page_is_escaped():
    slots = {"value": 3, "caption": "<script>alert(1)</script>"}
    html = page.build("big_number", slots, {"kicker": 0, "value": 1, "caption": 2},
                      art.resolve({}), 5.0, no_icons)
    assert "<script>alert(1)" not in html


# --- filling -------------------------------------------------------------------------

def test_fill_validation_reports_missing_and_long_slots():
    raw = {"slots": {"title": "x" * 80, "left": {"label": "Dogs"}}, "beats": {}}
    _, _, problems = fill.validate("versus", raw, WORDS, 6.0)
    text = " ".join(problems)
    assert "Missing slot 'right'" in text and "'title' is 80 characters" in text


def test_beats_become_times_in_order_and_gaps_are_filled():
    raw = {"slots": {"title": "t", "items": [{"text": "a"}, {"text": "b"}, {"text": "c"}]},
           "beats": {"title": 0, "item0": 4, "item1": 99, "item2": 2}}
    _, times, _ = fill.validate("list", raw, WORDS, 6.0)
    assert list(times) == ["title", "item0", "item1", "item2"]
    values = list(times.values())
    assert values == sorted(values)                          # never out of order
    assert times["item0"] == pytest.approx(1.6)


def test_nothing_enters_before_the_hook_text_has_gone():
    times = fill.hold_back({"title": 0.2, "item0": 0.8, "item1": 3.0}, 2.0)
    assert times == {"title": 2.0, "item0": 2.2, "item1": 3.0}


def test_a_template_makes_only_its_declared_sounds():
    assert fill.cues("myth_fact", {"myth": 0.5, "strike": 1.5, "fact": 2.5}) == [
        [1.65, "whoosh", 0.8], [2.65, "chime", 0.8]]
    assert fill.cues("list", {"title": 0.2, "item0": 1.0}) == []


def test_a_template_is_repaired_once_then_filled(monkeypatch, tmp_path):
    answers = iter([{"slots": {"left": {"label": "Dogs"}}, "beats": {}},
                    {"slots": {"title": "Who spreads it", "left": {"label": "Dogs", "value": "Often"},
                               "right": {"label": "Strangers", "value": "Rarely"}},
                     "beats": {"title": 0, "left": 1, "right": 6}}])
    calls = []
    monkeypatch.setattr(fill, "write", lambda *a, **k: calls.append(k.get("problems")) or next(answers))
    monkeypatch.setattr("pipeline.scenes.render.render_page", lambda html, d, out: out)
    clip, notes = fill.make("versus", "dogs vs strangers", WORDS, 6.0, "narration",
                            art.resolve({}), tmp_path / "icons", tmp_path / "seg1_template", 0.5)
    assert calls[0] is None and "Missing slot 'right'." in calls[1]
    saved = json.loads((tmp_path / "seg1_template.json").read_text(encoding="utf-8"))
    assert saved["template"] == "versus" and saved["cues"][0][1] == "pop"


# --- the director ----------------------------------------------------------------------

SEGS = [Segment("You see someone yawn.", "a person yawning", start=0, end=4),
        Segment("Brain scans show empathy circuits light up.", "brain scan", start=4, end=9),
        Segment("Dogs catch yawns, strangers barely do, toddlers never.", "dog yawning", start=9, end=15)]


def _directed(monkeypatch, rows, share, skip=frozenset()):
    calls = []
    monkeypatch.setattr(director, "call_json", lambda *a, **k: calls.append(a) or {"segments": rows})
    return director.direct(SEGS, "yawning", share, skip), calls


ROWS = [{"index": 0, "medium": "footage", "template": "", "brief": "a person yawning", "need": 1, "reason": "people"},
        {"index": 1, "medium": "illustration", "template": "", "brief": "a glowing brain", "need": 8, "reason": "can't film"},
        {"index": 2, "medium": "template", "template": "versus", "brief": "dogs vs strangers", "need": 6, "reason": "comparison"}]


def test_all_footage_never_asks_the_director(monkeypatch):
    out, calls = _directed(monkeypatch, ROWS, 0)
    assert calls == [] and {r["medium"] for r in out} == {"footage"}


def test_the_slider_is_the_bar_a_graphic_must_clear(monkeypatch):
    out, _ = _directed(monkeypatch, ROWS, 30)                       # bar 7
    assert [r["medium"] for r in out] == ["footage", "illustration", "footage"]
    out, _ = _directed(monkeypatch, ROWS, 50)                       # bar 5
    assert [r["medium"] for r in out] == ["footage", "illustration", "template"]


def test_always_animated_never_leaves_footage(monkeypatch):
    out, _ = _directed(monkeypatch, ROWS, 100)
    assert "footage" not in [r["medium"] for r in out]


def test_painted_segments_are_left_alone(monkeypatch):
    out, calls = _directed(monkeypatch, ROWS, 50, skip={0})
    assert [r["index"] for r in out] == [1, 2] and "[0]" not in calls[0][1]


def test_the_director_is_never_told_the_slider(monkeypatch):
    _, calls = _directed(monkeypatch, ROWS, 30)
    assert "30" not in calls[0][1] and "%" not in calls[0][1]


# --- the visuals stage ------------------------------------------------------------------

@pytest.fixture
def plan(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.scenes.stage.job_context.load_json_checkpoint", lambda n: None)
    monkeypatch.setattr("pipeline.scenes.stage.job_context.save_json_checkpoint", lambda n, d: None)
    channel = ChannelConfig(key="c")
    channel.scenes.share = 50
    return SimpleNamespace(channel=channel, script=SimpleNamespace(segments=SEGS, screen_hook=""),
                           voiceover=SimpleNamespace(word_timings=[WordTiming("x", 0, 0.2)]),
                           seed=SimpleNamespace(title="yawning"), out_dir=tmp_path, stem="v",
                           scene_clips=[])


def test_each_medium_is_made_and_a_failure_falls_back_to_footage(plan, monkeypatch):
    monkeypatch.setattr(director, "direct", lambda *a: [dict(r) for r in ROWS])
    monkeypatch.setattr(visuals.fill, "make", lambda *a, **k: (Path("tpl.mp4"), []))

    def broken(*a, **k):
        raise ExternalServiceError("OpenAI", "down", user_message="Couldn't draw an illustration.")

    monkeypatch.setattr(visuals.illustrate, "make", broken)
    visuals.run(plan)
    assert plan.scene_clips == [{"first": 2, "last": 2, "clip": "tpl.mp4", "kind": "template"}]
    assert plan.scenes_fell_back == 1 and "uses footage instead" in plan.scene_notes[0]


def test_a_painting_keeps_its_segment(plan, monkeypatch):
    plan.scene_clips = [{"first": 0, "last": 0, "clip": "art.mp4", "kind": "artwork"}]
    seen = {}
    monkeypatch.setattr(director, "direct", lambda segs, subj, share, skip: seen.setdefault("skip", skip) and [])
    visuals.run(plan)
    assert seen["skip"] == {0} and plan.scene_clips[0]["kind"] == "artwork"


def test_an_illustration_asks_for_no_text_and_room_for_captions():
    prompt = illustrate.prompt_for("a glowing brain", art.resolve({"preset": "clean_flat"}))
    assert "no text" in prompt.lower() and "bottom third" in prompt


# --- the checks that let the first Curiosity Leak video through -------------------------

def test_text_the_colour_of_its_own_pill_is_made_readable():
    from pipeline.scenes import writer
    raw = {"props": [], "elements": [
        {"id": "a", "type": "label", "text": "Strong", "color": "label_fill", "x": 1, "y": 1}],
        "actions": [{"target": "a", "do": "appear", "word": 0, "dur": 0.5}]}
    scene, _ = writer.validate(raw, WORDS, 5.0)
    assert scene["elements"][0]["color"] == "ink"


def test_a_blank_frame_is_caught_without_asking_anyone():
    import base64
    import io
    from PIL import Image, ImageDraw
    from pipeline import editor_check

    def jpeg(image):
        out = io.BytesIO(); image.save(out, format="JPEG")
        return base64.b64encode(out.getvalue()).decode()

    blank = Image.new("RGB", (540, 960), (250, 244, 232))
    busy = blank.copy()
    ImageDraw.Draw(busy).rectangle((60, 120, 480, 560), fill=(40, 40, 60))
    assert editor_check.looks_empty(jpeg(blank)) and not editor_check.looks_empty(jpeg(busy))


# --- filmed for real (slow) -----------------------------------------------------------------

@pytest.mark.slow
def test_a_template_films_and_counts_up(tmp_path):
    from pipeline.scenes import render
    from pipeline.scenes.render import _Page
    slots = samples.SAMPLES["big_number"]
    times = samples.sample_times("big_number", slots)
    html = page.build("big_number", slots, times, art.resolve({}), 6.0, no_icons)
    try:
        with _Page(html=html) as p:
            p.page.evaluate("window.__seek(0.1)")
            early = p.page.evaluate("document.querySelector('.bn-num').textContent")
            p.page.evaluate("window.__seek(5.9)")
            late = p.page.evaluate("document.querySelector('.bn-num').textContent")
            overflow = p.page.evaluate(
                "[...document.querySelectorAll('[data-fit]')].some(e => e.scrollWidth > e.clientWidth + 2)")
    except Exception as exc:
        if "Chrome" in str(exc):
            pytest.skip("Chrome isn't installed")
        raise
    assert early in ("", "Age 0+") and late == "Age 4+" and not overflow
    out = render.render_page(html, 1.0, tmp_path / "t.mp4", fps=10)
    assert out.stat().st_size > 1000
