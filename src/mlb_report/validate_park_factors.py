"""
Diagnostics for the park factor construction.

The point of a park factor is to isolate the park. This checks that it does, by
asking whether the factors track something they should have nothing to do with:
the quality of the home pitching staff, measured away from the park.

Three constructions are compared, since the choice between them is not obvious
and should be answerable from data rather than from memory:

  home     what the builder uses — the home club's games, both sides, here vs
           elsewhere. The club's own roster is constant across the comparison.
  pooled   every club's offence at the park vs those clubs elsewhere.
  visitors visiting offence only at the park vs those visitors elsewhere.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from . import park_builder, statsapi
from .park_builder import Totals

METHODS = ("home", "pooled", "visitors")


def _collect(home_of, logs, teams, method):
    if method == "home":
        return None  # handled by the builder itself

    at, away = defaultdict(Totals), defaultdict(Totals)
    parks = set(home_of.values())
    for park in parks:
        for team_id, games in logs.items():
            if method == "visitors" and team_id == park:
                continue
            if not any(home_of.get(game) == park for game in games):
                continue
            for game_pk, stat in games.items():
                where = home_of.get(game_pk)
                if where == park:
                    at[park].add(stat)
                elif where is not None:
                    away[park].add(stat)

    return {
        park: {
            "at": at[park],
            "elsewhere": away[park],
            "league_id": teams[park].get("league", {}).get("id", 0),
        }
        for park in parks
        if at[park].plate_appearances and away[park].plate_appearances
    }


def _flatten(by_league):
    return {
        park: factors for parks in by_league.values() for park, factors in parks.items()
    }


def staff_rate_away(home_of, logs, component="strikeOuts"):
    """
    Each club's pitching rate in its road games.

    In a road game the host bats against this club's pitchers, so the host's
    offensive line measures the staff with the club's own park excluded by
    construction.
    """
    rates = {}
    for club, games in logs.items():
        totals = Totals()
        for game_pk in games:
            host = home_of.get(game_pk)
            if host is None or host == club:
                continue
            totals.add(logs.get(host, {}).get(game_pk, {}))
        rates[club] = totals.rate("strikeouts")
    return rates


def correlate(pairs):
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    count = len(pairs)
    if count < 4:
        return None, count
    mean_x = sum(x for x, _ in pairs) / count
    mean_y = sum(y for _, y in pairs) / count
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    spread_x = sum((x - mean_x) ** 2 for x, _ in pairs) ** 0.5
    spread_y = sum((y - mean_y) ** 2 for _, y in pairs) ** 0.5
    if not spread_x or not spread_y:
        return None, count
    return covariance / (spread_x * spread_y), count


def evaluate(sport_id: int, seasons: list[int]) -> None:
    per_season = {}
    for season in seasons:
        print(f"fetching sport {sport_id} {season}...", flush=True)
        home_of = park_builder.home_team_by_game(sport_id, season)
        logs, teams = park_builder.team_game_logs(sport_id, season)

        factors = {}
        for method in METHODS:
            collected = (
                park_builder.collect(sport_id, season)
                if method == "home"
                else _collect(home_of, logs, teams, method)
            )
            factors[method] = _flatten(park_builder.factors(collected))

        per_season[season] = {
            "factors": factors,
            "staff": staff_rate_away(home_of, logs),
            "names": {tid: team["name"] for tid, team in teams.items()},
        }

    latest = per_season[seasons[-1]]

    print("\n=== Contamination by the home pitching staff ===")
    print("    Strikeout factor against the home staff's strikeout rate on the")
    print("    road. The park should know nothing about this; nearer zero is")
    print("    cleaner.")
    for method in METHODS:
        pairs = [
            (latest["staff"].get(park), factors["strikeouts"])
            for park, factors in latest["factors"][method].items()
        ]
        value, count = correlate(pairs)
        if value is None:
            print(f"  {method:9} n/a")
        else:
            print(f"  {method:9} {value:+.2f} (n={count})")

    if len(seasons) > 1:
        print("\n=== Year-over-year agreement ===")
        print("    Read with care: a contaminated estimator inherits the")
        print("    stability of whatever is contaminating it, and rosters")
        print("    persist across seasons.")
        first, last = per_season[seasons[0]], per_season[seasons[-1]]
        for method in METHODS:
            shared = set(first["factors"][method]) & set(last["factors"][method])
            line = f"  {method:9}"
            for component in ("runs", "home_runs", "strikeouts"):
                pairs = [
                    (
                        first["factors"][method][park][component],
                        last["factors"][method][park][component],
                    )
                    for park in shared
                ]
                value, count = correlate(pairs)
                line += f"  {component} {value:+.2f}" if value else f"  {component} n/a"
            print(f"{line}  (n={len(shared)})")

    print("\n=== Most extreme parks, as built ===")
    ranked = sorted(latest["factors"]["home"].items(), key=lambda kv: -kv[1]["runs"])
    for park, factors in ranked[:3] + ranked[-3:]:
        name = latest["names"].get(park, str(park))
        print(
            f"  {name[:26]:28} runs {factors['runs']:.3f}  "
            f"HR {factors['home_runs']:.3f}  K {factors['strikeouts']:.3f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate-park-factors",
        description="Check that park factors isolate the park.",
    )
    parser.add_argument("--sport", type=int, default=12, help="sport id (default: AA)")
    parser.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025])
    args = parser.parse_args(argv)

    try:
        evaluate(args.sport, args.seasons)
    except statsapi.StatsApiError as error:
        print(f"fetch failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
