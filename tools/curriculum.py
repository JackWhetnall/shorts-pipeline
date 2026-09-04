"""
Build and inspect a channel's topic syllabus from the command line.

    python tools/curriculum.py status minute_pastor
    python tools/curriculum.py outline my_channel --topics 25 --topics 1000
    python tools/curriculum.py fill my_channel --count 5
    python tools/curriculum.py fill my_channel --all
    python tools/curriculum.py list my_channel --pending
    python tools/curriculum.py skip my_channel t0042 --note "covered elsewhere"

`outline` designs the running order; `fill` writes the subtopics for topics
that do not have them yet. Both cost money and both say what they will
cost before doing it — `--yes` skips the confirmation, for a scheduled
run.

`fill --all` is the one worth thinking about: it writes every remaining
topic in one go, which is a real cost and generates subtopics long
before they are needed. Filling as you approach each topic is cheaper and
lets later ones be written knowing what has already been discarded.
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
    print(f"  topics      {state['topics_filled']}/{state['topic_count']} filled")
    print(f"  subtopics   {state['total']} written "
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

    cost = estimate_cost(args.topics)
    print(f"Designing a {args.units}-unit outline for {args.channel}. "
          f"About ${cost['outline_usd']:.2f}.")
    if not _confirm("Go ahead?", args.yes):
        return

    outline = plan_outline(channel, args.topics, args.subtopics, args.subject or "")
    curriculum.start(args.channel, outline.get("subject", ""), outline["topics"])

    print(f"\n{outline.get('subject', '')}\n")
    for i, topic in enumerate(outline["topics"], 1):
        print(f"{i:2d}. [{unit['level']:12s}] {topic['title']}  "
              f"({unit['target_topics']} topics)")
    print(f"\nNow write the topics:\n"
          f"  python tools/curriculum.py fill {args.channel} --count 5")


def cmd_fill(args) -> None:
    from pipeline.curriculum_gen import estimate_cost, write_subtopics

    channel = _channel(args.channel)
    if not curriculum.progress(args.channel)["has_curriculum"]:
        raise SystemExit(f"{args.channel} has no outline yet. Run `outline` first.")

    remaining = sum(1 for t in curriculum.load(args.channel)["topics"]
                    if not t.get("filled"))
    if not remaining:
        print("Every topic already has its subtopics.")
        return

    wanted = remaining if args.all else min(args.units, remaining)
    cost = estimate_cost()
    print(f"Writing subtopics for {wanted} topic(s). "
          f"About ${cost['per_unit_usd'] * wanted:.2f}.")
    if not _confirm("Go ahead?", args.yes):
        return

    added = 0
    for _ in range(wanted):
        topic = curriculum.next_unfilled_topic(args.channel)
        if topic is None:
            break
        try:
            subtopics = write_subtopics(channel, curriculum.load(args.channel), topic)
        except PipelineError as exc:
            # Stop, keep what worked. Partial progress is saved after each
            # unit, so nothing already paid for is lost.
            print(f"\n{topic['title']} failed: {exc.user_message}")
            break
        before = curriculum.progress(args.channel)["total"]
        curriculum.add_subtopics(args.channel, topic["id"], subtopics)
        written = curriculum.progress(args.channel)["total"] - before
        added += written
        print(f"  {topic['title']}: {written} topics")

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

    rows = curriculum.subtopics(args.channel, status=status)
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
    curriculum.skip(args.channel, args.subtopic_id, args.note or "")
    print(f"Skipped {args.subtopic_id}.")


def cmd_unskip(args) -> None:
    curriculum.unskip(args.channel, args.subtopic_id)
    print(f"{args.subtopic_id} is back in the queue.")


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
    p.add_argument("--topics", type=int, default=40,
                   help="How many topics the syllabus has.")
    p.add_argument("--subtopics", type=int, default=1000,
                   help="Roughly how many subtopics (videos) in total.")
    p.add_argument("--subject", help="Overrides what the style prompt implies.")
    p.set_defaults(func=cmd_outline)

    p = subparsers.add_parser("fill", help="Write subtopics for unfilled topics.")
    p.add_argument("channel")
    p.add_argument("--count", type=int, default=1,
                   help="How many topics to fill.")
    p.add_argument("--all", action="store_true", help="Every remaining topic.")
    p.set_defaults(func=cmd_fill)

    p = subparsers.add_parser("list", help="The subtopics themselves.")
    p.add_argument("channel")
    p.add_argument("--pending", action="store_true")
    p.add_argument("--skipped", action="store_true")
    p.add_argument("--done", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="Show the angles.")
    p.set_defaults(func=cmd_list)

    p = subparsers.add_parser("skip", help="Take one subtopic out of the queue.")
    p.add_argument("channel")
    p.add_argument("subtopic_id")
    p.add_argument("--note")
    p.set_defaults(func=cmd_skip)

    p = subparsers.add_parser("unskip", help="Put a skipped subtopic back.")
    p.add_argument("channel")
    p.add_argument("subtopic_id")
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
