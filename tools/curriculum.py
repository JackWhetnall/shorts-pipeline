"""
Build and inspect a channel's topic syllabus from the command line.

    python tools/curriculum.py status minute_pastor
    python tools/curriculum.py outline my_channel --units 25 --topics 1000
    python tools/curriculum.py fill my_channel --units 5
    python tools/curriculum.py fill my_channel --all
    python tools/curriculum.py list my_channel --pending
    python tools/curriculum.py skip my_channel t0042 --note "covered elsewhere"

`outline` designs the running order; `fill` writes the topics for units
that do not have them yet. Both cost money and both say what they will
cost before doing it — `--yes` skips the confirmation, for a scheduled
run.

`fill --all` is the one worth thinking about: it writes every remaining
unit in one go, which is a real cost and generates topics long before
they are needed. Filling as you approach each unit is cheaper and lets
later units be written knowing what has already been discarded.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import curriculum                                       # noqa: E402
from core.channels import load_channels                           # noqa: E402
from core.errors import PipelineError                             # noqa: E402
from core.logging_setup import configure, get_logger              # noqa: E402

log = get_logger(__name__)


def _channel(key: str):
    channels = load_channels(validate=False)
    if key not in channels:
        raise SystemExit(f'No channel called "{key}". '
                         f'Try one of: {", ".join(channels)}')
    return channels[key]


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


def cmd_status(args) -> None:
    state = curriculum.progress(args.channel)
    if not state["has_curriculum"]:
        print(f"{args.channel} has no topic plan. Make one with:\n"
              f"  python tools/curriculum.py outline {args.channel}")
        return

    print(f"\n{args.channel}: {state['subject']}\n")
    print(f"  units       {state['units_filled']}/{state['unit_count']} filled")
    print(f"  topics      {state['total']} written "
          f"(planned {state['planned_total']})")
    print(f"  made        {state['done']} ({state['percent_done']:.0f}%)")
    print(f"  waiting     {state['pending']}  "
          f"(~{state['runway_days']} days at 2 a day)")
    print(f"  skipped     {state['skipped']}")
    if state["running_low"]:
        print("\n  Running low. Generation stops when this reaches zero.")

    nxt = curriculum.next_pending(args.channel)
    if nxt:
        print(f"\n  next up:  {nxt['title']}")


def cmd_outline(args) -> None:
    from pipeline.curriculum_gen import estimate_cost, plan_outline

    channel = _channel(args.channel)
    state = curriculum.progress(args.channel)
    if state["has_curriculum"] and state["done"]:
        print(f"{args.channel} has already made {state['done']} videos from its "
              f"current plan. Replacing it loses the record of what was covered.")
        if not _confirm("Replace it anyway?", args.yes):
            return

    cost = estimate_cost(args.units)
    print(f"Designing a {args.units}-unit outline for {args.channel}. "
          f"About ${cost['outline_usd']:.2f}.")
    if not _confirm("Go ahead?", args.yes):
        return

    outline = plan_outline(channel, args.units, args.topics, args.subject or "")
    curriculum.start(args.channel, outline.get("subject", ""), outline["units"])

    print(f"\n{outline.get('subject', '')}\n")
    for i, unit in enumerate(outline["units"], 1):
        print(f"{i:2d}. [{unit['level']:12s}] {unit['title']}  "
              f"({unit['target_topics']} topics)")
    print(f"\nNow write the topics:\n"
          f"  python tools/curriculum.py fill {args.channel} --units 5")


def cmd_fill(args) -> None:
    from pipeline.curriculum_gen import estimate_cost, write_unit_topics

    channel = _channel(args.channel)
    if not curriculum.progress(args.channel)["has_curriculum"]:
        raise SystemExit(f"{args.channel} has no outline yet. Run `outline` first.")

    remaining = sum(1 for u in curriculum.load(args.channel)["units"]
                    if not u.get("filled"))
    if not remaining:
        print("Every unit already has its topics.")
        return

    wanted = remaining if args.all else min(args.units, remaining)
    cost = estimate_cost()
    print(f"Writing topics for {wanted} unit(s). "
          f"About ${cost['per_unit_usd'] * wanted:.2f}.")
    if not _confirm("Go ahead?", args.yes):
        return

    added = 0
    for _ in range(wanted):
        unit = curriculum.next_unfilled_unit(args.channel)
        if unit is None:
            break
        try:
            topics = write_unit_topics(channel, curriculum.load(args.channel), unit)
        except PipelineError as exc:
            # Stop, keep what worked. Partial progress is saved after each
            # unit, so nothing already paid for is lost.
            print(f"\n{unit['title']} failed: {exc.user_message}")
            break
        before = curriculum.progress(args.channel)["total"]
        curriculum.add_topics(args.channel, unit["id"], topics)
        written = curriculum.progress(args.channel)["total"] - before
        added += written
        print(f"  {unit['title']}: {written} topics")

    state = curriculum.progress(args.channel)
    print(f"\n{added} topics added. {state['pending']} waiting "
          f"(~{state['runway_days']} days).")


def cmd_list(args) -> None:
    status = None
    if args.pending:
        status = curriculum.PENDING
    elif args.skipped:
        status = curriculum.SKIPPED
    elif args.done:
        status = curriculum.PUBLISHED

    rows = curriculum.topics(args.channel, status=status)
    if not rows:
        print("Nothing to show.")
        return
    for topic in rows:
        marker = {"pending": " ", "used": "~", "published": "x", "skipped": "-"}
        print(f"[{marker.get(topic['status'], '?')}] {topic['id']}  {topic['title']}")
        if args.verbose and topic["angle"]:
            print(f"        {topic['angle']}")
    print(f"\n{len(rows)} topic(s).")


def cmd_skip(args) -> None:
    curriculum.skip(args.channel, args.topic_id, args.note or "")
    print(f"Skipped {args.topic_id}.")


def cmd_unskip(args) -> None:
    curriculum.unskip(args.channel, args.topic_id)
    print(f"{args.topic_id} is back in the queue.")


def main() -> None:
    configure()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--yes", action="store_true",
                        help="Don't ask before spending money.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("status", help="Where a channel's plan has got to.")
    p.add_argument("channel")
    p.set_defaults(func=cmd_status)

    p = subparsers.add_parser("outline", help="Design the running order.")
    p.add_argument("channel")
    p.add_argument("--units", type=int, default=25)
    p.add_argument("--topics", type=int, default=1000,
                   help="Roughly how many topics in total.")
    p.add_argument("--subject", help="Overrides what the style prompt implies.")
    p.set_defaults(func=cmd_outline)

    p = subparsers.add_parser("fill", help="Write topics for unfilled units.")
    p.add_argument("channel")
    p.add_argument("--units", type=int, default=1, help="How many units to write.")
    p.add_argument("--all", action="store_true", help="Every remaining unit.")
    p.set_defaults(func=cmd_fill)

    p = subparsers.add_parser("list", help="The topics themselves.")
    p.add_argument("channel")
    p.add_argument("--pending", action="store_true")
    p.add_argument("--skipped", action="store_true")
    p.add_argument("--done", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="Show the angles.")
    p.set_defaults(func=cmd_list)

    p = subparsers.add_parser("skip", help="Take one topic out of the queue.")
    p.add_argument("channel")
    p.add_argument("topic_id")
    p.add_argument("--note")
    p.set_defaults(func=cmd_skip)

    p = subparsers.add_parser("unskip", help="Put a skipped topic back.")
    p.add_argument("channel")
    p.add_argument("topic_id")
    p.set_defaults(func=cmd_unskip)

    args = parser.parse_args()
    # Every command names a channel, and "no such channel" is a better
    # answer to a typo than "that channel has no plan".
    _channel(args.channel)
    try:
        args.func(args)
    except PipelineError as exc:
        raise SystemExit(exc.user_message)


if __name__ == "__main__":
    main()
