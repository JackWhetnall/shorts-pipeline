"""
Which channel this browser is looking at (decision 080).

The owner keeps a browser profile per channel, each signed in to that
channel's social accounts, and wanted each profile's app to show its own
channel: Review, Queued, To post and the counts on the menu filtered to
it, "Channel" in the menu going straight to its page. It's a cookie, so
each profile keeps its own. Today and Activity always show everything:
something needing you on another channel shouldn't be hidden.
"""

from __future__ import annotations

from flask import request

COOKIE = "focus_channel"
YEAR = 365 * 86400


def current(channels: dict = None) -> str:
    """The channel key this browser is focused on, or "" for all of them."""
    key = (request.cookies.get(COOKIE) or "").strip()
    if not key:
        return ""
    if channels is None:
        from core.channels import load_channels
        channels = load_channels(validate=False)
    return key if key in channels else ""


def keep(rows, key_of=lambda r: r["channel_key"], channels: dict = None):
    """Only the focused channel's rows (all of them with no focus)."""
    focus = current(channels)
    return [r for r in rows if not focus or key_of(r) == focus]


# --- channels not yet publishing (decision 139) ---------------------------------------
#
# The owner, 28 Oct: the channels still being set up are "mostly just tests
# for now", so Today, Insights and the channel picker leave them out unless
# this browser asks for them.

TESTS_COOKIE = "include_tests"


def include_tests() -> bool:
    try:
        return request.cookies.get(TESTS_COOKIE) == "1"
    except RuntimeError:              # outside a request: everything
        return True


def is_test(channel) -> bool:
    """Not archived and not publishing yet: a channel still being tried out."""
    return not channel.archived and not channel.publishing.enabled


def visible(channels: dict) -> dict:
    """The channels to show: unarchived, and publishing unless tests are
    included."""
    tests = include_tests()
    return {k: c for k, c in channels.items() if not c.archived and (tests or not is_test(c))}
