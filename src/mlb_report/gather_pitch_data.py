"""
Entrypoint for topping up the play-by-play cache.

The digest reads whatever swing outcomes have already been gathered and says
nothing where it finds none, so a run without this leaves the batted-ball
skills — whiffs, grounders, spray, home runs per fly ball — quietly missing.
Games already cached are skipped, so this is a full backfill once and a
handful of games a day thereafter.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from . import pitch_data, statsapi


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gather-pitch-data",
        description="Fetch and cache play-by-play for games not yet held.",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=date.today().year,
        help="season to gather (default: this year)",
    )
    parser.add_argument(
        "--sports",
        type=int,
        nargs="*",
        default=list(statsapi.FULL_SEASON_SPORT_IDS),
        help=(
            "sport ids to cover (default: the four full-season levels). The "
            "complex and Dominican levels cost thousands of games for skills "
            "no top-thirty prospect is judged on."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # A level that fails is not worth abandoning the rest for: the digest
    # degrades to the skills it can still measure rather than not arriving.
    failed = 0
    for sport_id in args.sports:
        try:
            pitch_data.gather(sport_id, args.season)
        except statsapi.StatsApiError as error:
            print(f"  sport {sport_id}: skipped, {error}", file=sys.stderr)
            failed += 1

    if failed == len(args.sports):
        print("No level could be gathered.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
