from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from . import digest as digest_module
from . import fetchers, pipeline, store
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
        "--date",
        type=date.fromisoformat,
        default=date.today() - timedelta(days=1),
        help="day to report on (default: yesterday)",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="season to report on (default: the report date's year)",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="digest",
        choices=["digest", "prospects", "fetch"],
        help="prospects lists tracked players; fetch pulls logs into the local store",
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


def _fetch(season: int, org_id: int) -> None:
    tracked = prospects_module.tracked_prospects(season)
    logs = fetchers.game_logs(tracked, org_id, season)
    added = store.save(season, logs)
    print(f"fetched {len(logs)} game logs for {len(tracked)} prospects ({added} new)")

    since, until = fetchers.lookback_window(date.today(), days=7)
    moves = fetchers.transactions(tracked, org_id, season, since, until)
    print(f"{len(moves)} tracked moves since {since}")
    for entry in moves:
        print(f"  {entry.effective_date}  {entry.description}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    season = args.season or args.date.year

    if args.command == "prospects":
        _print_prospects(season)
        return 0

    if args.command == "fetch":
        _fetch(season, settings["org"]["team_id"])
        return 0

    digest = pipeline.build_digest(args.date, season, settings)
    print(digest_module.render(digest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
