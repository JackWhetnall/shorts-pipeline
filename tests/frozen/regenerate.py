"""
Write the frozen channels' goldens again (decision 075).

Only with the owner's agreement that Minute Pastor's or Pub Quiz Buzz's
videos should change. It prints what changed from the last goldens;
commit the new ones with the change that caused it.

    python -m tests.frozen.regenerate
"""

from __future__ import annotations

import os
import sys

import pytest


def main() -> int:
    os.environ["FROZEN_WRITE"] = "1"
    return pytest.main(["tests/frozen", "-q", "-s", "-p", "no:cacheprovider"])


if __name__ == "__main__":
    sys.exit(main())
