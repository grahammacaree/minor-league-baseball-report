"""
Turns a prospect's season into the handful of numbers worth reading.

The digest asks one question of every player: how good is this, for this
league? That means production indexed to the league, the underlying skills as
percentile ranks among his peers, and his age against the level he is at.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import sabermetrics as sm
from .baselines import (
    HITTING_METRICS,
    INVERTED_METRICS,
    PITCHING_METRICS,
    LeagueBaseline,
    PlayerSeason,
)


@dataclass(frozen=True)
class Skill:
    name: str
    percentile: int | None
    value: float | None


@dataclass(frozen=True)
class Evaluation:
    player_id: int
    level: str
    league_name: str
    sample: int
    production: float | None  # wRC+ for hitters, FIP- for pitchers
    production_label: str
    slash: str | None
    skills: list[Skill]
    is_pitcher: bool

    @property
    def has_enough_sample(self) -> bool:
        return self.production is not None


def _format_rate(value: float) -> str:
    return f"{value:.3f}".lstrip("0")


def _slash_line(events: sm.Events, woba: float) -> str:
    average = events.hits / events.at_bats if events.at_bats else 0.0
    on_base = sm.on_base_percentage(events)
    total_bases = (
        events.singles + 2 * events.doubles + 3 * events.triples + 4 * events.home_runs
    )
    slugging = total_bases / events.at_bats if events.at_bats else 0.0
    return (
        f"{_format_rate(average)}/{_format_rate(on_base)}/{_format_rate(slugging)}, "
        f"{_format_rate(woba)} wOBA"
    )


SKILL_LABELS = {
    "contact": "Contact",
    "power": "Power",
    "discipline": "Discipline",
    "contact_suppression": "Whiffs",
    "damage_limitation": "Grounders",
    "command": "Command",
}

HEADLINE_SKILLS = {
    "hitting": ("contact", "power", "discipline"),
    "pitching": ("contact_suppression", "damage_limitation", "command"),
}


def evaluate(
    player: PlayerSeason,
    baseline: LeagueBaseline,
    minimum_sample: int,
    park_factor: float = 1.0,
) -> Evaluation:
    is_pitcher = player.group == "pitching"
    metrics = PITCHING_METRICS if is_pitcher else HITTING_METRICS
    events = player.events

    sample = int(
        float(player.stat.get("battersFaced", 0))
        if is_pitcher
        else events.plate_appearances
    )

    skills = []
    if sample >= minimum_sample:
        # Below the sample floor a percentile is noise dressed up as insight,
        # so no skill line is produced at all.
        for name in HEADLINE_SKILLS[player.group]:
            value = metrics[name](player.stat)
            percentile = baseline.percentile(name, value)
            if percentile is not None and name in INVERTED_METRICS:
                percentile = 100 - percentile
            skills.append(Skill(SKILL_LABELS[name], percentile, value))
    else:
        return Evaluation(
            player_id=player.player_id,
            level=player.level,
            league_name=baseline.league_name,
            sample=sample,
            production=None,
            production_label="FIP-" if is_pitcher else "wRC+",
            slash=None,
            skills=skills,
            is_pitcher=is_pitcher,
        )

    if is_pitcher:
        player_fip = sm.fip(player.stat, baseline.fip_constant)
        production = sm.fip_minus(player_fip, baseline.league_fip, park_factor)
        slash = f"{player_fip:.2f} FIP"
    else:
        production = sm.wrc_plus(
            events, baseline.runs_per_pa, baseline.raa_per_pa, park_factor
        )
        slash = _slash_line(events, sm.woba(events, baseline.woba_scale))

    return Evaluation(
        player_id=player.player_id,
        level=player.level,
        league_name=baseline.league_name,
        sample=sample,
        production=production,
        production_label="FIP-" if is_pitcher else "wRC+",
        slash=slash,
        skills=skills,
        is_pitcher=is_pitcher,
    )


def _sample_of(player: PlayerSeason) -> float:
    stat = player.stat
    return float(stat.get("plateAppearances", 0) or stat.get("battersFaced", 0) or 0)


def split_stints(
    stints: list[PlayerSeason], current_level: str | None
) -> tuple[PlayerSeason, PlayerSeason | None]:
    """
    Separate where a player is now from where he was.

    The level of his most recent game decides which stint is current, since a
    player promoted in August may still have most of his season's plate
    appearances at the level below.
    """
    ordered = sorted(stints, key=_sample_of, reverse=True)
    current = next(
        (stint for stint in ordered if stint.level == current_level), ordered[0]
    )
    others = [stint for stint in ordered if stint is not current]
    return current, (others[0] if others else None)


def age_context(player: PlayerSeason, baseline: LeagueBaseline) -> str | None:
    """
    A player's age against his league's average.

    Deliberately kept out of the rate stats. A 20-year-old posting a league
    average line in Double-A is the whole story, and folding age into wRC+
    would bury exactly the thing worth noticing.
    """
    raw_age = player.stat.get("age")
    if raw_age is None or baseline.average_age is None:
        return None
    try:
        age = int(raw_age)
    except (TypeError, ValueError):
        return None

    gap = baseline.average_age - age
    if abs(gap) < 1:
        return f"{age}, typical age for the league"
    years = "year" if round(abs(gap)) == 1 else "years"
    direction = "young for" if gap > 0 else "old for"
    return f"{age}, {round(abs(gap))} {years} {direction} the {baseline.league_name}"


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def render_skills(evaluation: Evaluation) -> str | None:
    parts = [
        f"{skill.name} {_ordinal(skill.percentile)}"
        for skill in evaluation.skills
        if skill.percentile is not None
    ]
    return " · ".join(parts) if parts else None


def render_production(evaluation: Evaluation) -> str | None:
    if evaluation.production is None:
        return None
    unit = "BF" if evaluation.is_pitcher else "PA"
    return (
        f"{evaluation.level} ({evaluation.league_name}): {evaluation.slash}, "
        f"{evaluation.production:.0f} {evaluation.production_label} "
        f"in {evaluation.sample} {unit}"
    )


def render_prior(evaluation: Evaluation) -> str | None:
    """The level a player came from, so a promotion carries its own context."""
    if evaluation.production is None:
        return None
    unit = "BF" if evaluation.is_pitcher else "PA"
    return (
        f"Before that at {evaluation.level}: {evaluation.production:.0f} "
        f"{evaluation.production_label} in {evaluation.sample} {unit}"
    )
