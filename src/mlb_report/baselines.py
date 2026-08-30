"""
League context: run environments and skill distributions.

A prospect's numbers only mean something against the league he is playing in,
and the leagues differ sharply — the Pacific Coast League is not the Texas
League. Baselines are therefore built per league rather than per level.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from . import pitch_data, statsapi
from . import sabermetrics as sm
from .config_loader import user_data_dir


class ParkLookup(Protocol):
    def for_team(self, team_id: int | None) -> dict[str, float]: ...


# Bump whenever the cached shape changes, so stale files are refetched.
_CACHE_SCHEMA = 4

_STAT_KEYS = (
    "age",
    "runs",
    "plateAppearances",
    "atBats",
    "hits",
    "doubles",
    "triples",
    "homeRuns",
    "baseOnBalls",
    "intentionalWalks",
    "hitByPitch",
    "sacFlies",
    "strikeOuts",
    "battersFaced",
    "earnedRuns",
    "inningsPitched",
    "totalSwings",
    "swingAndMisses",
    "ballsInPlay",
    "lineHits",
    "lineOuts",
    "flyHits",
    "flyOuts",
    "groundHits",
    "groundOuts",
    "popHits",
    "popOuts",
)


@dataclass(frozen=True)
class PlayerSeason:
    player_id: int
    name: str
    league_id: int
    league_name: str
    level: str
    group: str
    stat: dict = field(repr=False)
    team_id: int = 0
    # The level this row's stats were earned at, as a sport id, so play-by-play
    # gathered per level can be matched to the right stint of a season.
    sport_id: int = 0
    # The club, which the level alone does not identify. A player who changes
    # organizations mid-season can have two stints at the same level, and
    # "AA" twice over says nothing about which is which.
    team_name: str = ""

    @property
    def events(self) -> sm.Events:
        return sm.events(self.stat)


@dataclass
class LeagueBaseline:
    """Everything needed to index one league's players against their peers."""

    league_id: int
    league_name: str
    group: str
    runs_per_pa: float = 0.0
    raa_per_pa: float = 0.0
    woba_scale: float = 1.0
    league_woba: float = 0.0
    league_fip: float = 0.0
    fip_constant: float = 3.10
    average_age: float | None = None
    distributions: dict[str, list[float]] = field(default_factory=dict, repr=False)

    def percentile(self, metric: str, value: float | None) -> int | None:
        """
        Where a value falls among qualified players in the same league.

        Returns None rather than a misleading number when the metric could not
        be computed or the league pool is too small to rank against.
        """
        if value is None:
            return None
        sorted_values = self.distributions.get(metric)
        if not sorted_values or len(sorted_values) < 20:
            return None
        position = bisect_left(sorted_values, value)
        return round(100 * position / len(sorted_values))


@dataclass
class BlendedBaseline(LeagueBaseline):
    """
    One yardstick for a player measured against two leagues.

    A player traded within a level has a single line covering time in two
    leagues, and ranking all of it against either one is wrong in whichever
    direction that league is the easier. Rather than splitting the line, the
    comparison is blended: he is ranked in each league he played in, and those
    ranks averaged by how much of his season each accounts for.

    Averaging the ranks rather than pooling the two leagues' players is the
    faithful reading. It says he was in the sixtieth percentile of one league
    for half a season and the seventieth of the other for the rest, which is
    what actually happened.
    """

    parts: list[tuple[LeagueBaseline, float]] = field(default_factory=list, repr=False)

    def percentile(self, metric: str, value: float | None) -> int | None:
        ranks = [
            (part.percentile(metric, value), weight) for part, weight in self.parts
        ]
        usable = [(rank, weight) for rank, weight in ranks if rank is not None]
        total = sum(weight for _, weight in usable)
        if not total:
            return None
        return round(sum(rank * weight for rank, weight in usable) / total)


