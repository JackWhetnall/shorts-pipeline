"""
The Open Trivia Database (opentdb.com): about 5,300 community-verified
questions, free to use under CC BY-SA 4.0, which asks for a credit line:
any video using one of its questions says so in its description
(`CREDIT`).

Its API gives 50 questions a call and one call per 5 seconds per address,
so the whole verified set takes about ten minutes. A session token makes
it hand out each question once; when the token runs dry for a category,
that category is done. True/false questions are left out: a pub quiz
read aloud has no options. Categories no British pub quiz asks about
(video games, anime, comics, board games, gadgets, computers) are left
out too.
"""

from __future__ import annotations

import html
import time

import requests

from core.logging_setup import get_logger

log = get_logger(__name__)

API = "https://opentdb.com/api.php"
TOKEN_API = "https://opentdb.com/api_token.php"
CATEGORIES_API = "https://opentdb.com/api_category.php"
PER_CALL = 50
WAIT = 5.5                     # seconds between calls: the API's own limit is one per five
CREDIT = "Some questions are adapted from the Open Trivia Database (opentdb.com), CC BY-SA 4.0."
SOURCE = "opentdb"
LEFT_OUT = ("video games", "japanese anime", "comics", "board games", "gadgets", "computers",
            "cartoon")


def _get(url: str, params: dict) -> dict:
    for attempt in range(4):
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if data.get("response_code") == 5:            # too many requests: wait and go again
            time.sleep(WAIT * (attempt + 2))
            continue
        return data
    return data


def categories() -> list:
    """[(id, name)] of the categories worth asking in a pub quiz."""
    found = requests.get(CATEGORIES_API, timeout=30).json().get("trivia_categories") or []
    return [(c["id"], c["name"]) for c in found
            if not any(word in c["name"].lower() for word in LEFT_OUT)]


def fetch(say=None, sleep=time.sleep) -> list:
    """Every multiple-choice question in the kept categories, as raw intake
    items: {"question", "answer", "wrong", "difficulty", "category"}."""
    token = requests.get(TOKEN_API, params={"command": "request"}, timeout=30).json().get("token", "")
    out = []
    for cat_id, name in categories():
        got = 0
        while True:
            sleep(WAIT)
            data = _get(API, {"amount": PER_CALL, "category": cat_id, "type": "multiple", "token": token})
            code = data.get("response_code")
            results = data.get("results") or []
            if code in (1, 4):
                # Fewer than a full call's worth left: the API says the token
                # is spent (4) rather than "not enough" (1), so either way the
                # rest is taken at smaller sizes.
                results = _rest(cat_id, token, sleep)
                out += [_item(r) for r in results]
                got += len(results)
                break
            if code != 0:
                log.warning(f"  [opentdb] {name}: response {code}; moving on")
                break
            out += [_item(r) for r in results]
            got += len(results)
        if say:
            say(f"Open Trivia DB: {name}: {got} questions")
    return out


def _rest(cat_id: int, token: str, sleep) -> list:
    """The last few in a category, fewer than a full call's worth."""
    out = []
    for amount in (25, 10, 5, 1):
        while True:
            sleep(WAIT)
            data = _get(API, {"amount": amount, "category": cat_id, "type": "multiple", "token": token})
            if data.get("response_code") != 0:
                break
            out += data.get("results") or []
    return out


def _item(r: dict) -> dict:
    return {"question": html.unescape(r.get("question", "")),
            "answer": html.unescape(r.get("correct_answer", "")),
            "wrong": [html.unescape(w) for w in r.get("incorrect_answers") or []],
            "difficulty": r.get("difficulty", ""),
            "category": html.unescape(r.get("category", ""))}
