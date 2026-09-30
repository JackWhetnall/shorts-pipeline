"""
The style grammar and its builder (decision 053): the questions and their
conditions, answers made to fit, what they compile to, the sentence that
describes them, the starting points, a style from a description, the
preview of exactly the style chosen, and the settings page's builder.

Models and services are faked; nothing here spends money.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.channels import ChannelConfig
from pipeline.animation import style
from pipeline.animation.style import describe, gallery, preview

QUESTIONS = [q["id"] for q in style.questions()]


def settings(answers: dict, **more):
    return SimpleNamespace(style=answers, **more)


def _conditions(option):
    for key in ("when", "not"):
        c = option.get(key)
        if c:
            yield from (c if isinstance(c, list) else [c])


# --- the grammar ---------------------------------------------------------------------

class TestGrammar:
    def test_conditions_only_look_back_at_real_options(self):
        """A condition may only name earlier questions (so choosing in order
        always works) and options that exist, as lists."""
        for index, q in enumerate(style.questions()):
            rules = [(o["id"], c) for o in q["options"] for c in _conditions(o)]
            rules += [(f"default {d['option']}", d["when"]) for d in q.get("defaults") or []]
            for where, condition in rules:
                for asked, allowed in condition.items():
                    assert asked in QUESTIONS[:index], (q["id"], where, asked)
                    assert isinstance(allowed, list), (q["id"], where, asked)
                    known = {o["id"] for o in style.grammar()["by_id"][asked]["options"]}
                    assert set(allowed) <= known, (q["id"], where, set(allowed) - known)
            for d in q.get("defaults") or []:
                assert d["option"] in q["by_id"], (q["id"], d["option"])

    def test_every_option_is_reachable(self):
        """Some combination of earlier answers offers every option."""
        seen = {q: set() for q in QUESTIONS}
        rng = random.Random(3)
        for _ in range(4000):
            answers = {}
            for q in style.questions():
                offered = style.options_for(q["id"], answers)
                if not offered:
                    continue
                answers[q["id"]] = rng.choice(offered)["id"]
                seen[q["id"]].add(answers[q["id"]])
        for q in style.questions():
            assert seen[q["id"]] == set(q["by_id"]), (q["id"], set(q["by_id"]) - seen[q["id"]])

    def test_every_option_says_what_it_is(self):
        for q in style.questions():
            assert q["ask"].endswith("?") and q.get("short"), q["id"]
            for o in q["options"]:
                assert o.get("label") and "phrase" in o, (q["id"], o["id"])
                if o.get("custom"):
                    assert "{custom}" in o["phrase"], (q["id"], o["id"])

    def test_every_material_has_a_board_wherever_the_stage_asks_for_one(self):
        """A stage whose surface is made of the material ("{board}": a felt
        tabletop, a wooden game board) finds it described by every material
        offered on it, so no composited style gets a generic surface."""
        rng = random.Random(5)
        for _ in range(3000):
            answers = {}
            for q in style.questions():
                offered = style.options_for(q["id"], answers)
                if offered:
                    answers[q["id"]] = rng.choice(offered)["id"]
            stage = style.q_option("stage", answers["stage"])
            material = style.q_option("material", answers["material"])
            assert (material.get("sets") or {}).get("image"), answers["material"]
            if "{board}" in str((stage.get("sets") or {}).get("surface", "")) \
                    and not material.get("custom"):
                boards = material["sets"].get("boards") or {}
                assert answers["stage"] in boards or "default" in boards, \
                    (answers["stage"], answers["material"])

    def test_every_answer_is_either_composited_or_generated(self):
        rng = random.Random(7)
        for _ in range(400):
            answers = {}
            for q in style.questions():
                offered = style.options_for(q["id"], answers)
                if offered:
                    answers[q["id"]] = rng.choice(offered)["id"]
            fmt, look = style.compile(settings(answers))
            assert fmt["engine"] in ("compositor", "generated")
            if style.composited(fmt):
                assert fmt["layouts"] and fmt["kit_view"] and fmt["continuity"] in (
                    "move", "fade", "persist", "clear", "scene"), answers
                assert fmt["entrance"] in ("drop", "pin", "draw", "puppet", "slide", "pop", "fade")
            assert look["image"] and look["palette"], answers


# --- answers made to fit ----------------------------------------------------------

class TestNormalise:
    def test_nothing_given_is_a_whole_style(self):
        answers, changed = style.normalise({})
        assert changed == [] and all(answers.get(q) for q in ("approach", "stage", "material"))

    def test_an_answer_that_no_longer_fits_is_replaced_and_said(self):
        answers, changed = style.normalise({"approach": "acted", "stage": "tabletop"})
        assert answers["stage"] != "tabletop" and changed == ["stage"]
        assert style.valid(style.q_option("stage", answers["stage"]), answers)

    def test_later_answers_are_kept_when_they_still_fit(self):
        given = dict(style.starting_point("meeple_logic")["answers"])
        answers, changed = style.normalise(given)
        assert changed == [] and {k: answers[k] for k in QUESTIONS if k in given} == \
            {k: given[k] for k in QUESTIONS if k in given}

    def test_something_else_needs_its_words(self):
        answers, changed = style.normalise({"approach": "objects", "stage": "tabletop",
                                            "material": "custom"})
        assert answers["material"] != "custom" and changed == ["material"]
        answers, _ = style.normalise({"approach": "objects", "stage": "tabletop",
                                      "material": "custom",
                                      "custom": {"material": "bottle caps", "people": "unused"}})
        assert answers["material"] == "custom"
        assert answers["custom"] == {"material": "bottle caps"}       # only for a custom answer

    def test_a_question_nothing_fits_is_not_asked(self):
        answers, _ = style.normalise({"approach": "acted"})
        assert "presenter" not in answers

    def test_every_starting_point_is_already_a_valid_style(self):
        ids = [sp["id"] for sp in style.starting_points()]
        assert len(ids) == len(set(ids)) >= 24
        for sp in style.starting_points():
            _, changed = style.normalise(sp["answers"])
            assert changed == [], (sp["id"], changed)
            assert {"label", "description", "suits", "subject"} <= set(sp), sp["id"]


# --- what it compiles to --------------------------------------------------------------

class TestCompile:
    @pytest.mark.parametrize("sid", [sp["id"] for sp in style.starting_points()])
    def test_every_starting_point_compiles(self, sid):
        fmt, look = style.compile(settings(style.starting_point(sid)["answers"]))
        assert fmt["label"] and look["description"].endswith(".")
        assert look["key"].startswith(style.slug(fmt["answers"]["material"]))
        if fmt["surface"]:
            assert "{board}" not in fmt["surface"]
        if style.composited(fmt) and fmt["areas"] != "canvas" and fmt["continuity"] != "scene":
            assert fmt["surface"] or look["canvas"], sid    # drawn, or a plain colour
        if fmt["continuity"] == "scene":
            assert fmt["backdrop"] and "{medium}" not in fmt["backdrop"]

    def test_later_answers_override_and_listed_fields_add_up(self):
        fmt, look = style.compile(settings({"approach": "objects", "stage": "game_board",
                                            "material": "matte_3d", "people": "tokens"}))
        assert fmt["view"] == "angle" and fmt["entrance"] == "drop"
        assert "game" in look["people"].lower() or "meeple" in look["people"].lower()
        assert "minimalist 3D" in look["image"]

    def test_a_host_is_the_first_of_the_cast(self):
        fmt, _ = style.compile(settings(style.starting_point("diagram_host")["answers"]))
        assert fmt["avatar"] and "host" in fmt["narrator"]

    def test_the_users_words_go_where_the_option_says(self):
        fmt, look = style.compile(settings({"approach": "objects", "stage": "tabletop",
                                            "material": "custom",
                                            "custom": {"material": "bottle caps and string"}}))
        assert "bottle caps and string" in look["image"]
        assert "bottle caps and string" in style.summary(fmt["answers"])
        assert style.title(fmt["answers"]).startswith("bottle caps")

    def test_the_channels_palette_wins_and_the_styles_are_suggestions(self):
        answers = style.starting_point("felt_science")["answers"]
        _, own = style.compile(settings(answers))
        _, mine = style.compile(settings(answers, palette=["#111111", "#222222", "#333333",
                                                           "#444444"]))
        assert mine["palette"] == ["#111111", "#222222", "#333333", "#444444"]
        assert own["palette"] == own["suggested_palettes"][0] and len(own["suggested_palettes"]) > 1


class TestWords:
    def test_the_sentence_reads_as_one(self):
        answers, _ = style.normalise(style.starting_point("stubby_paper_history")["answers"])
        sentence = style.summary(answers)
        assert sentence[0].isupper() and sentence.endswith(".") and ";" in sentence
        assert "paper" in sentence and "stubby" in sentence
        assert "  " not in sentence and ", ," not in sentence

    def test_every_starting_point_has_a_short_title(self):
        for sp in style.starting_points():
            title = style.title(style.normalise(sp["answers"])[0])
            assert 3 < len(title) <= 60 and ":" in title, (sp["id"], title)

    def test_the_browser_gets_no_prompt_text(self):
        data = json.dumps(style.for_browser())
        assert "boards" not in data and "guide" not in data and '"image"' not in data
        felt = next(o for o in style.for_browser()["questions"][2]["options"] if o["id"] == "felt")
        assert felt["palette"]


# --- the browser agrees ------------------------------------------------------------

def _js_normalise(cases: list) -> list:
    app = (Path(__file__).resolve().parent.parent / "web" / "static" / "app.js").read_text(
        encoding="utf-8")
    start, end = app.index("function styleMatches"), app.index("function initAnimationSettings")
    program = app[start:end] + (
        "\nconst data = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
        "process.stdout.write(JSON.stringify(data.cases.map(c => "
        "styleNormalise(data.questions, c))));\n")
    payload = json.dumps({"questions": style.for_browser()["questions"], "cases": cases})
    out = subprocess.run(["node", "-e", program], input=payload, capture_output=True,
                         text=True, encoding="utf-8", timeout=60, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_builder_offers_exactly_what_the_pipeline_accepts():
    """The builder (app.js) evaluates the grammar's conditions itself; given
    any answers, right or wrong, it must reach the same style as the
    server's normalise."""
    rng = random.Random(11)
    cases = []
    for _ in range(600):
        case = {}
        for q in style.questions():
            if rng.random() < 0.85:
                case[q["id"]] = rng.choice(q["options"])["id"]        # often invalid on purpose
        if rng.random() < 0.3:
            case["custom"] = {rng.choice(QUESTIONS): "my own words"}
        cases.append(case)
    cases += [sp["answers"] for sp in style.starting_points()]
    for case, js in zip(cases, _js_normalise(cases)):
        answers, changed = style.normalise(case)
        assert js["answers"] == answers and js["changed"] == changed, case


