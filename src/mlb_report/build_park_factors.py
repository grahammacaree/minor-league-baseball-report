"""
Offseason entrypoint for recomputing park factors.

One completed season at a time. Seasons already on disk are left alone, so a
routine yearly update fetches one season rather than three; the blend in
park.py handles the rest.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import park_builder, statsapi
from .config_loader import bundled_config_dir


def _output_dir():
    directory = bundled_config_dir() / "park_factors"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-park-factors",
        description="Compute component park factors for one completed season.",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=date.today().year - 1,
        help="season to compute (default: last year)",
    )
    parser.add_argument(
        "--sports",
        type=int,
        nargs="*",
        default=list(statsapi.AFFILIATE_SPORT_IDS),
        help="sport ids to cover",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="recompute seasons already on disk",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    directory = _output_dir()

    if args.season >= date.today().year:
        print(
            f"Season {args.season} is not complete. Park factors are only "
            "meaningful over a full schedule.",
            file=sys.stderr,
        )
        return 1

    written = 0
    for sport_id in args.sports:
        print(f"sport {sport_id}: fetching {args.season}...")
        try:
            by_league = park_builder.build(sport_id, args.season)
        except statsapi.StatsApiError as error:
            print(f"  skipped: {error}", file=sys.stderr)
            continue

        for league_id, parks in by_league.items():
            path = directory / f"{league_id}-{args.season}.json"
            if path.exists() and not args.force:
                print(f"  league {league_id}: already on disk, skipping")
                continue
            path.write_text(
                json.dumps(
                    {str(team): factors for team, factors in sorted(parks.items())},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            written += 1
            print(f"  league {league_id}: {len(parks)} parks -> {path.name}")

    print(f"\n{written} league-season file(s) written to {directory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
