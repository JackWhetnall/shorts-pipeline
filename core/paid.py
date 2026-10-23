"""
No money or voice credits spent outside the project's own programs
(decision 132).

The owner, 23 Oct: "real API usage and voice credits should never be
spent on testing, ever." The test suite couldn't spend (tests/conftest.py
blocks every live call), but 10,785 voice credits, a third of a month, went
on 11 to 13 October on voiceovers run by hand from one-off scripts while
the voice changes were being built. So a billable request is refused
unless the program making it is one of the project's own: the app, main.py,
the overseer and the newsroom, the tools/ scripts. A one-off script, code
piped in or run with `python -c`, gets an error instead of a bill.

Billable means a request that makes something:
- a Claude reply;
- an OpenAI picture or batch;
- an ElevenLabs voiceover or sound;
- a fal video.
Lookups stay free to make: the voice list, the credits left, a batch's
status. When the owner asks for a one-off paid run by hand, SHORTS_PAID_OK=1
allows it, for that run only.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from core.errors import PipelineError
from core.paths import PROJECT_ROOT

# host: the methods that bill there (any path), or {method: path fragments}.
BILLED = {
    "api.openai.com": {"POST": ("/images/", "/batches", "/files", "/chat", "/responses")},
    "api.elevenlabs.io": {"POST": ("/text-to-speech", "/sound-generation", "/text-to-voice", "/speech-to-speech")},
    "queue.fal.run": {"POST": ("",)},
    "fal.run": {"POST": ("",)},
}


class PaidCallRefused(PipelineError):
    """A billable request from a program that isn't the project's own."""


def _in_tests() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def sanctioned() -> bool:
    """Whether this process may spend: one of the project's own programs, or
    a run the owner allowed by hand. Tests have their own, stricter guard."""
    if os.environ.get("SHORTS_PAID_OK") == "1" or _in_tests():
        return True
    import __main__
    main = getattr(__main__, "__file__", None)
    if not main:
        return False                    # python -c, code piped in, a REPL
    try:
        Path(main).resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return False                    # a script from anywhere else
    return True


def billed(method: str, url: str) -> bool:
    parsed = urlparse(str(url))
    rules = BILLED.get(parsed.hostname or "")
    if not rules:
        return False
    return any(fragment in parsed.path for fragment in rules.get(method.upper(), ()))


def refuse(what: str) -> None:
    raise PaidCallRefused(
        f"paid call outside the project's programs: {what}",
        user_message=(f"Refused: {what} costs money, and only the app, main.py, the overseer, the newsroom "
                      f"and the tools/ scripts may spend (decision 132). Run it from one of those, or set "
                      f"SHORTS_PAID_OK=1 for a run the owner has asked for."))


def check(what: str) -> None:
    if not sanctioned():
        refuse(what)


_installed = False


def install() -> None:
    """Guard every request made with `requests`: a billable one from a
    program that isn't the project's own is refused before it's sent."""
    global _installed
    if _installed:
        return
    import requests
    real = requests.sessions.Session.request

    def guarded(self, method, url, *args, **kwargs):
        if billed(method, url):
            check(f"{method.upper()} {urlparse(str(url)).hostname}{urlparse(str(url)).path}")
        return real(self, method, url, *args, **kwargs)

    requests.sessions.Session.request = guarded
    _installed = True