def blend(parts: list[tuple[LeagueBaseline, float]]) -> LeagueBaseline:
    """
    Weigh two leagues' baselines by how much of a season each accounts for.

    The constants behind wRC+ and FIP- describe a run environment, so a season
    split across two of them was played in neither and is fairly measured
    against the mix.
    """
    usable = [(part, weight) for part, weight in parts if weight > 0]
    if len(usable) == 1:
        return usable[0][0]
    if not usable:
        raise ValueError("nothing to blend")

    total = sum(weight for _, weight in usable)

    def mean(read) -> float:
        return sum(read(part) * weight for part, weight in usable) / total

    ages = [(part, weight) for part, weight in usable if part.average_age is not None]
    first = usable[0][0]
    return BlendedBaseline(
        league_id=first.league_id,
        # Both leagues are named, since the reader is being told what the
        # percentiles beneath were measured against.
        league_name="/".join(dict.fromkeys(part.league_name for part, _ in usable)),
        group=first.group,
        runs_per_pa=mean(lambda p: p.runs_per_pa),
        raa_per_pa=mean(lambda p: p.raa_per_pa),
        woba_scale=mean(lambda p: p.woba_scale),
        league_woba=mean(lambda p: p.league_woba),
        league_fip=mean(lambda p: p.league_fip),
        fip_constant=mean(lambda p: p.fip_constant),
        average_age=(
            sum(part.average_age * weight for part, weight in ages)
            / sum(weight for _, weight in ages)
            if ages
            else None
        ),
        parts=usable,
    )


def _merge_pool(
    season_rows: list[dict],
    advanced_rows: list[dict],
    group: str,
    short_names: dict[int, str] | None = None,
) -> list[PlayerSeason]:
    """
    Join the standard and advanced leaderboards for one level.

    Neither alone is sufficient: counting stats for wOBA come from the standard
    feed, while swings, whiffs and batted-ball types only exist on the advanced
    one.
    """
    advanced_by_player = {
        row["player"]["id"]: row.get("stat", {}) for row in advanced_rows
    }
    short_names = short_names or {}
    pool = []
    for row in season_rows:
        player = row.get("player", {})
        league = row.get("league", {})
        team = row.get("team", {})
        merged = {**row.get("stat", {}), **advanced_by_player.get(player.get("id"), {})}
        pool.append(
            PlayerSeason(
                player_id=player.get("id", 0),
                name=player.get("fullName", ""),
                league_id=league.get("id", 0),
                league_name=league.get("name", ""),
                level=row.get("sport", {}).get("abbreviation", ""),
                group=group,
                stat={key: merged[key] for key in _STAT_KEYS if key in merged},
                team_id=team.get("id", 0),
                sport_id=row.get("sport", {}).get("id", 0),
                # "Tacoma" rather than "Tacoma Rainiers": the club is being
                # named to tell two stints apart, not introduced.
                team_name=short_names.get(team.get("id", 0), team.get("name", "")),
            )
        )
    return pool


def fetch_pool(sport_id: int, season: int, group: str) -> list[PlayerSeason]:
    season_rows = statsapi.stats_leaderboard("season", group, sport_id, season)
    advanced_rows = statsapi.stats_leaderboard(
        "seasonAdvanced", group, sport_id, season
    )
    return _merge_pool(
        season_rows, advanced_rows, group, statsapi.team_short_names(sport_id, season)
    )


def _cache_path(season: int, group: str) -> object:
    return user_data_dir() / f"pool_{season}_{group}.json"


def load_pools(
    sport_ids: tuple[int, ...], season: int, group: str, as_of: date
) -> list[PlayerSeason]:
    """
    Every player at the given levels, cached for the day.

    League distributions move slowly and the leaderboards are large, so one
    fetch per day is plenty.
    """
    path = _cache_path(season, group)
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            fresh = cached.get("fetched") == as_of.isoformat()
            # A cache written before a field existed would silently read back
            # as the default, which is how a park factor lookup quietly turns
            # neutral. Version it so shape changes force a refetch.
            if fresh and cached.get("schema") == _CACHE_SCHEMA:
                pool = [PlayerSeason(**row) for row in cached["players"]]
                return _with_batted_ball(pool, sport_ids, season, group)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    pool: list[PlayerSeason] = []
    for sport_id in sport_ids:
        pool.extend(fetch_pool(sport_id, season, group))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "fetched": as_of.isoformat(),
                "schema": _CACHE_SCHEMA,
                "players": [player.__dict__ for player in pool],
            }
        ),
        encoding="utf-8",
    )
    return _with_batted_ball(pool, sport_ids, season, group)