# --- from a description ---------------------------------------------------------------

class TestDescribe:
    def test_a_description_becomes_answers_that_fit(self, monkeypatch):
        seen = {}

        def fake_call(system, user, schema, **kw):
            seen["schema"], seen["user"] = schema, user
            return {**{q: "" for q in QUESTIONS}, "approach": "acted", "stage": "tabletop",
                    "material": "paper", "people": "stubby", "custom_material": "",
                    "style_notes": "  warm   candlelight ", "palette": ["#112233", "nope"],
                    "why": "Because."}
        monkeypatch.setattr(describe, "call_json", fake_call)
        result = describe.describe("stubby paper people acting out history")
        assert result["style"]["approach"] == "acted" and result["style"]["stage"] != "tabletop"
        assert result["changed"] == ["stage"] and result["notes"] == "warm candlelight"
        assert result["palette"] == [] and result["summary"].endswith(".")
        assert seen["schema"]["properties"]["material"]["enum"][-1] == ""
        assert "stubby paper people" in seen["user"] and "only when" in seen["user"]


# --- the preview of exactly this style ----------------------------------------------

def _jpg(path, size=(1080, 1920)):
    from PIL import Image
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 190, 170)).save(path)
    return Path(path)


class TestPreview:
    @pytest.fixture
    def fakes(self, monkeypatch, tmp_path):
        from pipeline.animation.compositor import render
        monkeypatch.setattr(preview, "PREVIEWS_DIR", tmp_path / "previews")
        calls = {"llm": 0, "render": 0, "draw": 0}

        def fake_call(system, user, schema, **kw):
            calls["llm"] += 1
            if "beat" in schema["properties"]:
                return {"line": "Yawns spread because brains copy what they see nearby",
                        "kit": [{"key": "brain", "name": "Brain", "kind": "object",
                                 "description": "pink"}],
                        "beat": {"start_word": 0, "layout": "hero", "title": "", "relation": "",
                                 "avatar": "", "items": [{"key": "brain", "label": "brain",
                                                          "on_word": 2, "count": 1,
                                                          "highlight": False}],
                                 "why": ""}}
            return {"line": "A line.", "image": "A fox in snow.", "motion": "It trots."}
        monkeypatch.setattr(preview, "call_json", fake_call)
        monkeypatch.setattr(preview.kit, "objects",
                            lambda ch, lk, fmt, wanted: {"brain": _jpg(tmp_path / "b.png", (400, 300))})
        monkeypatch.setattr(preview.kit, "index", lambda *a: {})
        monkeypatch.setattr(preview.compose, "dress",
                            lambda ch, lk, fmt, pics, result=None: ({
                                "step": 0, "jitter": 0, "surface": {"color": "#fff"},
                                "shadow": {"mode": "none"}, "labels": {}}, dict(pics)))

        def fake_still(stage_data, assets, t, out):
            calls["render"] += 1
            calls["stage"] = stage_data
            return _jpg(out)
        monkeypatch.setattr(render, "still", fake_still)

        def fake_draw(prompt, out, model, **kw):
            calls["draw"] += 1
            calls["prompt"] = prompt
            return _jpg(out)
        monkeypatch.setattr(preview.images, "draw", fake_draw)
        return calls

    def channel(self, sid):
        channel = ChannelConfig(key="demo", topics=["Why yawns are contagious"])
        channel.animation.style = dict(style.starting_point(sid)["answers"])
        return channel

    def test_a_composited_style_is_filmed_by_the_real_stage_once(self, fakes):
        channel = self.channel("felt_science")
        assert preview.cached(channel, channel.animation) == {"still": None, "moving": None}
        first = preview.still(channel, channel.animation)
        again = preview.still(channel, channel.animation)
        assert first == again and fakes["llm"] == 1 and fakes["render"] == 1
        assert [s["src"] for s in fakes["stage"]["sprites"]] == ["brain"]
        assert preview.cached(channel, channel.animation)["still"] == first

    def test_another_style_or_subject_is_another_preview(self, fakes):
        channel = self.channel("felt_science")
        a = preview.still(channel, channel.animation)
        b = preview.still(channel, channel.animation, subject="How bees see")
        channel.animation.style = {**channel.animation.style, "words": "marker"}
        c = preview.still(channel, channel.animation)
        assert len({a, b, c}) == 3

    def test_a_widescreen_preview_reuses_the_written_moment(self, fakes):
        channel = self.channel("felt_science")
        tall = preview.still(channel, channel.animation)
        wide = preview.still(channel, channel.animation, frame="wide")
        assert tall != wide and fakes["llm"] == 1 and fakes["render"] == 2
        assert fakes["stage"]["frame"] == {"w": 1920, "h": 1080}
        assert preview.cached(channel, channel.animation, frame="wide")["still"] == wide
        assert preview.cached(channel, channel.animation)["still"] == tall

    def test_a_host_style_shows_its_host_and_a_diagram_style_a_diagram(self, fakes, monkeypatch):
        seen = []
        real = preview.call_json
        monkeypatch.setattr(preview, "call_json",
                            lambda system, user, schema, **kw: seen.append(user)
                            or real(system, user, schema, **kw))
        for sid in ("diagram_host", "quant_minimal"):
            channel = self.channel(sid)
            preview.still(channel, channel.animation)
        assert "presenter layout" in seen[0] and "diagram layout" in seen[1]

    def test_a_generated_style_draws_a_first_frame_in_its_look(self, fakes):
        channel = self.channel("painted_history")
        out = preview.still(channel, channel.animation)
        assert out.exists() and fakes["draw"] == 1 and "A fox in snow." in fakes["prompt"]

    def test_moving_a_generated_style_needs_the_key(self, fakes, monkeypatch):
        from core.errors import PipelineError
        monkeypatch.delenv("FAL_KEY", raising=False)
        channel = self.channel("painted_history")
        with pytest.raises(PipelineError) as failed:
            preview.moving(channel, channel.animation)
        assert "FAL_KEY" in failed.value.user_message

    def test_the_gallery_draws_each_starting_point_once(self, fakes, monkeypatch, tmp_path):
        monkeypatch.setattr(gallery, "EXAMPLES_DIR", tmp_path / "examples")
        made = gallery.draw(["felt_science", "painted_history"])
        from PIL import Image
        assert [p.stem for p in made] == ["felt_science", "painted_history"]
        assert Image.open(made[0]).size == (540, 960)
        assert gallery.draw(["felt_science"]) == []


