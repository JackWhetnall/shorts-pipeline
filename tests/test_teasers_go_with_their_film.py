"""
A film's teasers go out close to it (decision 107): in the first shorts
slots after the film's own, or straight away once it's out, and never
before it's queued. Other shorts keep their order in the slots left.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import gallery, publish_queue


def at(day, hour):
    return datetime(2026, 10, day, hour, 30, tzinfo=timezone.utc)


SLOTS = [at(d, 18) for d in range(19, 31)]                  # a shorts slot every evening


def test_teasers_follow_their_film_and_wait_for_it(monkeypatch, tmp_path):
    film, unqueued = tmp_path / "film.mp4", tmp_path / "later.mp4"
    t1, t2, quiz, t3 = (tmp_path / f"{n}.mp4" for n in ("t1", "t2", "quiz", "t3"))
    films = {t1: film, t2: film, t3: unqueued}
    monkeypatch.setattr(gallery, "load_publish_info", lambda p: {"youtube_url": "", "published_at": None})
    monkeypatch.setattr(gallery, "is_out", lambda info: False)
    film_when = {str(film.resolve()): at(23, 16)}            # the film goes out on the 23rd
    out = publish_queue._shorts_with_teasers([t1, t2, quiz, t3], lambda n: SLOTS[:n], films, film_when, at(19, 9))
    when = dict(out)
    assert when[quiz] == at(19, 18)                          # the other short isn't held back
    assert when[t1] == at(23, 18) and when[t2] == at(24, 18)  # the evening of the film, and the next
    assert isinstance(when[t3], publish_queue.AfterFilm)     # its film isn't queued: it waits
    assert publish_queue.slot_text(when[t3]) == "After its film"


def test_a_teaser_whose_film_is_out_goes_first(monkeypatch, tmp_path):
    film, quiz, t1 = tmp_path / "film.mp4", tmp_path / "quiz.mp4", tmp_path / "t1.mp4"
    monkeypatch.setattr(gallery, "load_publish_info", lambda p: {"published_at": "x"})
    monkeypatch.setattr(gallery, "is_out", lambda info: True)
    out = publish_queue._shorts_with_teasers([quiz, t1], lambda n: SLOTS[:n], {t1: film}, {}, at(19, 9))
    assert out[0] == (t1, at(19, 18)) and out[1] == (quiz, at(20, 18))


def test_a_channel_without_teasers_is_scheduled_as_before(monkeypatch, tmp_path):
    monkeypatch.setattr(publish_queue, "film_of_teaser", lambda channel, v: None)
    assert publish_queue.film_of_teaser(None, tmp_path / "a.mp4") is None