def _with_batted_ball(
    pool: list[PlayerSeason], sport_ids: tuple[int, ...], season: int, group: str
) -> list[PlayerSeason]:
    """
    Fold play-by-play batted-ball counts into each player's season line.

    Applied after the day's cache rather than before it, because play-by-play
    for a season in progress keeps arriving: baking a partial count into a
    cached pool would freeze these rates at whatever had been gathered when the
    pool was first written.

    Seasons that have not been gathered simply leave the counts absent, and the
    rates then report nothing rather than zero.

    Counts are kept per level rather than per season. A player promoted in July
    has one row per stint, each carrying that level's home run total, so pooling
    his batted balls across both would divide one level's damage by two levels'
    chances at it.
    """
    side = "pitchers" if group == "pitching" else "batters"
    totals: dict[tuple[int, int], dict[str, int]] = {}
    for sport_id in sport_ids:
        games = pitch_data.load_cached(sport_id, season)
        if not games:
            continue
        for player, counts in pitch_data.by_player(games, side).items():
            running = totals.setdefault(
                (sport_id, player), dict.fromkeys(pitch_data.PLAYER_FIELDS, 0)
            )
            for name, value in counts.items():
                running[name] += value

    for player in pool:
        counts = totals.get((player.sport_id, player.player_id))
        if not counts:
            continue
        # Two denominators, not one: a batted ball is classified by trajectory
        # slightly more often than it is given a landing spot.
        player.stat["groundBalls"] = counts["ground"]
        player.stat["flyBalls"] = counts["fly"]
        player.stat["battedBalls"] = sum(
            counts[field] for field in pitch_data.TRAJECTORY_FIELDS
        )
        player.stat["pulledBalls"] = counts["pull"]
        player.stat["sprayedBalls"] = sum(
            counts[field] for field in pitch_data.SPRAY_FIELDS
        )
        # Absent below Triple-A, where nothing tracks a pitch's location or a
        # ball's speed. Left out of the stat line entirely rather than set to
        # zero, so the rates built on them report nothing instead of a floor.
        if counts.get("out_of_zone"):
            player.stat["pitchesOutOfZone"] = counts["out_of_zone"]
            player.stat["chases"] = counts.get("chases", 0)
        if counts.get("measured"):
            player.stat["measuredBalls"] = counts["measured"]
            player.stat["exitSpeedTotal"] = counts.get("exit_speed_total", 0)
            player.stat["hardHitBalls"] = counts.get("hard_hit", 0)
    return pool


def _sum(pool: list[PlayerSeason], key: str) -> float:
    total = 0.0
    for player in pool:
        raw = player.stat.get(key, 0)
        try:
            total += float(raw)
        except (TypeError, ValueError):
            continue
    return total


def _qualified(
    pool: list[PlayerSeason], group: str, minimum: int
) -> list[PlayerSeason]:
    field_name = "battersFaced" if group == "pitching" else "plateAppearances"
    return [player for player in pool if _sum([player], field_name) >= minimum]


# Power is three rates rather than one. Isolated power answers how much damage
# a hitter did, which the slash line already carries; these answer how he did
# it, and separate the hitter who lifts and pulls without punishing the ball
# from the one who punishes it.
HITTING_METRICS = {
    "contact": sm.contact_rate,
    "home_runs_per_fly": sm.home_runs_per_fly_ball,
    "air": sm.air_rate,
    "pull": sm.pull_rate,
    "discipline": sm.walk_rate,
    "solid_contact": sm.solid_contact_rate,
    "strikeout_rate": sm.strikeout_rate,
    # Measured rather than inferred, and only where a park measures them. A
    # league without tracking produces no distribution for these, so no player
    # in it can be ranked on them and none is.
    "chase": sm.chase_rate,
    "exit_velocity": sm.average_exit_velocity,
}

# The pitching side mirrors it, one metric at a time: whiffs against contact,
# home runs per fly against the same, ground balls in place of air since one is
# the complement of the other, pull against pull, walks against walks.
PITCHING_METRICS = {
    "contact_suppression": sm.whiff_rate,
    "home_runs_per_fly": sm.home_runs_per_fly_ball,
    "damage_limitation": lambda stat: sm.ground_ball_rate(stat),
    "pull": sm.pull_rate,
    "command": lambda stat: sm.walk_rate(stat),
    "strikeouts_minus_walks": sm.strikeouts_minus_walks,
    # Read from the other end: the chases a pitcher drew, and how hard he was
    # hit. Both are the same measurement as the hitter's, pointing the other way.
    "chase": sm.chase_rate,
    "exit_velocity": sm.average_exit_velocity,
}

# Lower is better, so the percentile is inverted before it is reported. Keyed by
# group because the same metric can point either way: lifting and pulling is how
# a hitter does damage and therefore the direction that flatters him, while the
# same contact allowed is the pitcher's problem.
INVERTED_METRICS = {
    # Chasing is the hitter's mistake and the pitcher's achievement, and being
    # hit hard is the pitcher's problem and the hitter's whole purpose, so both
    # metrics point opposite ways on the two sides.
    "hitting": {"strikeout_rate", "chase"},
    "pitching": {"command", "home_runs_per_fly", "pull", "exit_velocity"},
}


