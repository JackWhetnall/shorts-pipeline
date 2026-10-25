"""
Films made overnight at batch prices, overseen, within a ceiling (decision 094).

The owner: make it cheaper "without sacrificing quality", with the batch
APIs and "an overnight schedule for generating videos"; a scheduled
Claude session to oversee it on the subscription; and a spending cap set
where it is "a rare 'something has gone fundamentally wrong' rather than
'this one's a bit more expensive than the others'", that never scraps a
film nearly made.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as N

import pytest
from PIL import Image

from core import costs, film_budget, job_context, production
from core.channels import within_hours
from pipeline.animation import images
from pipeline.animation.models import ImageModel


# --- the ceiling -------------------------------------------------------------------------------

def _cost(channel, film, usd):
    costs._write(costs.CostRecord(ts=0, service="claude", operation="x", model="m", cost_usd=usd,
                                  channel_key=channel, production=film))


def test_every_cost_knows_its_film(tmp_path):
    token = job_context.set_production("t0009")
    try:
        costs._write(costs.CostRecord(ts=0, service="claude", operation="x", model="m", cost_usd=0.5,
                                      channel_key="doc"))
    finally:
        job_context.reset_production(token)
    row = json.loads(Path(costs.COST_LOG_PATH).read_text(encoding="utf-8").splitlines()[-1])
    assert row["production"] == "t0009"
    assert film_budget.spent("doc", "t0009") == 0.5


def test_the_ceiling_is_twice_a_usual_film_and_pauses_without_scrapping(tmp_path, monkeypatch):
    monkeypatch.setattr(production, "load", lambda k, s, t=None: {"subtopic_id": s})
    monkeypatch.setattr(production, "all_for", lambda k: [])
    assert film_budget.ceiling("doc", "t1") == max(film_budget.FLOOR, 2 * film_budget.USUAL_UNTIL_KNOWN)
    _cost("doc", "t1", 6.9)
    film_budget.check("doc", "t1")                                   # under: carries on
    _cost("doc", "t1", 0.2)
    with pytest.raises(film_budget.FilmOverBudget) as stopped:
        film_budget.check("doc", "t1")
    assert "Everything made so far is kept" in stopped.value.user_message


def test_the_usual_film_is_measured_from_the_channels_own(tmp_path, monkeypatch):
    films = [{"subtopic_id": f"t{i}", "stages": {"video": {"state": "ready", "at": f"2026-10-0{i}"}}}
             for i in range(1, 4)]
    monkeypatch.setattr(production, "all_for", lambda k: films)
    monkeypatch.setattr(production, "state", lambda d, s: d["stages"].get(s, {}).get("state", "todo"))
    for i, usd in ((1, 1.5), (2, 2.0), (3, 2.5)):
        _cost("doc", f"t{i}", usd)
    assert film_budget.usual("doc") == 2.0
    monkeypatch.setattr(production, "load", lambda k, s, t=None: {"subtopic_id": s, "budget_extra": 2.0})
    assert film_budget.ceiling("doc", "t9") == max(film_budget.FLOOR, 4.0) + 2.0


def test_a_paid_call_for_a_film_past_its_ceiling_is_never_made(monkeypatch):
    from pipeline import llm
    monkeypatch.setattr(film_budget, "check_current", lambda: (_ for _ in ()).throw(
        film_budget.FilmOverBudget("over", user_message="Paused")))
    sent = []
    monkeypatch.setattr(llm, "client", lambda: sent.append(1))
    with pytest.raises(film_budget.FilmOverBudget):
        llm._call({"model": "m"}, "op", "m")
    assert sent == []


# --- pictures as one batch ---------------------------------------------------------------------

class _FakeOpenAI:
    """Files, batches and their results, in memory."""

    def __init__(self, fail_key=None):
        self.uploads, self.created, self.deleted, self.fail_key = [], [], [], fail_key

    def post(self, url, headers=None, data=None, files=None, timeout=None):
        if url.endswith("/files"):
            self.uploads.append((data["purpose"], files["file"][0]))
            if data["purpose"] == "batch":
                self.lines = [json.loads(x) for x in files["file"][1].decode().splitlines()]
            return N(status_code=200, json=lambda: {"id": f"file-{len(self.uploads)}"}, text="")
        if url.endswith("/batches"):
            self.created.append(json.loads(data))
            return N(status_code=200, json=lambda: {"id": "batch-1"}, text="")
        raise AssertionError(url)

    def get(self, url, headers=None, timeout=None):
        if url.endswith("/batches/batch-1"):
            return N(json=lambda: {"status": "completed", "output_file_id": "out-1"})
        import base64
        import io
        buf = io.BytesIO()
        Image.new("RGB", (16, 9), (10, 200, 10)).save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        rows = []
        for line in self.lines:
            ok = line["custom_id"] != self.fail_key
            rows.append(json.dumps({"custom_id": line["custom_id"], "response": {
                "status_code": 200 if ok else 400,
                "body": {"data": [{"b64_json": b64}], "usage": {"input_tokens": 1000, "output_tokens": 280,
                         "input_tokens_details": {"image_tokens": 900, "text_tokens": 100}}} if ok else
                {"error": {"message": "refused"}}}}))
        return N(text="\n".join(rows))

    def delete(self, url, headers=None, timeout=None):
        self.deleted.append(url)


@pytest.fixture
def openai(monkeypatch, tmp_path):
    fake = _FakeOpenAI()
    monkeypatch.setattr(images, "requests", N(post=fake.post, get=fake.get, delete=fake.delete,
                                              RequestException=Exception))
    monkeypatch.setattr(images, "_key", lambda: "k")
    monkeypatch.setattr(images, "_batch_journal_path", lambda: tmp_path / "journal.json")
    monkeypatch.setattr(images, "BATCH_POLL_FIRST", 0)
    return fake


def _jobs(tmp_path, n=3):
    ref = tmp_path / "style.png"
    Image.new("RGB", (64, 64), (200, 10, 10)).save(ref)
    model = ImageModel(key="m", label="M", provider="openai", model="gpt-image-2.5-flare")
    return [{"key": i, "prompt": f"picture {i}", "out": tmp_path / f"kf_{i:02d}.jpg", "model": model,
             "references": [ref], "size": (1536, 864), "operation": "animation_keyframe"} for i in range(n)]


def test_a_storyboard_goes_as_one_batch_at_half_price(openai, tmp_path):
    out = images.draw_batch(_jobs(tmp_path))
    assert sorted(out) == [0, 1, 2] and all(p.exists() for p in out.values())
    assert [p for p, _ in openai.uploads] == ["vision", "batch"]           # the reference once, then the batch
    assert openai.created[0]["endpoint"] == "/v1/images/edits"
    assert openai.lines[0]["body"]["images"] == [{"file_id": "file-1"}]
    rows = [json.loads(x) for x in Path(costs.COST_LOG_PATH).read_text(encoding="utf-8").splitlines()]
    full = costs.openai_image_usage_cost("gpt-image-2.5-flare", {"input_tokens": 1000, "output_tokens": 280,
                                         "input_tokens_details": {"image_tokens": 900, "text_tokens": 100}})
    assert all(r["batch"] for r in rows) and abs(rows[0]["cost_usd"] - full / 2) < 1e-9
    assert openai.deleted and not json.loads((tmp_path / "journal.json").read_text())


def test_a_picture_the_batch_couldnt_draw_comes_back_empty(openai, tmp_path):
    openai.fail_key = "1"
    out = images.draw_batch(_jobs(tmp_path))
    assert out[1] is None and out[0] is not None


def test_a_batch_left_waiting_is_picked_up_not_paid_for_again(openai, tmp_path):
    jobs = _jobs(tmp_path, 2)
    images._write_batch_journal(images._batch_key(jobs), {"batch": "batch-1", "files": [], "at": 9e12})
    openai.lines = [{"custom_id": "0"}, {"custom_id": "1"}]
    out = images.draw_batch(jobs)
    assert openai.created == [] and openai.uploads == [] and all(out.values())


def test_a_batch_too_slow_is_cancelled_and_its_pictures_drawn_at_once(openai, tmp_path, monkeypatch):
    # Decision 102: one sat "in progress" 16 hours, nothing drawn, and held
    # the channel's autopilot all night.
    jobs = _jobs(tmp_path, 2)
    images._write_batch_journal(images._batch_key(jobs), {"batch": "batch-9", "files": [], "at": 1.0})
    cancelled, drawn = [], []
    real_post = openai.post

    def post(url, **kw):
        if url.endswith("/batches/batch-9/cancel"):
            cancelled.append(url)
            return N(status_code=200)
        return real_post(url, **kw)
    monkeypatch.setattr(images.requests, "post", post)
    monkeypatch.setattr(images.requests, "get", lambda url, **kw: N(json=lambda: {"status": "cancelled"}
                                                                    if cancelled else {"status": "in_progress"}))
    monkeypatch.setattr(images, "draw", lambda prompt, out, model, **kw: drawn.append(prompt) or out)
    monkeypatch.setattr(images.time, "sleep", lambda s: None)
    out = images.draw_batch(jobs)
    assert cancelled and drawn == ["picture 0", "picture 1"] and all(out.values())


# --- the autopilot overnight, the overseer at its checkpoints ----------------------------------

def test_hours_run_past_midnight():
    assert {h for h in range(24) if within_hours("22-8", h)} == {22, 23, 0, 1, 2, 3, 4, 5, 6, 7}
    assert within_hours("", 13) and not within_hours("9-17", 8)


def _channel(**doc):
    defaults = dict(auto_make=True, ahead=3, teasers=0, overseen=False, hours="")
    defaults.update(doc)
    return N(key="doc", format="documentary", archived=False, publishing=N(enabled=True),
             animation=N(style={"approach": "acted"}), documentary=N(**defaults))


def test_an_overseen_script_waits_for_the_overseer_and_stages_start_only_in_hours(monkeypatch):
    from core import auto_films
    states = {"pitch": "approved", "outline": "approved", "script": "ready", "stills": "todo", "video": "todo"}
    monkeypatch.setattr(auto_films, "_busy", lambda k: False)
    monkeypatch.setattr(auto_films, "_candidates", lambda c: [({"id": "t1", "title": "T"}, {"stages": {}}, False)])
    monkeypatch.setattr(production, "current", lambda d: next(s for s, v in states.items() if v != "approved"))
    monkeypatch.setattr(production, "state", lambda d, s: states[s])
    approved, started = [], []
    monkeypatch.setattr(production, "approve", lambda *a, **k: approved.append(a[2]))
    monkeypatch.setattr(auto_films, "start", lambda c, r, s: started.append(s) or "j")
    assert auto_films.step(_channel(overseen=True)) == "" and approved == []      # left for the overseer
    assert auto_films.step(_channel()) and approved == ["script"]                 # not overseen: approved
    states["script"] = "approved"
    monkeypatch.setattr(auto_films, "within_hours", lambda text, hour: False, raising=False)
    import core.channels as config
    monkeypatch.setattr(config, "within_hours", lambda text, hour: False)
    assert auto_films.step(_channel(hours="22-8")) == "" and started == []        # out of hours: waits
    monkeypatch.setattr(config, "within_hours", lambda text, hour: True)
    assert auto_films.step(_channel(hours="22-8")) and started == ["stills"]


def test_the_overseer_edits_approves_and_notes_through_one_tool(monkeypatch):
    from core import overseer
    data = {"script": {"scenes": [{"chapter": 1, "narration": "Salt never leaves.", "direction": "d", "same_as": 0}],
                       "description": "x"}, "history": []}
    monkeypatch.setattr(production, "update", lambda k, s, change, *a: change(data))
    overseer.edit("doc", "t1", 0, narration="Salt leaves, slowly, into seafloor mud.", direction="A seabed.")
    overseer.note("doc", "t1", "Fixed the thesis.")
    assert data["script"]["scenes"][0]["narration"].startswith("Salt leaves") and "same_as" not in data["script"]["scenes"][0]
    assert data["history"][-1]["by"] == "overseer" and data["overseer"][0]["text"] == "Fixed the thesis."
    with pytest.raises(SystemExit):
        overseer.approve("doc", "t1", "video")                                    # the owner's alone


def test_the_overseer_reads_the_teasers_before_they_are_made(monkeypatch):
    # Decision 111: the teasers' scripts wait for the overseer on an overseen channel.
    from core import auto_films, overseer
    data = {"stages": {"pitch": {"state": "approved"}, "outline": {"state": "approved"},
                       "script": {"state": "approved"}, "stills": {"state": "approved"},
                       "video": {"state": "approved"}, "teasers": {"state": "ready"}},
            "teasers": {"scripts": [{"title": "T", "scenes": [{"narration": "a", "picture": 0}]}]},
            "history": [], "script": {"scenes": [{"direction": "d"}]}}
    monkeypatch.setattr(auto_films, "_busy", lambda k: False)
    monkeypatch.setattr(auto_films, "_candidates", lambda c: [({"id": "t1", "title": "T"}, data, False)])
    monkeypatch.setattr(production, "update", lambda k, s, change, *a: change(data))
    monkeypatch.setattr(production, "load", lambda k, s, t="": data)
    started = []
    monkeypatch.setattr(auto_films, "start", lambda c, r, s: started.append(s) or "j")
    assert auto_films.step(_channel(overseen=True)) == "" and started == []        # waits for the overseer
    overseer.edit_teaser("doc", "t1", 0, 0, narration="Find out in the full video on our channel.")
    assert data["teasers"]["scripts"][0]["scenes"][0]["narration"].startswith("Find out")
    assert "[0] Find out" in overseer.teaser_sheet("doc", "t1")
    overseer.approve("doc", "t1", "teasers")
    assert data["teasers"]["reviewed"] and auto_films.step(_channel(overseen=True)) and started == ["teasers"]
    assert "Checkpoint 3: the teasers" in open("docs/overseer.md", encoding="utf-8").read()


def test_teasers_sharing_a_title_cant_be_approved(monkeypatch):
    # 25 Oct: "Before the Stop Sign Existed" was queued twice.
    from core import overseer
    data = {"teasers": {"scripts": [{"title": "Same Title"}, {"title": "same  title"}], "videos": []}}
    monkeypatch.setattr(overseer.production, "load", lambda key, sid: data)
    monkeypatch.setattr(overseer.channel_config, "load_channels", lambda: {})
    assert overseer.teaser_title_clashes("doc", "t1") == ["same title"]
    with pytest.raises(SystemExit):
        overseer.approve("doc", "t1", "teasers")