# --- the settings page's builder -------------------------------------------------------

from tests.test_web import client, config_path, csrf  # noqa: E402,F401  (fixtures)


def _form(client, **fields):
    return {"csrf_token": csrf(client), "content_mode": "topic", "voice": "21m00Tcm4TlvDq8ikWAM",
            "style_prompt": "Write something.", "topics": "coffee", "anim_present": "1", **fields}


class TestBuilder:
    def test_the_page_carries_the_grammar_and_starting_points(self, client):
        body = client.get("/channels/test_channel/settings").get_data(as_text=True)
        assert "data-anim-grammar" in body and "data-anim-starts" in body
        assert "How does this channel show what it" in body
        assert 'data-style-start="meeple_logic"' in body

    def test_saving_keeps_only_a_style_that_fits(self, client, config_path):
        from core.channels import load_channels
        client.post("/channels/test_channel/settings", data=_form(
            client, anim_style_approach="acted", anim_style_stage="tabletop",
            anim_style_material="paper"))
        saved = load_channels(config_path)["test_channel"].animation.style
        assert saved["approach"] == "acted" and saved["stage"] != "tabletop"
        assert style.normalise(saved)[1] == []

    def test_something_else_is_saved_with_its_words(self, client, config_path):
        from core.channels import load_channels
        client.post("/channels/test_channel/settings", data=_form(
            client, anim_style_approach="objects", anim_style_stage="tabletop",
            anim_style_material="custom", anim_style_custom_material="  bottle   caps ",
            anim_style_custom_people="ignored"))
        saved = load_channels(config_path)["test_channel"].animation.style
        assert saved["material"] == "custom" and saved["custom"] == {"material": "bottle caps"}

    def test_the_style_in_the_form_is_described_before_it_is_saved(self, client):
        response = client.post("/api/channels/test_channel/animation/style",
                               headers={"X-CSRF-Token": csrf(client)},
                               json={"style": {"approach": "acted", "stage": "tabletop"}})
        data = response.get_json()
        assert data["changed"] == ["stage"] and data["summary"].startswith("Acted out")
        assert data["preview"] == {"still": None, "moving": None}
        assert "frames" in data["bible"]

    def test_a_description_builds_a_style(self, client, monkeypatch):
        monkeypatch.setattr(describe, "call_json", lambda *a, **k: {
            **{q: "" for q in QUESTIONS}, "approach": "objects", "stage": "game_board",
            "material": "matte_3d", "people": "tokens", "style_notes": "", "palette": [],
            "why": "Meeples."})
        data = client.post("/api/channels/test_channel/animation/describe",
                           headers={"X-CSRF-Token": csrf(client)},
                           json={"text": "minimal 3D meeples for logic puzzles"}).get_json()
        assert data["style"]["stage"] == "game_board" and data["why"] == "Meeples."
        short = client.post("/api/channels/test_channel/animation/describe",
                            headers={"X-CSRF-Token": csrf(client)}, json={"text": "hi"})
        assert short.status_code == 400

    def test_a_preview_is_made_and_served(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(preview, "PREVIEWS_DIR", tmp_path)
        made = []

        def fake_still(channel, settings_, subject="", frame=None):
            made.append((channel.key, settings_.style["material"], subject))
            fmt, look = style.compile(settings_)
            out = preview.folder_for(channel.key) / (preview._key(fmt, look, subject or
                                                     preview._subject(channel, ""), "") + ".jpg")
            return _jpg(out, (54, 96))
        monkeypatch.setattr(preview, "still", fake_still)
        data = client.post("/api/channels/test_channel/animation/style-preview",
                           headers={"X-CSRF-Token": csrf(client)},
                           json={"style": {"approach": "objects", "stage": "tabletop",
                                           "material": "clay"}}).get_json()
        assert made == [("test_channel", "clay", "")]
        assert data["preview"]["still"].startswith("/channels/test_channel/animation/style-preview/")
        assert client.get(data["preview"]["still"]).status_code == 200
        assert client.get("/channels/test_channel/animation/style-preview/..%2Fx.jpg").status_code \
            in (400, 404)
        assert client.get("/channels/test_channel/animation/style-preview/nope.txt").status_code == 404

    def test_the_frame_switch_asks_for_a_widescreen_preview(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(preview, "PREVIEWS_DIR", tmp_path)
        made = []
        monkeypatch.setattr(preview, "still",
                            lambda channel, settings_, subject="", frame=None: made.append(frame))
        answers = {"approach": "diagrams", "stage": "black"}
        data = client.post("/api/channels/test_channel/animation/style-preview",
                           headers={"X-CSRF-Token": csrf(client)},
                           json={"style": answers, "frame": "wide"}).get_json()
        assert made == ["wide"] and data["frame"] == "wide"
        client.post("/api/channels/test_channel/animation/style-preview",
                    headers={"X-CSRF-Token": csrf(client)},
                    json={"style": answers, "frame": "sideways"})
        assert made[-1] == "vertical"
        body = client.get("/channels/test_channel/settings").get_data(as_text=True)
        assert 'data-style-frame="wide"' in body

    def test_starting_point_examples_are_served(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(gallery, "EXAMPLES_DIR", tmp_path)
        _jpg(tmp_path / "meeple_logic.jpg", (54, 96))
        assert client.get("/animation/styles/meeple_logic.jpg").status_code == 200
        assert client.get("/animation/styles/felt_science.jpg").status_code == 404
        assert client.get("/animation/styles/nope.jpg").status_code == 404