# Which park component each skill is measured against. A rate is adjusted by
# the park's effect on that same rate rather than on a proxy for it: bat-to-ball
# skill goes against whiffs, not strikeouts, because a strikeout also carries a
# called strike, and parks move the two independently of each other.
METRIC_COMPONENTS = {
    "contact": "whiffs",
    "home_runs_per_fly": "home_runs",
    # The air rate is one minus the ground-ball rate, so the park's effect on it
    # is the ground-ball factor turned over.
    "air": "ground_balls",
    # Walks are adjusted by the park's measured effect on walks. The
    # called-strike factor describes the mechanism but tracks the outcome only
    # weakly and inconsistently (-0.08, -0.37, -0.33 across three levels), so
    # substituting it for the direct measurement would trade signal for noise.
    "discipline": "walks",
    "solid_contact": "hits_in_play",
    "strikeout_rate": "strikeouts",
    "contact_suppression": "whiffs",
    "damage_limitation": "hits_in_play",
    "command": "walks",
    "strikeouts_minus_walks": "strikeouts",
    "pull": "pull",
    # Each against its own measurement rather than a proxy: a park where
    # hitters chase more and one where the ball leaves the bat harder are
    # different parks, and the two effects are only loosely related.
    "chase": "chases",
    "exit_velocity": "exit_speed",
}

# A park that inflates whiffs deflates contact, and one that inflates ground
# balls deflates air, so those factors are flipped before they are applied.
# Every other pairing moves in the same direction.
INVERSE_OF_COMPONENT = {"contact", "air"}


def park_adjust(
    value: float | None, metric: str, factor: dict[str, float]
) -> float | None:
    """
    Divide a rate by its park's effect on that component, at half strength.

    Half, because roughly half a player's games are on the road.
    """
    if value is None:
        return None
    component = METRIC_COMPONENTS.get(metric)
    if component is None:
        return value
    raw = factor.get(component, 1.0)
    if metric in INVERSE_OF_COMPONENT:
        raw = 1 / raw if raw else 1.0
    return value / ((raw + 1.0) / 2)


def build(
    pool: list[PlayerSeason],
    group: str,
    minimum_sample: int,
    parks: ParkLookup | None = None,
) -> dict[int, LeagueBaseline]:
    """
    One baseline per league represented in the pool.

    When park factors are supplied the whole league is ranked on adjusted
    values. Adjusting one player and looking him up in an unadjusted
    distribution would double-count, crediting him for his park while his peers
    are still measured with theirs baked in.
    """
    metrics = PITCHING_METRICS if group == "pitching" else HITTING_METRICS
    by_league: dict[int, list[PlayerSeason]] = {}
    for player in pool:
        by_league.setdefault(player.league_id, []).append(player)

    baselines = {}
    for league_id, players in by_league.items():
        baseline = LeagueBaseline(
            league_id=league_id,
            league_name=players[0].league_name,
            group=group,
        )
        totals = {key: _sum(players, key) for key in _STAT_KEYS}
        league_events = sm.events(totals)

        if group == "hitting":
            plate_appearances = league_events.plate_appearances
            if plate_appearances > 0:
                baseline.runs_per_pa = totals.get("runs", 0.0) / plate_appearances
                baseline.raa_per_pa = (
                    sm.runs_above_average(league_events) / plate_appearances
                )
            raw = sm.raw_woba(league_events)
            obp = sm.on_base_percentage(league_events)
            baseline.woba_scale = obp / raw if raw > 0 else 1.0
            baseline.league_woba = obp
        else:
            # Summed through the box-score reader rather than added as raw
            # floats: ".1" is one out, and adding a third of an inning as a
            # tenth across a whole league drifts by hundreds of innings.
            innings = sum(sm.innings(player.stat) for player in players)
            totals["inningsPitched"] = innings
            era = 9 * totals.get("earnedRuns", 0.0) / innings if innings else 0.0
            baseline.fip_constant = sm.fip_constant(era, totals)
            baseline.league_fip = era

        qualified = _qualified(players, group, minimum_sample)
        ages = [
            float(player.stat["age"])
            for player in qualified
            if str(player.stat.get("age", "")).isdigit()
        ]
        baseline.average_age = sum(ages) / len(ages) if ages else None

        for name, metric in metrics.items():
            values = []
            for player in qualified:
                value = metric(player.stat)
                if parks is not None:
                    value = park_adjust(value, name, parks.for_team(player.team_id))
                if value is not None:
                    values.append(value)
            baseline.distributions[name] = sorted(values)
        baselines[league_id] = baseline
    return baselines
