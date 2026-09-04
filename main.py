"""
Command-line entry point.

    python main.py                          list channels
    python main.py minute_pastor            make one video
    python main.py minute_pastor --count 5  make five
    python main.py minute_pastor --yes      don't ask about each seed
    python main.py --costs                  what everything has cost so far
    python main.py --sameness               how alike the channels have become

The interactive reroll loop lives here rather than in the pipeline. The
pipeline never prompts — it has no terminal on a background thread — so
asking is the caller's job, and both callers (this and the web app) build
their own answer to "is this seed any good" on the same `fetch_seed`.
"""

from __future__ import annotations

import argparse
import sys

from core import costs
from core.channels import load_channels
from core.errors import PipelineError, friendly_message
from core.logging_setup import configure, get_logger
from pipeline.run import fetch_seed, generate

log = get_logger(__name__)


def pick_seed(channel, assume_yes: bool = False):
    """Reroll until the seed is approved."""
    while True:
        seed = fetch_seed(channel)
        if assume_yes:
            return seed
        print()
        if seed.type == "quote":
            print(f"  Quote:     {seed.text}")
            print(f"  Reference: {seed.reference}")
        else:
            print(f"  Topic: {seed.topic}")
        print()
        if input("Use this? [Y/n] ").strip().lower() in ("", "y", "yes"):
            return seed
        print("Rerolling...")


def list_channels() -> None:
    channels = load_channels(validate=False)
    if not channels:
        print("No channels configured yet. Add one in the web app: python -m web")
        return
    print(f"{len(channels)} channel(s):\n")
    for key, channel in channels.items():
        detail = channel.source if channel.content_mode == "static_corpus" else \
            f"{len(channel.topics)} topic(s)"
        print(f"  {key:24s} {channel.channel_display_name:24s} {channel.content_mode} ({detail})")


def show_costs() -> None:
    summary = costs.summary_all()
    if not summary["calls"]:
        print("Nothing recorded yet.")
        return
    print(f"Total: {costs.format_usd(summary['total_usd'])} "
          f"across {summary['calls']} API call(s)\n")
    for operation, amount in summary["by_operation"].items():
        print(f"  {operation:34s} {costs.format_usd(amount):>10s}")
    if summary["cache_read_tokens"]:
        print(f"\n  {summary['cache_read_tokens']:,} input tokens served from cache "
              f"(billed at a tenth of the usual rate).")


def show_sameness() -> None:
    """How alike different channels' output has become.

    This is the risk no per-channel check can see: each channel can be
    perfectly consistent with itself while every channel converges on the
    same house style, which is what reads as templated at volume.
    """
    from pipeline import similarity

    pairs = similarity.cross_channel_report()
    if not pairs:
        print("Not enough history yet — this needs at least two channels with "
              "generated scripts.")
        return
    print("Channel pairs, most alike first:\n")
    for pair in pairs:
        a, b = pair["channels"]
        flag = "  <-- worth a look" if pair["vocabulary_overlap"] > 0.75 else ""
        print(f"  {a} vs {b}{flag}")
        print(f"    wording overlap {pair['vocabulary_overlap']:.0%}  "
              f"phrase overlap {pair['phrase_overlap']:.0%}  "
              f"length similarity {pair['length_ratio']:.0%}")
    print("\nHigh wording overlap between channels means they are converging on "
          "one voice. Distinct style prompts and pacing are the levers.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate short-form videos.")
    parser.add_argument("channel", nargs="?", help="Channel key. Omit to list channels.")
    parser.add_argument("--count", type=int, default=1, help="How many videos to make.")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Accept each quote/topic without asking.")
    parser.add_argument("--costs", action="store_true", help="Show recorded API spend and exit.")
    parser.add_argument("--sameness", action="store_true",
                        help="Show how alike the channels' scripts have become.")
    args = parser.parse_args()

    configure()

    if args.costs:
        show_costs()
        return 0
    if args.sameness:
        show_sameness()
        return 0
    if not args.channel:
        list_channels()
        return 0

    channels = load_channels(validate=False)
    if args.channel not in channels:
        print(f'No channel called "{args.channel}". Known channels:', file=sys.stderr)
        list_channels()
        return 1

    channel = channels[args.channel]
    try:
        channel.validate()
    except PipelineError as exc:
        print(exc.user_message, file=sys.stderr)
        return 1

    for i in range(args.count):
        if args.count > 1:
            print(f"\n=== Video {i + 1} of {args.count} ===")
        seed = pick_seed(channel, assume_yes=args.yes)
        try:
            generate(channel, seed, interactive=True)
        except PipelineError as exc:
            print(f"\n{exc.user_message}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            log.exception("Generation failed")
            print(f"\n{friendly_message(exc)}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
