"""
Computes component park factors from game-level data.

The construction is a with/without comparison held to one question: what varies
between the numerator and the denominator? For a park, we take the home club's
own games and compare what happened there against what happened when the same
club played elsewhere.

Both sides of the ball are used, and that is what keeps it clean. A club's
hitters face a roughly random draw of league pitching whether at home or on the
road, and its pitchers face a roughly random draw of league hitting either way.
The club's own roster is therefore held constant across the comparison and
cancels; only the park differs.

The tempting alternative — pooling every club's offence at a park and comparing
against those clubs elsewhere — fails this test. Visiting hitters at a park
always face the home staff, but not in the denominator, so a strong home
rotation reads as a pitcher-friendly park. See scripts/validate-park-factors.

This is offseason work. Nothing in the daily digest calls it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from . import pitch_data, statsapi
from .park import BOX_COMPONENTS, PITCH_COMPONENTS

# Regression toward neutral, in plate appearances. A park with a full season of
# roughly 10,000 PA across both sides keeps most of its observed effect; a park
# with a handful of games keeps almost none.
REGRESSION_PA = 4000


@dataclass
class Totals:
    plate_appearances: float = 0.0
    balls_in_play: float = 0.0
    events: dict[str, float] = field(
        default_factory=lambda: dict.fromkeys(BOX_COMPONENTS, 0.0)
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


def home_team_by_game(sport_id: int, season: int) -> dict[int, int]:
    """Every completed game's home club, which is what identifies the park."""
    payload = statsapi.get(
        "schedule",
        sportId=sport_id,
        season=season,
        gameType="R",
        fields="dates,games,gamePk,status,detailedState,teams,home,away,team,id",
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


def team_game_logs(
    sport_id: int, season: int
) -> tuple[dict[int, dict[int, dict]], dict]:
    """Each club's per-game offensive line, keyed by game."""
    teams = statsapi.get("teams", sportId=sport_id, season=season).get("teams", [])
    logs: dict[int, dict[int, dict]] = {}
    for team in teams:
        payload = statsapi.get(
            f"teams/{team['id']}/stats",
            stats="gameLog",
            group="hitting",
            season=season,
            sportId=sport_id,
        )
        rows = [
            split for block in payload.get("stats", []) for split in block["splits"]
        ]
        logs[team["id"]] = {
            row["game"]["gamePk"]: row.get("stat", {})
            for row in rows
            if row.get("game", {}).get("gamePk")
        }
    return logs, {team["id"]: team for team in teams}


def collect(sport_id: int, season: int) -> dict[int, dict]:
    """
    Per-park totals, split into the home club's games there and elsewhere.

    Both clubs' lines are counted in every game, so each park's totals cover
    the full run environment rather than one side of it.
    """
    home_of = home_team_by_game(sport_id, season)
    logs, teams = team_game_logs(sport_id, season)

    # Which clubs played in each game, so a game's opposing line can be found.
    sides: dict[int, list[int]] = defaultdict(list)
    for team_id, games in logs.items():
        for game_pk in games:
            sides[game_pk].append(team_id)

    collected = {}
    for club, games in logs.items():
        at_home, on_road = Totals(), Totals()
        for game_pk, own_line in games.items():
            venue_host = home_of.get(game_pk)
            if venue_host is None:
                continue
            opponents = [side for side in sides.get(game_pk, []) if side != club]
            bucket = at_home if venue_host == club else on_road
            bucket.add(own_line)
            for opponent in opponents:
                bucket.add(logs[opponent].get(game_pk, {}))

        if at_home.plate_appearances and on_road.plate_appearances:
            collected[club] = {
                "at": at_home,
                "elsewhere": on_road,
                "league_id": teams[club].get("league", {}).get("id", 0),
            }
    return collected


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
        for component in BOX_COMPONENTS:
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
        for component in BOX_COMPONENTS:
            values = [park[component] for park in parks.values()]
            mean = sum(values) / len(values) if values else 1.0
            if mean > 0:
                for park in parks.values():
                    park[component] /= mean
    return by_league


def _pitch_sample(component: str, totals: dict[str, int]) -> int:
    """
    How many chances produced the rate, so regression is scaled to it.

    Each component is regressed against its own denominator rather than a
    shared game count: a park sees far fewer batted balls than pitches, and
    treating the two as equally well measured would leave spray factors noisier
    than they look.
    """
    if component == "whiffs":
        return totals["swings"]
    if component == "called_strikes":
        return totals["pitches"] - totals["swings"]
    if component == "ground_balls":
        return sum(totals[field] for field in pitch_data.TRAJECTORY_FIELDS)
    return sum(totals[field] for field in pitch_data.SPRAY_FIELDS)


def pitch_factors(
    sport_id: int, season: int, league_of: dict[int, int]
) -> dict[int, dict[int, dict[str, float]]]:
    """
    Whiff, called-strike, ground-ball and pull factors, if play-by-play has
    been gathered.

    Same construction as the rest: the home club's games, both sides, here
    against elsewhere. Returns nothing when the season has not been fetched,
    since these components are optional rather than required.
    """
    games = pitch_data.load_cached(sport_id, season)
    if not games:
        return {}

    home_of = home_team_by_game(sport_id, season)
    at_home, on_road = pitch_data.by_club(games, home_of)

    by_league: dict[int, dict[int, dict[str, float]]] = defaultdict(dict)
    for club, home_totals in at_home.items():
        road_totals = on_road.get(club)
        if not road_totals:
            continue
        home_rates = pitch_data.rates(home_totals)
        road_rates = pitch_data.rates(road_totals)
        components = {}
        for component in PITCH_COMPONENTS:
            home_rate, road_rate = home_rates[component], road_rates[component]
            if not home_rate or not road_rate:
                continue
            components[component] = _regress(
                home_rate / road_rate, _pitch_sample(component, home_totals)
            )
        if components:
            by_league[league_of.get(club, 0)][club] = components

    for parks in by_league.values():
        for component in PITCH_COMPONENTS:
            values = [p[component] for p in parks.values() if component in p]
            mean = sum(values) / len(values) if values else 1.0
            if mean > 0:
                for park_components in parks.values():
                    if component in park_components:
                        park_components[component] /= mean
    return by_league


def build(sport_id: int, season: int) -> dict[int, dict[int, dict[str, float]]]:
    collected = collect(sport_id, season)
    by_league = factors(collected)

    league_of = {club: data["league_id"] for club, data in collected.items()}
    for league_id, parks in pitch_factors(sport_id, season, league_of).items():
        for club, components in parks.items():
            if club in by_league.get(league_id, {}):
                by_league[league_id][club].update(components)
    return by_league
