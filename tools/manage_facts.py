"""
Maintain the quiz fact store (pipeline.facts, facts/facts.db).

    python tools/manage_facts.py stats
    python tools/manage_facts.py define "Harry Potter"       # map a category onto Wikidata
    python tools/manage_facts.py harvest "Harry Potter"      # its first page of facts
    python tools/manage_facts.py grow "Harry Potter"         # a page deeper
    python tools/manage_facts.py stock the_pub_quiz_round    # every category that channel has
    python tools/manage_facts.py show "Space" --level 7      # a sample round's facts
    python tools/manage_facts.py refresh --days 180          # re-pull old facts

The app does `stock` for every quiz channel by itself, hourly (see
pipeline.facts.keep); these are for doing it now, or by hand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logging_setup import configure                         # noqa: E402
from pipeline.facts import categories, harvest, keep, pick, store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats")
    for name in ("define", "harvest", "grow"):
        sub.add_parser(name).add_argument("category")
    sub.add_parser("stock").add_argument("channel")
    show = sub.add_parser("show")
    show.add_argument("category")
    show.add_argument("--level", type=float, default=5.0)
    show.add_argument("--count", type=int, default=10)
    refresh = sub.add_parser("refresh")
    refresh.add_argument("--days", type=int, default=180)
    args = parser.parse_args()
    configure()
    conn = store.connect()

    if args.command == "stats":
        print(store.totals(conn))
        for record in store.categories(conn):
            size = len(pick.pool(conn, record["name"], bool(record["spec"].get("general"))))
            print(f"  {record['name']}: {size} askable facts"
                  + ("" if record["spec"].get("general") else f", {len(record['spec']['sets'])} sets"))
    elif args.command == "define":
        spec = categories.define(conn, args.category)
        for entity_set in spec.get("sets", []):
            print(f"  {entity_set['name']}: {entity_set}")
    elif args.command in ("harvest", "grow"):
        if store.category(conn, args.category) is None:
            categories.define(conn, args.category)
        print(harvest.harvest(conn, args.category, grow=args.command == "grow"))
    elif args.command == "stock":
        from core.channels import load_channels
        print(keep.stock(conn, load_channels(validate=False)[args.channel]))
    elif args.command == "show":
        for fact in pick.for_round(conn, "preview", args.category, args.level, args.count):
            print(f"  {fact['level']:>5}  {pick.describe(fact)}")
    elif args.command == "refresh":
        print(f"refreshed {harvest.refresh(conn, args.days)} entities")
    return 0


if __name__ == "__main__":
    sys.exit(main())
