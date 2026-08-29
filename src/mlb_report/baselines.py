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

from . import sabermetrics as sm
from . import statsapi
from .config_loader import user_data_dir

# Bump whenever the cached shape changes, so stale files are refetched.
_CACHE_SCHEMA = 2

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


def _merge_pool(
    season_rows: list[dict], advanced_rows: list[dict], group: str
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
    pool = []
    for row in season_rows:
        player = row.get("player", {})
        league = row.get("league", {})
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
                team_id=row.get("team", {}).get("id", 0),
            )
        )
    return pool


def fetch_pool(sport_id: int, season: int, group: str) -> list[PlayerSeason]:
    season_rows = statsapi.stats_leaderboard("season", group, sport_id, season)
    advanced_rows = statsapi.stats_leaderboard(
        "seasonAdvanced", group, sport_id, season
    )
    return _merge_pool(season_rows, advanced_rows, group)


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
                return [PlayerSeason(**row) for row in cached["players"]]
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


HITTING_METRICS = {
    "contact": sm.contact_rate,
    "power": lambda stat: sm.isolated_power(sm.events(stat)),
    "discipline": sm.walk_rate,
    "solid_contact": sm.solid_contact_rate,
    "strikeout_rate": sm.strikeout_rate,
}

PITCHING_METRICS = {
    "contact_suppression": lambda stat: sm.strikeout_rate(stat),
    "damage_limitation": lambda stat: sm.ground_ball_rate(stat),
    "command": lambda stat: sm.walk_rate(stat),
    "strikeouts_minus_walks": sm.strikeouts_minus_walks,
}

# Lower is better, so the percentile is inverted before it is reported.
INVERTED_METRICS = {"strikeout_rate", "command"}


def build(
    pool: list[PlayerSeason], group: str, minimum_sample: int
) -> dict[int, LeagueBaseline]:
    """One baseline per league represented in the pool."""
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
            innings = totals.get("inningsPitched", 0.0)
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
            values = sorted(
                value
                for value in (metric(player.stat) for player in qualified)
                if value is not None
            )
            baseline.distributions[name] = values
        baselines[league_id] = baseline
    return baselines
