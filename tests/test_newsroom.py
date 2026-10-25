"""
The newsroom (decision 127): a film's angle, outline and script made by
roles on the owner's Claude subscription, each able to send the work back or
scrap it, before money is spent. The owner, on 21 Oct: "at no point is there
any verification that topic X will actually result in a good script".

- a pitch comes with evidence of demand and enough beats for nine minutes,
  or it isn't taken;
- no film is commissioned, passed on from its proof, or passed from its
  edit with a score under 6, and each kind of rework has a limit;
- a scrapped film leaves the plan with its reason;
- a proof's first chapter, and every chapter of a draft, is long enough;
- a script editor's line edits are made; the picture editor's plan is held
  to the code's counts;
- a passed film's angle, outline and script are approved by the newsroom,
  and the autopilot draws it; it never writes a newsroom channel's films;
- the work is handed out a film nearest done first, within points a
  session and a week, and handed out again if it's never handed in;
- the newsroom's files live under the channel's folder, so a rename
  carries them (decision 057).
"""

from __future__ import annotations

import json

import pytest

from core import auto_films, curriculum, newsroom, overseer, production, storyboard
from core.channels import ChannelConfig
from pipeline.documentary import cast as library
from pipeline.documentary import script

HOUR = 3600


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(curriculum, "CURRICULA_DIR", tmp_path / "curricula")
    monkeypatch.setattr(production, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(newsroom, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(library, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(library, "merge", lambda *a, **k: None)
    monkeypatch.setattr(script, "words_per_second", lambda channel: 2.5)
    monkeypatch.setattr(overseer, "status", lambda: [])
    monkeypatch.setattr("core.lessons.for_prompt", lambda key: "")
    curriculum.start("why", "Questions", [{"title": "Everyday", "summary": "", "level": "foundation",
                                           "target_subtopics": 9}])
    curriculum.add_subtopics("why", "u01", [{"title": f"Why Does Thing {n} Happen?"} for n in range(6)])
    monkeypatch.setattr(storyboard, "upcoming", lambda channel, count=12: [
        s for s in curriculum.subtopics("why") if s["status"] == curriculum.PENDING][:count])
    monkeypatch.setattr(curriculum, "progress", lambda key: {"pending": 6, "running_low": False})
    channel = ChannelConfig(key="why", format="documentary", voice="v")
    channel.documentary.minutes = 1.0
    channel.documentary.kind = "explainer"
    channel.documentary.newsroom = True
    monkeypatch.setattr(newsroom, "_channel", lambda key: channel)
    return channel


def _hand_in(channel, aid, data):
    path = newsroom.work_dir(channel.key) / f"{aid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return newsroom.submit(channel.key, aid)


def _issue(channel, role):
    """The next assignment, which must be `role`'s, with a fresh session."""
    newsroom.save_ledger(channel.key, {**newsroom.load_ledger(channel.key), "done": []})
    row, why = newsroom.next_assignment(channel)
    assert row is not None, why
    assert row["role"] == role, (row["role"], role)
    return row


def _pitch(sid, title):
    return {"film": sid, "question": "Why?", "answer": "Because, surprisingly.", "why_care": "Everyone wonders.",
            "demand": [{"query": "why thing", "found": "a 40,000-view video on a 2,000-sub channel"}],
            "beats": [{"beat": f"part {n}", "reveal": f"reveal {n}"} for n in range(6)],
            "angle": {"title": title, "thumbnail": {"subject": "a thing", "words": "NOT WHAT YOU THINK"},
                      "promise": "You'll know why.", "hook": "A kettle boils at seventy degrees on Everest.",
                      "open_loop": "But why?"},
            "risks": "It could be thin."}


def _line(n):
    return " ".join(["word"] * n) + "."


OUTLINE = {"title_options": ["T"], "through_line": "x", "promise": "p", "want": "w", "open_loops": ["Why?"],
           "visual_concept": "v",
           "chapters": [{"title": "The Strange Fact", "says": "s", "turn": "t", "shows": "x", "sound": "none",
                         "minutes": 0.4},
                        {"title": "The Real Cause", "says": "s", "turn": "t", "shows": "x", "sound": "none",
                         "minutes": 0.6}],
           "settings": [{"name": "Kitchen", "scale": "human", "description": "a kitchen"}],
           "cast": []}


def _scene(chapter, words, direction="A kettle on a stove, whole and at rest"):
    return {"chapter": chapter, "direction": direction, "cast": [], "framing": "medium", "camera": "push_in",
            "caption": "", "narration": _line(words), "setting": "Kitchen", "medium": "picture",
            "art_query": "", "card": {}, "speaker": ""}


VIEWERS = [{"who": "a commuter", "clicks": True, "click_why": "odd", "leaves_at": -1, "leave_why": "kept"},
           {"who": "a science fan", "clicks": True, "click_why": "new", "leaves_at": -1, "leave_why": "kept"},
           {"who": "a teenager", "clicks": False, "click_why": "dull", "leaves_at": 2, "leave_why": "slow"}]


def _to(channel, state):
    """Walk the first film to `state` through each role, all approving."""
    pitch = _issue(channel, "pitch")
    assert _hand_in(channel, pitch["id"], {"pitches": [_pitch(s, f"Why Does Thing {s[-1]} Happen")
                                                       for s in pitch["films"]]})[0]
    sid = pitch["films"][0]
    steps = [
        ("commission", "commissioned", {"verdicts": [
            {"film": s, "verdict": "commission", "reason": "good", "notes": ["keep the hook"],
             "scores": {"curiosity": 8, "demand": 7, "material": 7, "pictures": 8}} for s in pitch["films"]]}),
        ("proof", "proofed", {"outline": OUTLINE, "scenes": [_scene(1, 30), _scene(1, 30, "A steaming kettle")]}),
        ("proof_audience", "proof_screened", {"summary": "Two would watch.", "viewers": VIEWERS}),
        ("proof_review", "drafting", {"verdict": "go", "reason": "it hooks", "notes": [],
                                      "scores": {"opening": 8, "momentum": 7, "clarity": 8, "material": 7}}),
        ("draft", "drafted", {"scenes": [_scene(1, 30), _scene(1, 30, "A steaming kettle"),
                                         _scene(2, 45, "A pan of water"), _scene(2, 45, "A frosted window")],
                              "description": "Why it happens."}),
        ("edit", "edited", {"verdict": "pass", "reason": "tight", "edits": [{"scene": 0, "narration": "New line.",
                                                                             "why": "sharper"}],
                            "chapters": [{"chapter": n, "momentum": 7, "specificity": 7, "voice": 7, "clarity": 8}
                                         for n in (1, 2)]}),
        ("facts", "checked", {"verdict": "ok", "facts": {"fixes": []}, "cards": {"fixes": []},
                              "checked": ["the boiling point, from a physics text"]}),
        ("pictures", "pictured", {"subjects": [{"scene": i, "subject": f"thing {i}"} for i in range(4)],
                                  "changes": []}),
        ("packaging", "packaged", {"title": "Why Does Thing 0 Happen Every Day", "description": "A film about it.",
                                   "thumbnail": {"subject": "a kettle", "words": "EVERY DAY"}, "why": "clear"}),
        ("audience", "screened", {"summary": "Two would watch.", "viewers": VIEWERS}),
    ]
    for role, reached, data in steps:
        row = _issue(channel, role)
        ok, problems, _ = _hand_in(channel, row["id"], data)
        assert ok, (role, problems)
        assert newsroom.state_of(production.load("why", sid)) == reached
        if reached == state:
            break
    return sid


def test_a_pitch_without_evidence_or_enough_beats_isnt_taken(world):
    row = _issue(world, "pitch")
    assert row["films"] == ["t0001", "t0002", "t0003"] and row["agent"] == "newsroom-scout"
    thin = [{**_pitch(s, f"Why Does Thing {s[-1]} Happen"), "demand": [], "beats": []} for s in row["films"]]
    ok, problems, _ = _hand_in(world, row["id"], {"pitches": thin})
    assert not ok and any("demand" in p for p in problems) and any("beats" in p for p in problems)
    full = [_pitch(s, f"Why Does Thing {s[-1]} Happen") for s in row["films"]]
    assert _hand_in(world, row["id"], {"pitches": full})[0]
    assert newsroom.state_of(production.load("why", "t0001")) == "pitched"


def test_a_low_score_isnt_commissioned_a_rework_is_once_and_a_scrap_leaves_the_plan(world):
    pitch = _issue(world, "pitch")
    _hand_in(world, pitch["id"], {"pitches": [_pitch(s, f"Why Does Thing {s[-1]} Happen") for s in pitch["films"]]})
    row = _issue(world, "commission")
    good = {"curiosity": 8, "demand": 7, "material": 7, "pictures": 8}
    low = [{"film": s, "verdict": "commission", "reason": "ok", "scores": {**good, "material": 4}}
           for s in row["films"]]
    ok, problems, _ = _hand_in(world, row["id"], {"verdicts": low})
    assert not ok and "can't be commissioned" in problems[0]
    verdicts = [{"film": "t0001", "verdict": "scrap", "reason": "the answer is dull", "scores": good},
                {"film": "t0002", "verdict": "rework", "reason": "a better angle", "notes": ["lead with the myth"],
                 "scores": good},
                {"film": "t0003", "verdict": "scrap", "reason": "done to death", "scores": good}]
    assert _hand_in(world, row["id"], {"verdicts": verdicts})[0]
    assert curriculum.find("why", "t0001")["status"] == curriculum.SKIPPED
    assert newsroom.state_of(production.load("why", "t0002")) == "rework_pitch"
    assert newsroom.newsroom_of(production.load("why", "t0002"))["notes"] == ["lead with the myth"]
    # The rework comes back to the scout first, then to the editor, who can't rework it again.
    again = _issue(world, "pitch")
    assert again["films"][0] == "t0002"
    _hand_in(world, again["id"], {"pitches": [_pitch(s, f"Why Does Thing {s[-1]} Happen") for s in again["films"]]})
    row = _issue(world, "commission")
    once_more = [{"film": s, "verdict": "rework", "reason": "still", "notes": ["x"], "scores": good}
                 for s in row["films"]]
    ok, problems, _ = _hand_in(world, row["id"], {"verdicts": once_more})
    assert not ok and any("had its rework" in p for p in problems)


def test_a_proof_must_fill_its_first_chapter_and_a_low_score_cant_go_on(world):
    sid = _to(world, "commissioned")
    row = _issue(world, "proof")
    ok, problems, _ = _hand_in(world, row["id"], {"outline": OUTLINE, "scenes": [_scene(1, 10)]})
    assert not ok and "chapter 1 is 10 words" in problems[0]
    assert _hand_in(world, row["id"], {"outline": OUTLINE, "scenes": [_scene(1, 30), _scene(1, 30, "A kettle")]})[0]
    first = _issue(world, "proof_audience")
    assert _hand_in(world, first["id"], {"summary": "Two would watch.", "viewers": VIEWERS})[0]
    review = _issue(world, "proof_review")
    ok, problems, _ = _hand_in(world, review["id"], {"verdict": "go", "reason": "fine", "scores": {
        "opening": 4, "momentum": 7, "clarity": 8, "material": 7}})
    assert not ok and "can't go on" in problems[0]
    assert _hand_in(world, review["id"], {"verdict": "rework", "reason": "the opening restates the title",
                                          "notes": ["open on the kettle"], "scores": {
                                              "opening": 4, "momentum": 7, "clarity": 8, "material": 7}})[0]
    assert newsroom.state_of(production.load("why", sid)) == "rework_proof"
    assert _issue(world, "proof")["films"] == [sid]          # back to the writer, with the notes
    assert "open on the kettle" in newsroom.brief("why", newsroom.load_ledger("why")["open"].popitem()[0])


def test_the_proofs_first_viewers_are_heard_before_the_script_is_written(world):
    # Three of nine final reads sent a finished script back over its first
    # minutes; the same viewers now see the proof, before the draft is paid
    # for in time and tokens.
    sid = _to(world, "proofed")
    row = _issue(world, "proof_audience")
    assert row["agent"] == "newsroom-test-audience"
    brief = newsroom.brief("why", row["id"])
    assert 'title "Why Does Thing 1 Happen"' in brief and "A steaming kettle" in brief
    viewers = [{"who": w, "clicks": True, "click_why": "y", "leaves_at": 1, "leave_why": "it repeats"} for w in "abc"]
    assert _hand_in(world, row["id"], {"viewers": viewers, "summary": "All leave early."})[0]
    review = _issue(world, "proof_review")
    assert review["films"] == [sid]
    assert "THE FIRST VIEWERS" in newsroom.brief("why", review["id"])
    assert "leaves at scene 1" in newsroom.brief("why", review["id"])


def test_a_short_chapter_goes_back_and_an_editor_edits_lines(world):
    sid = _to(world, "drafting")
    row = _issue(world, "draft")
    ok, problems, _ = _hand_in(world, row["id"], {"scenes": [_scene(1, 60), _scene(2, 20)], "description": "d"})
    assert not ok and "chapter 2 is 20 words" in problems[0]
    _hand_in(world, row["id"], {"scenes": [_scene(1, 60), _scene(2, 45), _scene(2, 45, "A pan")],
                                "description": "d"})
    edit = _issue(world, "edit")
    low = [{"chapter": n, "momentum": 5, "specificity": 7, "voice": 7, "clarity": 8} for n in (1, 2)]
    ok, problems, _ = _hand_in(world, edit["id"], {"verdict": "pass", "reason": "ok", "chapters": low, "edits": []})
    assert not ok and "score under 6" in problems[0]
    good = [{**c, "momentum": 8} for c in low]
    assert _hand_in(world, edit["id"], {"verdict": "pass", "reason": "tight", "chapters": good,
                                        "edits": [{"scene": 1, "narration": "A sharper line.", "why": "punch"}]})[0]
    nr = newsroom.newsroom_of(production.load("why", sid))
    assert nr["draft"]["scenes"][1]["narration"] == "A sharper line." and nr["state"] == "edited"


def test_a_passed_film_is_approved_by_the_newsroom_and_drawn_by_the_autopilot(world, monkeypatch):
    sid = _to(world, "screened")
    final = _issue(world, "final")
    assert _hand_in(world, final["id"], {"verdict": "pass", "summary": "A good film about a kettle."})[0]
    data = production.load("why", sid)
    assert all(production.state(data, s) == "approved" for s in ("pitch", "outline", "script"))
    assert production.packaging(data)["title"] == "Why Does Thing 0 Happen Every Day"
    assert data["script"]["pictures"]["planned"] and data["script"]["scenes"][0]["narration"] == "New line."
    assert any(h.get("by") == "newsroom" for h in data["history"])
    started = []
    monkeypatch.setattr(auto_films, "start", lambda channel, row, stage: started.append(stage) or "j")
    world.publishing.enabled = True
    auto_films._act(world, curriculum.find("why", sid), data, after_hours=False)
    assert started == ["stills"]
    fresh = production.load("why", "t0004", "Why Does Thing 3 Happen?")
    assert auto_films._act(world, curriculum.find("why", "t0004"), fresh, after_hours=False) == ""
    assert started == ["stills"]                              # the newsroom writes it, not the API


def test_work_is_handed_out_within_a_sessions_and_a_weeks_points(world, monkeypatch):
    row, _ = newsroom.next_assignment(world, now=1_000_000.0)
    assert row["role"] == "pitch"
    monkeypatch.setattr(newsroom, "SESSION_POINTS", 1)
    again, why = newsroom.next_assignment(world, now=1_000_000.0 + 60)
    assert again is None and "session" in why
    # Never handed in: given up after a while, and due again in the next session.
    later, _ = newsroom.next_assignment(world, now=1_000_000.0 + 5 * HOUR)
    assert later["role"] == "pitch" and later["films"] == row["films"]
    monkeypatch.setattr(newsroom, "SESSION_POINTS", 50)
    monkeypatch.setattr(newsroom, "WEEK_POINTS", 2)
    newsroom.next_assignment(world, now=1_000_000.0 + 10 * HOUR)
    last, why = newsroom.next_assignment(world, now=1_000_000.0 + 10 * HOUR + 60)
    assert last is None and "week" in why


def test_the_film_nearest_done_goes_first(world, monkeypatch):
    monkeypatch.setattr(newsroom, "FILMS_WRITING", 2)
    _to(world, "drafted")
    due = newsroom.due(world)
    # The draft's edit first; then one more film's proof (two in writing at
    # once, not three); then a pitch to keep three films waiting.
    assert [(a["role"], a["films"]) for a in due] == [("edit", ["t0001"]), ("proof", ["t0002"]),
                                                       ("pitch", ["t0004"])]


def test_the_newsrooms_files_are_under_the_channels_folder(world):
    assert newsroom._ledger_path("why").parent.name == "why"
    assert newsroom.work_dir("why").parent.name == "why"
    assert newsroom._ledger_path("why").parent == newsroom.CHANNELS_DIR / "why"


def test_a_newsroom_channels_angles_arent_pitched_ahead_by_the_api(world, monkeypatch):
    called = []
    monkeypatch.setattr(storyboard, "outline_ahead", lambda c: called.append(c.key) or 0)
    monkeypatch.setattr(storyboard, "_last_auto", 0)
    world.publishing.enabled = True
    world.content_mode = "topic"
    storyboard.keep_up({"why": world})
    assert called == []


def test_what_each_role_used_of_the_subscription_is_recorded(world):
    row = _issue(world, "pitch")
    _hand_in(world, row["id"], {"pitches": [_pitch(s, f"Why Does Thing {s[-1]} Happen") for s in row["films"]]})
    assert newsroom.spent("why", row["id"], 117542)
    assert newsroom.tokens_used(newsroom.load_ledger("why"), 24) == 117542
    assert not newsroom.spent("why", "no-such-assignment", 5)


def test_a_newsroom_film_goes_out_before_films_made_the_old_way(world, tmp_path, monkeypatch):
    # The owner, 21 Oct: "put newsroom films first".
    from core import publish_queue
    out = tmp_path / "out"
    old, new = out / "longform" / "old.mp4", out / "longform" / "new.mp4"
    monkeypatch.setattr(publish_queue.gallery, "resolve_output_dir", lambda d: out)
    monkeypatch.setattr(publish_queue.gallery, "videos_in", lambda d, long=False: [old, new])
    monkeypatch.setattr(publish_queue.gallery, "load_publish_info", lambda p: {"queued_at": p.stem == "new" and "2" or "1"})
    monkeypatch.setattr(publish_queue.gallery, "is_queued", lambda info: True)
    out.mkdir()
    production.update("why", "t0001", lambda d: d.update(script={"by": "newsroom"}, video={"path": "longform/new.mp4"}),
                      "Why Does Thing 0 Happen?")
    assert publish_queue.queued(world, long=True) == [new, old]
    world.documentary.newsroom = False                     # any other channel: approval order
    assert publish_queue.queued(world, long=True) == [old, new]


def test_the_analyst_reads_a_weeks_films_and_its_findings_reach_each_role(world, monkeypatch):
    # The owner, 21 Oct: "is there a retrospective agent that looks at
    # previous videos, click-through and retention ... and feeds this back".
    import time as clock
    out = [(production.load("why", "t0005", "x"), type("P", (), {"stem": "film_a"})(), {}, {}, 9.0)]
    monkeypatch.setattr(newsroom, "_published", lambda channel, now=None: out)
    monkeypatch.setattr(newsroom, "_brief_analysis", lambda channel, row: "the figures")
    assert newsroom.analysis_due(world)
    row = _issue(world, "analysis")
    assert row["agent"] == "newsroom-analyst"
    ok, problems, _ = _hand_in(world, row["id"], {"findings": {"writer": [{"text": "Open on the number."}]}})
    assert not ok and "evidence" in problems[0]
    assert _hand_in(world, row["id"], {"summary": "Openings matter.", "findings": {
        "writer": [{"text": "Open on the number.", "evidence": "film_a lost 48% by 0:15", "confidence": "hunch"}],
        "packaging": [{"text": "Name the thing.", "evidence": "film_a 2.6%", "confidence": "suggestive"}]}})[0]
    assert not newsroom.analysis_due(world)                  # read; not again until a new film's week is up
    assert "Open on the number." in newsroom.findings_text("why", "draft")
    assert "Name the thing." in newsroom.findings_text("why", "packaging")
    assert newsroom.findings_text("why", "facts") == ""
    assert newsroom._findings_path("why").parent == newsroom.CHANNELS_DIR / "why"
    out.append((production.load("why", "t0006", "y"), type("P", (), {"stem": "film_b"})(), {}, {}, 8.0))
    assert not newsroom.analysis_due(world)                  # a new film, but the last read is under a week old
    assert newsroom.analysis_due(world, now=clock.time() + 7 * 86400)


def test_no_new_film_is_started_once_enough_are_in_hand(world, monkeypatch):
    # The owner, 22 Oct: usage "should slow down naturally" once films are waiting.
    _to(world, "drafted")
    monkeypatch.setattr(newsroom, "BANK_FILMS", 1)
    assert [a["role"] for a in newsroom.due(world)] == ["edit"]   # no proof, no pitch


def test_an_opening_or_title_that_echoes_the_other_is_refused(world):
    # 22 Oct: every first proof went back for an opening that restated the
    # title, and a two-part "X: Y" title got through.
    assert newsroom.echoes("We have a map of Mars. We have never mapped our own ocean floor.",
                           "Why We Know Mars Better Than Our Own Ocean Floor")
    assert not newsroom.echoes("Put the Sun a football pitch away, and climbing Everest brings you closer.",
                               "Your Freezer Is Warmer Than the Top of Everest")
    row = _issue(world, "pitch")
    echoing = [{**_pitch(s, f"Why Does Thing {s[-1]} Happen"), "angle": {
        **_pitch(s, "x")["angle"], "title": f"Why Does Thing {s[-1]} Happen", "hook": "Thing happens. Why?"}}
        for s in row["films"]]
    ok, problems, _ = _hand_in(world, row["id"], {"pitches": echoing})
    assert not ok and any("restates the title" in p for p in problems)
    colon = [{**_pitch(s, f"Thing {s[-1]}: The Truth"), "angle": {**_pitch(s, "x")["angle"],
                                                              "title": f"Thing {s[-1]}: The Truth"}}
             for s in row["films"]]
    ok, problems, _ = _hand_in(world, row["id"], {"pitches": colon})
    assert not ok and any("X: Y" in p for p in problems)



def test_a_films_step_rejected_twice_is_held_until_the_owner_releases_it(world):
    sid = _to(world, "drafting")
    for _ in range(2):
        row, _ = newsroom.next_assignment(world)
        assert row["role"] == "draft"
        for _ in range(newsroom.SUBMITS):
            ok, problems, _ = _hand_in(world, row["id"], {"scenes": [_scene(1, 5)], "description": "d"})
        assert not ok
    assert sid in newsroom.held(world)
    assert all(a["films"] != [sid] for a in newsroom.due(world))   # not handed out again
    newsroom.release("why", sid)
    assert sid not in newsroom.held(world) and newsroom.due(world)[0]["films"] == [sid]


def test_a_session_runs_up_to_three_assignments_at_once_each_a_different_film(world):
    sid = _to(world, "drafted")
    first, _ = newsroom.next_assignment(world)
    second, _ = newsroom.next_assignment(world)
    assert first["films"] != second["films"] and sid in first["films"] + second["films"]
    newsroom.next_assignment(world)
    fourth, why = newsroom.next_assignment(world)
    assert fourth is None and "already out" in why


def test_a_review_of_a_drawn_film_doesnt_write_its_production(world, monkeypatch):
    # The app writes a film's production once it's past the newsroom; a
    # second writer could undo either's change.
    monkeypatch.setattr(overseer, "status", lambda: [{"channel": "why", "id": "t0005", "waiting": ["stills"]}])
    before = production.load("why", "t0005", "x")
    row = _issue(world, "frames")
    assert _hand_in(world, row["id"], {"summary": "Redrew 2."})[0]
    assert production.load("why", "t0005", "x") == before
    assert newsroom.load_ledger("why")["done"][-1]["verdict"] == "Redrew 2."


def test_the_scout_hears_what_the_editors_said_about_earlier_pitches(world):
    pitch = _issue(world, "pitch")
    _hand_in(world, pitch["id"], {"pitches": [_pitch(s, f"Why Does Thing {s[-1]} Happen") for s in pitch["films"]]})
    row = _issue(world, "commission")
    good = {"curiosity": 8, "demand": 7, "material": 7, "pictures": 8}
    _hand_in(world, row["id"], {"verdicts": [
        {"film": s, "verdict": "scrap", "reason": "everyone knows this already", "scores": good} for s in row["films"]]})
    assert "everyone knows this already" in newsroom._pitch_verdicts(world)


def test_a_search_made_this_week_is_answered_from_the_cache(world, monkeypatch):
    with newsroom.locked("why"):
        ledger = newsroom.load_ledger("why")
        ledger["demand"].append({"at": newsroom._now(), "query": "why is the sky blue", "result": "CACHED"})
        newsroom.save_ledger("why", ledger)
    monkeypatch.setattr("core.youtube.access_token", lambda key: (_ for _ in ()).throw(AssertionError("searched")))
    assert newsroom.demand("why", "Why is the  sky blue").startswith("CACHED")


def test_the_ledger_is_one_writer_at_a_time(world):
    with newsroom.locked("why"):
        with pytest.raises(newsroom.PipelineError):
            newsroom._Locked("why", wait=0.3).__enter__()
    with newsroom.locked("why"):
        pass                                                  # free again afterwards


def test_the_test_audience_is_three_viewers_and_the_final_read_hears_them(world):
    sid = _to(world, "packaged")
    row = _issue(world, "audience")
    ok, problems, _ = _hand_in(world, row["id"], {"viewers": [{"who": "x", "clicks": True, "leaves_at": -1}]})
    assert not ok and "three" in problems[0]
    viewers = [{"who": w, "clicks": True, "click_why": "y", "leaves_at": 1, "leave_why": "slow"} for w in "abc"]
    assert _hand_in(world, row["id"], {"viewers": viewers, "summary": "All leave early."})[1] == []
    final = _issue(world, "final")
    assert "leaves at scene 1" in newsroom.brief("why", final["id"])


def test_the_board_shows_each_films_steps_and_what_the_next_run_should_do(world, monkeypatch):
    # The owner, 22 Oct: "a flowchart style display that shows the process
    # and where it is up to, and also showing what is expected to be
    # completed next time it runs".
    monkeypatch.setattr("core.voice_quota.summary", lambda keys: None)
    sid = _to(world, "drafted")
    b = newsroom.board(world)
    film = next(f for f in b["films"] if f["id"] == sid)
    by = {s["key"]: s for s in film["steps"]}
    assert by["draft"]["status"] == "done" and by["edit"]["status"] == "current"
    assert by["proof"]["status"] == "done" and by["storyboard"]["status"] == "todo"
    assert by["edit"]["next"] and by["final"]["next"]                # the whole film fits in the next run
    assert film["group"] == "writing"
    assert b["expected"]["films"][sid][0] == "edit"
    assert newsroom.next_run().hour in newsroom.RUN_HOURS


def test_the_newsroom_board_draws(world, monkeypatch):
    from web import create_app
    monkeypatch.setattr("core.voice_quota.summary", lambda keys: None)
    monkeypatch.setattr("web.blueprints.newsroom.channel_or_404", lambda key: world)
    _to(world, "edited")
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        page = client.get("/channels/why/newsroom?partial=1").get_data(as_text=True)
    assert 'class="nr-step s-done' in page and "s-current" in page and "Next run" in page


def test_a_drawn_storyboard_is_read_frame_by_frame_then_as_one_film(world, monkeypatch):
    # The owner, 25 Oct: "an agent that checks the storyboard as a whole ...
    # as well as an agent that checks individual pictures to make sure they
    # fit with the script at that point".
    monkeypatch.setattr(overseer, "status", lambda: [{"channel": "why", "id": "t0005", "waiting": ["stills"]}])
    row = _issue(world, "frames")
    assert row["agent"] == "newsroom-frame-checker"
    assert _hand_in(world, row["id"], {"summary": "Redrew 3: a blank face."})[0]
    with newsroom.locked("why"):
        ledger = newsroom.load_ledger("why")
    assert newsroom.frames_checked(ledger, "why", "t0005")
    nxt, _ = newsroom.next_assignment(world)
    assert nxt["role"] == "continuity" and nxt["agent"] == "newsroom-continuity-editor"


def test_frame_sheets_show_six_pictures_with_their_lines(world, tmp_path):
    from PIL import Image
    folder = production.folder("why", "t0005")
    (folder / "stills").mkdir(parents=True, exist_ok=True)
    scenes = []
    for i in range(8):
        Image.new("RGB", (64, 36), (i * 20, 40, 40)).save(folder / "stills" / f"kf_{i:02d}.jpg")
        scenes.append(_scene(1, 5, f"Picture {i}"))
    production.update("why", "t0005", lambda d: d.update(
        stills={str(i): f"stills/kf_{i:02d}.jpg" for i in range(8)}, script={"scenes": scenes}), "x")
    sheets = newsroom.frame_sheets("why", "t0005")
    assert [n for _, n in sheets] == [[0, 1, 2, 3, 4, 5], [6, 7]] and all(p.exists() for p, _ in sheets)
    text = newsroom.frames_text("why", "t0005")
    assert "[7] SAYS:" in text and "Picture 7" in text and text.count("SHEET") == 2
