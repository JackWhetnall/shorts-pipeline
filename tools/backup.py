"""
Back up everything on this machine that can't be regenerated.

    python tools/backup.py "C:/Users/you/OneDrive/ShortsBackups"
    python tools/backup.py DEST --keep 30
    python tools/backup.py DEST --include-secrets

Writes one dated zip per run and keeps the newest 14 by default. Run it
daily from Windows Task Scheduler; see README "Backups". What goes in and
what is left out is explained in core/backup.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.backup import DEFAULT_KEEP, create_backup                # noqa: E402
from core.errors import PipelineError                             # noqa: E402
from core.logging_setup import configure, get_logger              # noqa: E402

log = get_logger(__name__)


def main() -> int:
    configure()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    parser.add_argument("dest", help="Folder to write backups into (e.g. inside OneDrive).")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                        help=f"How many backups to keep (default {DEFAULT_KEEP}).")
    parser.add_argument("--include-secrets", action="store_true",
                        help="Also back up YouTube OAuth credentials and tokens.")
    args = parser.parse_args()
    try:
        create_backup(args.dest, keep=args.keep, include_secrets=args.include_secrets)
    except PipelineError as exc:
        log.error(exc.user_message)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
