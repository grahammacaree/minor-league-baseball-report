"""
Computes component park factors from game-level data.

The construction is the standard with/without comparison, applied per component
rather than only to runs: for each park, compare the rate of an event in games
played there against the rate the same clubs produced everywhere else. Because
each game appears in both clubs' logs, pooling by venue captures both offences,
not just the home team's.

This is offseason work. Nothing in the daily digest calls it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from . import statsapi
from .park import COMPONENTS

# Regression toward neutral, in plate appearances. A park with a full season of
# roughly 5,000 PA keeps most of its observed effect; a park with a handful of
# games keeps almost none.
REGRESSION_PA = 4000


@dataclass
class Totals:
    plate_appearances: float = 0.0
    balls_in_play: float = 0.0
    events: dict[str, float] = field(
        default_factory=lambda: dict.fromkeys(COMPONENTS, 0.0)
    )

    def add(self, stat: dict) -> None:
        def value(key: str) -> float:
            try:
                return float(stat.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        plate_appearances = value("plateAppearances")
        strikeouts = value("strikeOuts")
        walks = value("baseOnBalls")
        home_runs = value("homeRuns")
        hits = value("hits")
        doubles = value("doubles")
        triples = value("triples")

        self.plate_appearances += plate_appearances
        self.balls_in_play += max(
            plate_appearances - strikeouts - walks - home_runs, 0.0
        )
        self.events["runs"] += value("runs")
        self.events["strikeouts"] += strikeouts
        self.events["walks"] += walks
        self.events["home_runs"] += home_runs
        self.events["hits_in_play"] += max(hits - home_runs, 0.0)
        self.events["extra_base_hits"] += doubles + triples + home_runs

    def rate(self, component: str) -> float | None:
        # Hits in play are judged per ball in play, since a park that changes
        # the strikeout rate would otherwise move this for the wrong reason.
        denominator = (
            self.balls_in_play
            if component == "hits_in_play"
            else self.plate_appearances
        )
        if denominator <= 0:
            return None
        return self.events[component] / denominator


def venues_by_game(sport_id: int, season: int) -> dict[int, int]:
    """Every completed game's home team, which is what identifies the park."""
    payload = statsapi.get(
        "schedule",
        sportId=sport_id,
        season=season,
        gameType="R",
        fields=(
            "dates,games,gamePk,status,detailedState,teams,home,away,team,id,venue,id"
        ),
    )
    mapping = {}
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            if game.get("status", {}).get("detailedState") != "Final":
                continue
            home_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
            if home_id:
                mapping[game["gamePk"]] = home_id
    return mapping


def collect(sport_id: int, season: int) -> dict[int, dict]:
    """
    Per-park totals, split into games at the park and games away from it.

    Returns one entry per home club, keyed by team id, since a club and its
    park are one to one within a season.
    """
    home_team_of = venues_by_game(sport_id, season)
    teams = [
        team
        for team in statsapi.get("teams", sportId=sport_id, season=season).get(
            "teams", []
        )
    ]

    at_park: dict[int, Totals] = defaultdict(Totals)
    elsewhere: dict[int, Totals] = defaultdict(Totals)
    visitors: dict[int, set[int]] = defaultdict(set)
    league_of: dict[int, int] = {}
    club_logs: dict[int, list[tuple[int, dict]]] = {}

    for team in teams:
        team_id = team["id"]
        league_of[team_id] = team.get("league", {}).get("id", 0)
        splits = statsapi.get(
            f"teams/{team_id}/stats",
            stats="gameLog",
            group="hitting",
            season=season,
            sportId=sport_id,
        )
        rows = [
            split
            for block in splits.get("stats", [])
            for block_splits in [block["splits"]]
            for split in block_splits
        ]
        club_logs[team_id] = [
            (row.get("game", {}).get("gamePk"), row.get("stat", {})) for row in rows
        ]

    for team_id, rows in club_logs.items():
        for game_pk, stat in rows:
            park = home_team_of.get(game_pk)
            if park is None:
                continue
            at_park[park].add(stat)
            visitors[park].add(team_id)

    # A club's games elsewhere are every game it played at a different park.
    for park, clubs in visitors.items():
        for team_id in clubs:
            for game_pk, stat in club_logs.get(team_id, []):
                if home_team_of.get(game_pk) not in (None, park):
                    elsewhere[park].add(stat)

    return {
        park: {
            "at": at_park[park],
            "elsewhere": elsewhere[park],
            "league_id": league_of.get(park, 0),
        }
        for park in at_park
    }


def _regress(raw: float, sample: float) -> float:
    weight = sample / (sample + REGRESSION_PA)
    return 1.0 + (raw - 1.0) * weight


def factors(collected: dict[int, dict]) -> dict[int, dict[int, dict[str, float]]]:
    """
    Regressed, league-normalized factors, grouped by league.

    Normalizing within the league is what makes 1.0 mean "neutral for this
    league" rather than "neutral in some absolute sense".
    """
    by_league: dict[int, dict[int, dict[str, float]]] = defaultdict(dict)

    for park, data in collected.items():
        at, away = data["at"], data["elsewhere"]
        components = {}
        for component in COMPONENTS:
            home_rate = at.rate(component)
            away_rate = away.rate(component)
            if not home_rate or not away_rate:
                components[component] = 1.0
                continue
            components[component] = _regress(
                home_rate / away_rate, at.plate_appearances
            )
        by_league[data["league_id"]][park] = components

    for parks in by_league.values():
        for component in COMPONENTS:
            values = [park[component] for park in parks.values()]
            mean = sum(values) / len(values) if values else 1.0
            if mean > 0:
                for park in parks.values():
                    park[component] /= mean
    return by_league


def build(sport_id: int, season: int) -> dict[int, dict[int, dict[str, float]]]:
    return factors(collect(sport_id, season))
