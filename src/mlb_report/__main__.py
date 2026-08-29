from __future__ import annotations

import argparse
import sys
from datetime import date

from . import prospects as prospects_module
from .config_loader import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mlb_report",
        description="Build the daily Mariners farm system digest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the digest instead of emailing it",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=date.today().year,
        help="season to report on (default: current year)",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="digest",
        choices=["digest", "prospects"],
        help="prospects prints the tracked list and exits",
    )
    return parser


def _print_prospects(season: int) -> None:
    tracked = prospects_module.tracked_prospects(season)
    for p in tracked:
        player_id = p.player_id or "unresolved"
        print(f"{p.rank:>2}. {p.name:<20} {p.position:<6} {player_id}")

    unresolved = [p.name for p in tracked if p.player_id is None]
    if unresolved:
        print(f"\nNo player id found for: {', '.join(unresolved)}")

    captured = prospects_module.captured_on()
    if prospects_module.refresh_due(captured):
        print(f"\nRanking captured {captured} — a Pipeline update has landed since.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()

    if args.command == "prospects":
        _print_prospects(args.season)
        return 0

    print(f"{settings['org']['team_name']} farm report")
    if args.dry_run:
        print("(dry run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
