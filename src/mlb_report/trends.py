from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .models import GameLog


@dataclass(frozen=True)
class Trend:
    player_id: int
    player_name: str
    headline: str


def _chronological(logs: list[GameLog]) -> list[GameLog]:
    return sorted(logs, key=lambda log: (log.game_date, log.game_pk))


def hit_streak(logs: list[GameLog]) -> int:
    """Games with at least one hit, counting back from the most recent."""
    streak = 0
    for log in reversed(_chronological(logs)):
        if log.count("atBats") == 0 and log.count("hits") == 0:
            continue  # a pinch-run or defensive appearance breaks nothing
        if log.count("hits") == 0:
            break
        streak += 1
    return streak


def scoreless_outings(logs: list[GameLog]) -> int:
    streak = 0
    for log in reversed(_chronological(logs)):
        if log.count("earnedRuns") > 0 or log.innings_pitched == 0:
            break
        streak += 1
    return streak


def window(logs: list[GameLog], days: int, as_of: date) -> list[GameLog]:
    cutoff = as_of - timedelta(days=days - 1)
    return [log for log in logs if cutoff <= log.game_date <= as_of]


def rolling_hitting(logs: list[GameLog]) -> dict:
    """Aggregate slash line over a set of hitting logs."""
    totals = {
        key: sum(log.count(key) for log in logs)
        for key in (
            "atBats",
            "hits",
            "doubles",
            "triples",
            "homeRuns",
            "baseOnBalls",
            "hitByPitch",
            "sacFlies",
            "plateAppearances",
            "rbi",
            "stolenBases",
            "strikeOuts",
        )
    }
    at_bats = totals["atBats"]
    singles = (
        totals["hits"] - totals["doubles"] - totals["triples"] - totals["homeRuns"]
    )
    total_bases = (
        singles + 2 * totals["doubles"] + 3 * totals["triples"] + 4 * totals["homeRuns"]
    )
    on_base_chances = (
        at_bats + totals["baseOnBalls"] + totals["hitByPitch"] + totals["sacFlies"]
    )
    reached = totals["hits"] + totals["baseOnBalls"] + totals["hitByPitch"]

    average = totals["hits"] / at_bats if at_bats else 0.0
    obp = reached / on_base_chances if on_base_chances else 0.0
    slg = total_bases / at_bats if at_bats else 0.0
    return {
        **totals,
        "avg": average,
        "obp": obp,
        "slg": slg,
        "ops": obp + slg,
        "games": len(logs),
    }


def rolling_pitching(logs: list[GameLog]) -> dict:
    innings = sum(log.innings_pitched for log in logs)
    earned = sum(log.count("earnedRuns") for log in logs)
    return {
        "innings": innings,
        "earnedRuns": earned,
        "strikeOuts": sum(log.count("strikeOuts") for log in logs),
        "baseOnBalls": sum(log.count("baseOnBalls") for log in logs),
        "era": (earned * 9 / innings) if innings else 0.0,
        "games": len(logs),
    }


def _format_slash(line: dict) -> str:
    def trim(value: float) -> str:
        return f"{value:.3f}".lstrip("0")

    return f"{trim(line['avg'])}/{trim(line['obp'])}/{trim(line['slg'])}"


def for_player(
    player_id: str,
    player_name: str,
    logs: list[GameLog],
    as_of: date,
    config: dict,
) -> list[Trend]:
    """
    Whatever is genuinely interesting about a player's recent form.

    Everything here is gated on a configured threshold — a digest that reports
    every rolling split every day is one nobody reads.
    """
    if not logs:
        return []

    found: list[Trend] = []
    is_pitcher = logs[-1].is_pitching

    if is_pitcher:
        streak = scoreless_outings(logs)
        if streak >= config["min_scoreless_outings"]:
            found.append(
                Trend(player_id, player_name, f"{streak} straight scoreless outings")
            )
    else:
        streak = hit_streak(logs)
        if streak >= config["min_hit_streak"]:
            found.append(Trend(player_id, player_name, f"{streak}-game hit streak"))

    for days in config["rolling_windows_days"]:
        recent = window(logs, days, as_of)
        if is_pitcher or not recent:
            continue
        line = rolling_hitting(recent)
        if line["plateAppearances"] < config["min_rolling_plate_appearances"]:
            continue
        if line["ops"] >= config["min_rolling_ops"]:
            found.append(
                Trend(
                    player_id,
                    player_name,
                    f"hot over {days} days: {_format_slash(line)} "
                    f"in {line['plateAppearances']} PA",
                )
            )
            break
        if line["ops"] <= config["max_rolling_ops"]:
            found.append(
                Trend(
                    player_id,
                    player_name,
                    f"cold over {days} days: {_format_slash(line)} "
                    f"in {line['plateAppearances']} PA",
                )
            )
            break
    return found
