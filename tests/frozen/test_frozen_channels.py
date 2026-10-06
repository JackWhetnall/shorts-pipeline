"""
Minute Pastor and Pub Quiz Buzz are frozen (decision 075): the project
has moved to long-form, and these two channels are kept exactly as they
are. This is the check that keeps them that way.

Each channel's real pipeline runs end to end with every outside service
recorded (tests/frozen/harness.py): the requests to Claude and
ElevenLabs word for word, the footage chosen, the quiz board, frames of
the picture, the sound, the files written beside each video, the long
quiz Pub Quiz Buzz recuts from its shorts, and the settings and slots
each channel resolves to. The result has to match the golden copy.

When it doesn't, a change to shared code has changed one of these
channels' videos. Make the change additive instead (behind a default
the frozen channels keep), or, if the owner has agreed to the change,
write the goldens again:

    python -m tests.frozen.regenerate

and commit them with the change, saying what changed and why.
"""

from __future__ import annotations

import json
import os

import pytest

from tests.frozen import harness

pytestmark = pytest.mark.frozen

WRITE = os.environ.get("FROZEN_WRITE") == "1"


@pytest.mark.parametrize("key", harness.FROZEN)
def test_a_frozen_channel_makes_exactly_what_it_did(key, tmp_path, monkeypatch):
    actual = harness.fingerprint(key, tmp_path / "run", monkeypatch)

    assert not actual["touched_real_data"], (
        f"{key}'s frozen run reached the installation's own data, so it isn't isolated: "
        f"{actual['touched_real_data']}. Redirect that path in tests/frozen/harness.py.")

    path = harness.golden_path(key)
    if WRITE:
        before = harness.read_golden(key) if path.exists() else {}
        harness.write_golden(key, actual)
        changed = harness.differences(before, actual, limit=40)
        print(f"\n{key}: golden written ({len(changed)} difference(s) from the last one)")
        for line in changed:
            print("  " + line)
        return

    assert path.exists(), (f"No golden for {key}. Write it with: python -m tests.frozen.regenerate")
    expected = harness.read_golden(key)
    changed = harness.differences(expected, actual)
    if changed:
        saved = tmp_path / "actual.json"
        saved.write_text(json.dumps(actual, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        pytest.fail(
            f"{key} is frozen, and this change alters what it makes:\n  " + "\n  ".join(changed) +
            f"\n\nThe whole new fingerprint, with frames of the picture, is in {tmp_path}.\n"
            "Make the change additive, or with the owner's agreement run "
            "`python -m tests.frozen.regenerate` and commit the goldens (decision 075).",
            pytrace=False)


def test_the_snapshot_is_of_the_two_frozen_channels():
    """What's pinned is these two channels, as they were on 6 Oct 2026."""
    assert set(harness.FROZEN) == {"minute_pastor", "pub_quiz_buzz"}
    assert harness.CHANNELS["pub_quiz_buzz"]["format"] == "quiz"
    assert harness.CHANNELS["minute_pastor"]["source"] == "bible"
