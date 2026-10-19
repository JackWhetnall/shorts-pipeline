"""
Where the voice allowance goes (core.voice_budget, decision 120). The
owner: it was "really difficult to tell how much a channel uses, what the
average voice per video is", whether teasers count, how a schedule change
affects the total, and "which videos are pre made and which will actually
spend the remaining elevenlabs budget".

- this month starts a month before the next reset;
- a film and its teasers are one block; a short is matched to its video
  by its voice cost, so it has a title and a state;
- what's still to come is the slots before the reset plus the buffer,
  less what's made ahead;
- a suggestion only claims what it really saves, made-ahead videos
  allowed for, and is applied as a settings change, nothing else.
"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from core import gallery, voice_budget as vb
from core.channels import ChannelConfig


def test_this_month_starts_a_month_before_the_reset():
    resets = datetime(2026, 11, 7, 17, 28).timestamp()
    assert datetime.fromtimestamp(vb._cycle_start(resets)) == datetime(2026, 10, 7, 17, 28)
    assert datetime.fromtimestamp(vb._cycle_start(datetime(2026, 3, 31, 9).timestamp())) == datetime(2026, 2, 28, 9)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("core.gallery.OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr("core.gallery._sync_curriculum", lambda *a: None)
    monkeypatch.setattr(vb, "_seeds", {"j-film": {"stage": "video"}, "j-teasers": {"stage": "teasers"}})
    short = ChannelConfig(key="mp", channel_display_name="Minute Pastor", output_dir=str(tmp_path / "out" / "mp"))
    video = tmp_path / "out" / "mp" / "2026-10-12" / "john_3_16.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"v")
    video.with_name("john_3_16_cost.json").write_text(json.dumps({"by_operation": {"elevenlabs:voiceover": 0.0825}}))
    gallery.save_title_and_description(video, "For God So Loved", "")
    return short, video


def _record(ts, chars, usd=0.0, **fields):
    return {"ts": ts, "service": "elevenlabs", "operation": "voiceover", "characters": chars, "cost_usd": usd,
            **fields}


def test_a_film_and_its_teasers_are_one_block_and_a_short_has_its_title(world, monkeypatch):
    short, video = world
    monkeypatch.setattr("core.curriculum.find", lambda key, sid: {"title": "Why Do We Get Hiccups?"})
    monkeypatch.setattr(vb, "_film_video", lambda channel, sid: (None, {}))
    film = ChannelConfig(key="why", channel_display_name="Why, Though?", format="documentary")
    records = [_record(100, 7000, channel_key="why", production="t0004", job_id="j-film"),
               _record(200, 1500, channel_key="why", production="t0004", job_id="j-teasers"),
               _record(150, 300, 0.05, channel_key="mp", job_id="j-short"),
               _record(160, 200, 0.0325, channel_key="mp", job_id="j-short"),
               _record(10, 999, channel_key="mp", job_id="old")]                 # before this month
    blocks = vb.spent({"why": film, "mp": short}, records, since=50, ratio=0.2)
    by_label = {b["label"]: b for b in blocks}
    assert by_label["Why Do We Get Hiccups?"]["credits"] == 1700 and by_label["Why Do We Get Hiccups?"]["teasers"] == 300
    assert by_label["For God So Loved"]["credits"] == 100 and by_label["For God So Loved"]["state"] == "in review"
    assert len(blocks) == 2


def test_what_is_still_to_come_allows_for_videos_made_ahead(world, monkeypatch):
    short, _ = world
    monkeypatch.setattr(vb, "_slots", lambda plan, now, until, long=False: [1.0, 2.0, 3.0, 4.0])
    monkeypatch.setattr(vb, "_made_ahead", lambda channel, long: 3)
    short.publishing.buffer = 3
    blocks, made, ready = vb._shorts_to_come(short, {"short": 500, "long": 500}, 0.2, 0, 10)
    assert len(blocks) == 4 and made == 3 and all(b["credits"] == 100 for b in blocks)   # 4 slots + 3 kept - 3 made
    monkeypatch.setattr(vb, "_made_ahead", lambda channel, long: 30)
    assert vb._shorts_to_come(short, {"short": 500, "long": 500}, 0.2, 0, 10)[0] == []


def test_a_suggestion_only_claims_what_it_saves(world, monkeypatch):
    short, _ = world
    short.publishing.slots = ["11:00", "21:00"]
    monkeypatch.setattr(vb, "_views_per_video", lambda channel: 10)
    monkeypatch.setattr(vb, "_slots", lambda plan, now, until, long=False: [0] * (8 if len(plan.slots) > 1 else 4))
    facts = {"mp": {"typical": {"short": 100}, "made_ahead": 2, "short_ready": 2}}
    found = vb.suggestions({"mp": short}, [], facts, gap=500, now=0, until=1)
    one_a_day = next(s for s in found if s["apply"] == {"slots": ["11:00"]})
    assert one_a_day["saves"] == 400 and one_a_day["views"] == 40 and one_a_day["pick"]
    facts["mp"]["short_ready"] = 50                                   # made far ahead: nothing to save
    assert vb.suggestions({"mp": short}, [], facts, gap=500, now=0, until=1) == []


def test_a_suggestion_is_applied_as_a_settings_change_only(monkeypatch):
    saved = []
    channel = ChannelConfig(key="mp", channel_display_name="Minute Pastor")
    monkeypatch.setattr("core.channels.load_channels", lambda validate=False: {"mp": channel})
    monkeypatch.setattr("core.channels.save_channel", lambda c: saved.append(c))
    vb.apply("mp", {"slots": ["11:00"]})
    assert channel.publishing.slots == ["11:00"] and saved
    from core.errors import PipelineError
    with pytest.raises(PipelineError):
        vb.apply("mp", {"style_prompt": "anything"})


def test_the_page_shows_the_bar_the_channels_and_the_suggestions(monkeypatch):
    from web import create_app
    block = {"channel": "mp", "kind": "short", "label": "For God So Loved", "credits": 100, "spent": True,
             "estimate": False, "state": "out", "when": 1, "when_label": "out Mon 12 Oct", "colour": "#3987e5",
             "name": "Minute Pastor", "order": 0}
    picture = {"used": 900, "limit": 1000, "remaining": 100, "need": 300, "gap": 200, "resets_label": "Sat 7 Nov",
               "days_left": 19, "spent": [block], "coming": [{**block, "spent": False, "estimate": True,
                                                              "state": "to make", "credits": 300}],
               "rows": [{"key": "mp", "name": "Minute Pastor", "colour": "#3987e5", "spent": 100, "wasted": 0,
                         "coming": 300, "videos_coming": 3, "typical": {"short": 100, "long": 100}, "made_ahead": 2}],
               "suggestions": [{"id": 0, "channel": "mp", "text": "Minute Pastor: one a day at 11:00, not 2 a day",
                                "saves": 200, "views": 30, "apply": {"slots": ["11:00"]}, "pick": True}],
               "upgrade": vb.UPGRADE}
    monkeypatch.setattr(vb, "picture", lambda: picture)
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        page = client.get("/money/voice").get_data(as_text=True)
    assert "Where it goes" in page and "short by" in page and "one a day at 11:00" in page
    assert page.count('class="vb-block ') == 2 and "Apply &middot; free" in page and "$22 a month" in page


def test_slots_keep_their_wall_clock_time_after_the_clocks_change():
    # Found on 19 Oct: slots after 25 Oct read 10:00, not 11:00.
    from core import publish_queue
    plan = SimpleNamespace(slots=["11:00"], weekdays=list(range(7)))
    found = publish_queue.upcoming_slots(plan, datetime(2026, 10, 23, 12).astimezone(), 5)
    assert [s.hour for s in found] == [11] * 5


def test_a_discarded_film_holds_no_place_in_the_bank(monkeypatch, tmp_path):
    # Found on 19 Oct: three films discarded while waiting for a look still
    # counted as banked, holding three of Why, Though?'s eight places.
    from core import auto_films, production
    films = [{"video": "ready", "path": tmp_path / "a.mp4"}, {"video": "ready", "path": tmp_path / "b.mp4"}]
    for f in films:
        f["path"].write_bytes(b"v")
    gallery.set_discarded(films[1]["path"], True)
    monkeypatch.setattr(production, "all_for", lambda key: films)
    monkeypatch.setattr(production, "state", lambda data, stage: data["video"] if stage == "video" else "approved")
    monkeypatch.setattr(production, "video_file", lambda channel, data: data["path"])
    assert auto_films._in_hand(SimpleNamespace(key="why")) == (0, 1)
