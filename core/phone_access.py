"""
Using the app from a phone on the same home network (decision 055).

Off by default, when the app listens only on this PC. Turned on, it
listens on the network too, and anything not from this PC must first give
the access code: a phone enters it once and stays signed in. A new code
signs every phone out. Wrong codes are limited per address, so the code
can't be guessed by trying them all.

It's still a home-network tool, not something to put on the internet: no
HTTPS, and the code is the only lock. Windows Firewall must also let the
phone in, which only the PC's owner can allow (TASKS.md).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import socket
import threading
import time

from core.logging_setup import get_logger
from core.paths import PHONE_ACCESS_PATH

log = get_logger(__name__)

PATH = PHONE_ACCESS_PATH
CODE_DIGITS = 6
MAX_TRIES = 8                  # wrong codes from one address...
TRY_WINDOW = 15 * 60           # ...in this many seconds, then it waits
LOCAL = {"127.0.0.1", "::1", "localhost"}

_tries: dict = {}
_lock = threading.Lock()


def settings() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"enabled": bool(data.get("enabled")), "code": str(data.get("code") or "")}


def _save(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")


def new_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))


def set_enabled(on: bool) -> dict:
    """Turn phone access on (making a code the first time) or off."""
    data = settings()
    data["enabled"] = bool(on)
    if on and not data["code"]:
        data["code"] = new_code()
    _save(data)
    return data


def change_code() -> str:
    data = settings()
    data["code"] = new_code()
    _save(data)
    return data["code"]


def host() -> str:
    """What the app listens on: this PC only, or the network as well."""
    return "0.0.0.0" if settings()["enabled"] else "127.0.0.1"


def is_local(address: str) -> bool:
    address = (address or "").removeprefix("::ffff:")
    return address in LOCAL


def token(code: str = None) -> str:
    """What a signed-in phone's session holds: changes with the code."""
    code = settings()["code"] if code is None else code
    return hashlib.sha256(f"phone:{code}".encode("utf-8")).hexdigest()[:24] if code else ""


def locked_out(address: str) -> bool:
    now = time.time()
    with _lock:
        recent = [t for t in _tries.get(address, []) if now - t < TRY_WINDOW]
        _tries[address] = recent
        return len(recent) >= MAX_TRIES


def check(address: str, typed: str) -> bool:
    """Whether `typed` is the code, counting a wrong one against `address`."""
    if locked_out(address):
        return False
    code = settings()["code"]
    ok = bool(code) and secrets.compare_digest(code, "".join((typed or "").split()))
    if not ok:
        with _lock:
            _tries.setdefault(address, []).append(time.time())
        log.warning(f"Wrong phone access code from {address}")
    return ok


def addresses() -> list:
    """This PC's addresses on the home network, most likely first."""
    found = []
    try:
        # No packet is sent: connecting a UDP socket only picks the route.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    private = [a for a in dict.fromkeys(found) if a.startswith(("192.168.", "10."))
               or (a.startswith("172.") and 16 <= int(a.split(".")[1]) <= 31)]
    return private
