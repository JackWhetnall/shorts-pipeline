"""
The owner's list of 13 October (decision 095): teasers that seemed to be
missing, thumbnails, Insights ignoring the chosen channel, a wordy Money
page without top-up buttons, and a low prompt-cache hit rate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace as N

from core import costs, money, publish_queue, youtube
from pipeline import llm


# --- caching -----------------------------------------------------------------------------------

def test_a_repeated_message_prefix_is_cached_and_an_hour_in_batch_mode():
    llm._system_chars.set("s" * 3000)
    content = llm._content("Write chapter 2.", None, prefix="o" * 1500)
    assert content[0]["text"] == "o" * 1500 and content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[1] == {"type": "text", "text": "Write chapter 2."}
    with llm.batched():
        assert llm._content("x", None, prefix="o" * 4000)[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    llm._system_chars.set("")
    assert "cache_control" not in llm._content("x", None, prefix="short")[0]      # under the minimum: plain
    assert llm._content("just text") == "just text"


def test_an_hour_long_cache_write_is_billed_at_twice_the_input_rate():
    price = costs.CLAUDE_PRICES["claude-sonnet-5"]
    usage = N(input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=1_000_000,
              cache_creation=N(ephemeral_1h_input_tokens=1_000_000, ephemeral_5m_input_tokens=0))
    record = costs.record_claude("x", "claude-sonnet-5", usage)
    assert abs(record.cost_usd - 2 * price.input) < 1e-9


# --- thumbnails --------------------------------------------------------------------------------

def test_a_long_videos_thumbnail_is_sent_and_a_shorts_frame_is_not(tmp_path, monkeypatch):
    long_video = tmp_path / "longform" / "quiz_night_1.mp4"
    short = tmp_path / "proverbs_6_5.mp4"
    for v in (long_video, short):
        v.parent.mkdir(parents=True, exist_ok=True)
        v.write_bytes(b"x")
        v.with_name(f"{v.stem}_thumb.jpg").write_bytes(b"j")
    monkeypatch.setattr(publish_queue.gallery, "is_long", lambda v: "longform" in str(v))
    assert publish_queue.own_picture(long_video).name == "quiz_night_1_thumb.jpg"
    assert publish_queue.own_picture(short) is None                     # a frame for the app's lists, not a cover


def test_a_refused_thumbnail_says_to_verify_the_account_not_to_check_the_login():
    response = N(status_code=403, text=json.dumps({"error": {"errors": [{"reason": "forbidden"}]}}),
                 json=lambda: {"error": {"errors": [{"reason": "forbidden"}]}})
    error = youtube._api_error(response, "setting the thumbnail")
    assert "verify it by phone" in error.user_message
    assert "upload permission" in youtube._api_error(response, "uploading the video").user_message


# --- the Money page ------------------------------------------------------------------------------

def test_a_top_up_adds_to_what_is_left(monkeypatch):
    saved = {"balances": {"openai": {"usd": 7.5, "at": 0}}}
    monkeypatch.setattr(money, "settings", lambda: saved)
    monkeypatch.setattr(costs, "read_records", lambda: [{"service": "openai-image", "cost_usd": 2.5, "ts": 10}])
    stored = []
    monkeypatch.setattr(money, "set_balance", lambda provider, usd, now=None: stored.append((provider, usd)))
    assert money.top_up("openai", 20) == 25.0 and stored == [("openai", 25.0)]


def test_the_money_page_has_top_ups_and_says_the_2027_change_once():
    from web import create_app
    page = create_app().test_client().get("/money").get_data(as_text=True)
    assert page.count('name="add" value="20"') == 2
    assert page.count("doubles") == 0 and page.count("8,000 hours from") <= 1


# --- Insights and teasers --------------------------------------------------------------------------

def test_insights_follow_the_chosen_channel(monkeypatch):
    from web.blueprints import review
    asked = []
    monkeypatch.setattr(review.insights, "collect", lambda keys=None: asked.append(keys) or {})
    monkeypatch.setattr("web.focus.current", lambda channels: next(iter(channels)))
    from web import create_app
    create_app().test_client().get("/insights")
    assert asked and asked[-1] and len(asked[-1]) == 1


def test_teasers_say_they_wait_for_the_video():
    page = Path("web/templates/production.html").read_text(encoding="utf-8")
    assert "After the video's approved" in page
