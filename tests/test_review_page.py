"""
The review page (web/blueprints/review.py).

Regression (decision 077): the page sent the browser the 40 oldest videos,
approved or not. With spare voice making dozens ahead and approving them
into the queue, all 40 were approved; the page's default filter shows only
videos waiting for a decision, so it said "All caught up" while the
header counted 32 waiting.
"""

from __future__ import annotations

import html
import json


def test_videos_waiting_for_a_decision_are_sent_before_approved_ones(monkeypatch):
    from web import create_app
    from web.blueprints import review

    def item(n, queued):
        return {"relpath": f"c/2026-10-0{1 if queued else 7}/v{n}.mp4", "name": f"v{n}", "queued": queued,
                "channel_key": "c", "channel_name": "Chan", "mtime": n, "title": f"v{n}",
                "links": {}, "checks": {}}
    approved_old = [item(n, True) for n in range(45)]
    waiting_new = [item(100 + n, False) for n in range(3)]
    monkeypatch.setattr(review, "_queue", lambda: approved_old + waiting_new)

    app = create_app()
    app.config.update(TESTING=True)
    page = app.test_client().get("/review").get_data(as_text=True)
    sent = json.loads(html.unescape(page.split('data-items="')[1].split('"')[0]))
    assert [i["name"] for i in sent if not i["queued"]] == ["v100", "v101", "v102"]
    assert "3 videos waiting" in page and "All caught up" not in page
