"""
Turns a prospect's season into the handful of numbers worth reading.

The digest asks one question of every player: how good is this, for this
league? That means production indexed to the league, the underlying skills as
percentile ranks among his peers, and his age against the level he is at.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import baselines
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
    # None for a rate, which is rendered as a percentage. Anything else is
    # reported in the unit it was measured in.
    unit: str | None = None


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
    # Level and club together, e.g. "AA Arkansas Travelers". The level alone
    # stops identifying a stint the moment a player is traded without moving up.
    where: str = ""

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


# Metrics are named for what they are rather than for the virtue they imply. A
# reader who knows the game can tell what a 4% walk rate means without being
# told it is "command", and one who does not is better served by a number he can
# look up than by a word he cannot.
#
# A trailing arrow marks a rate whose bar is inverted, so that a long bar always
# means good and the label always says which direction is the good one.
def _pitching_season(stat: dict, player_fip: float) -> str:
    """
    A pitcher's season the way a box score would give it, then FIP.

    The counting line comes first because it is what happened, and ERA and FIP
    follow as two readings of it: what the runs say, and what the strikeouts,
    walks and home runs say they should have been.
    """
    def count(key: str) -> int:
        try:
            return int(float(stat.get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0

    parts = [
        f"{stat.get('inningsPitched', '0.0')} IP",
        f"{count('runs')} R",
        f"{count('homeRuns')} HR",
        f"{count('strikeOuts')} K",
        f"{count('baseOnBalls')} BB",
    ]
    era = sm.earned_run_average(stat)
    if era is not None:
        parts.append(f"{era:.2f} ERA")
    parts.append(f"{player_fip:.2f} FIP")
    return ", ".join(parts)


SKILL_LABELS = {
    "contact": "Contact%",
    "home_runs_per_fly": "HR/FB",
    "air": "Air%",
    "pull": "Pull%",
    "discipline": "BB%",
    # Whiffs per swing, not per pitch: naming it SwStr% would promise a stat
    # around 11% and then show one around 35%.
    "contact_suppression": "Whiff%",
    "damage_limitation": "GB%",
    "command": "BB%",
    "chase": "Chase%",
    "exit_velocity": "EV",
}

# Every skill is a rate read as a percentage except the one that is measured
# rather than counted, which is a speed and has to say so.
SKILL_UNITS = {"exit_velocity": "mph"}

# Bat-to-ball, then damage, then batted-ball shape and direction, then the
# plate. Exit velocity leads the damage group because it is the only measured
# member of it: HR/FB, air and pull describe how a hitter goes about doing
# damage, and the speed off the bat is whether he actually did any.
#
# Chase and exit velocity are listed for every level but only exist at Triple-A,
# where the parks track pitch location and ball speed. Below it neither has a
# value, and a skill without one is dropped when the line is rendered — so a
# Triple-A player shows seven bars and everyone under him shows five, without
# either side needing to know which level it is.
HEADLINE_SKILLS = {
    # Chasing sits with the walk rate rather than with the bat, because for a
    # hitter it is the same skill read a pitch earlier: what he offered at is
    # why he walked or did not.
    "hitting": (
        "contact",
        "exit_velocity",
        "home_runs_per_fly",
        "air",
        "pull",
        "discipline",
        "chase",
    ),
    # For a pitcher the same rate belongs beside the whiff, since drawing a
    # chase and missing the bat are two results of the same pitch.
    "pitching": (
        "contact_suppression",
        "chase",
        "exit_velocity",
        "home_runs_per_fly",
        "damage_limitation",
        "pull",
        "command",
    ),
}

INVERTED_MARK = "\u2193"

# Between one skill and the next on a rendered line.
SKILL_SEPARATOR = " \u00b7 "


def evaluate(
    player: PlayerSeason,
    baseline: LeagueBaseline,
    minimum_sample: int,
    park_factor: float = 1.0,
    park_components: dict[str, float] | None = None,
) -> Evaluation:
    is_pitcher = player.group == "pitching"
    metrics = PITCHING_METRICS if is_pitcher else HITTING_METRICS
    inverted = INVERTED_METRICS[player.group]
    events = player.events

    sample = int(
        float(player.stat.get("battersFaced", 0))
        if is_pitcher
        else events.plate_appearances
    )

    def rank(name: str) -> Skill:
        observed = metrics[name](player.stat)
        # Ranked on the park-adjusted value, using the same factor the league
        # distribution was built from, or the comparison is between different
        # things. Reported as the observed rate, because that is what actually
        # happened and is the number a reader can check anywhere else.
        adjusted = observed
        if park_components is not None:
            adjusted = baselines.park_adjust(observed, name, park_components)
        percentile = baseline.percentile(name, adjusted)
        label = SKILL_LABELS[name]
        if name in inverted:
            label += INVERTED_MARK
            if percentile is not None:
                percentile = 100 - percentile
        if percentile is not None:
            # A rank against a finite league can land on either end, and both
            # ends read as nonsense: nobody is in the hundredth percentile, and
            # "0th" looks like a missing number rather than a last place.
            percentile = min(99, max(1, percentile))
        return Skill(label, percentile, observed, unit=SKILL_UNITS.get(name))

    skills: list[Skill] = []
    if sample >= minimum_sample:
        # Below the sample floor a percentile is noise dressed up as insight,
        # so no skill line is produced at all.
        # A metric the level does not measure is not a skill he lacks, so it is
        # dropped rather than carried as a blank. This is what leaves a
        # Triple-A player with seven bars and everyone below him with five.
        skills = [
            skill
            for skill in (rank(name) for name in HEADLINE_SKILLS[player.group])
            if skill.value is not None
        ]
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
        slash = _pitching_season(player.stat, player_fip)
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
        where=_where(player),
    )


def _where(player: PlayerSeason) -> str:
    """Level and club together, which is what actually identifies a stint."""
    return " ".join(part for part in (player.level, player.team_name) if part)


def _sample_of(player: PlayerSeason) -> float:
    stat = player.stat
    return float(stat.get("plateAppearances", 0) or stat.get("battersFaced", 0) or 0)


def split_stints(
    stints: list[PlayerSeason], current_level: str | None
) -> tuple[PlayerSeason, list[PlayerSeason]]:
    """
    Separate where a player is now from everywhere he has been.

    The level of his most recent game decides which stint is current, since a
    player promoted in August may still have most of his season's plate
    appearances at the level below.

    Every other stint is kept, largest first, because the one he has left is
    often the better evidence: a hitter called up in July can have three times
    the plate appearances below, and reporting only the most recent of them
    buries his actual season.
    """
    ordered = sorted(stints, key=_sample_of, reverse=True)
    current = next(
        (stint for stint in ordered if stint.level == current_level), ordered[0]
    )
    return current, [stint for stint in ordered if stint is not current]


def age_context(player: PlayerSeason, baseline: LeagueBaseline) -> str | None:
    """
    Where a player is, how old he is, and how that age sits against the level.

    Written as "AA Arkansas, 21yo, TEX -4": three quantities rather than a
    sentence. Negative is young for the level, which is the direction that
    flatters a prospect.

    The club is named alongside the level because the level alone stops
    identifying a stint as soon as a player changes organizations without
    changing level, which is exactly when the reader needs telling apart.

    Age is deliberately kept out of the rate stats. A 20-year-old posting a
    league average line in Double-A is the whole story, and folding age into
    wRC+ would bury exactly the thing worth noticing.
    """
    parts = [_where(player)] if _where(player) else []

    try:
        age: int | None = int(player.stat["age"])
    except (KeyError, TypeError, ValueError):
        age = None

    if age is not None:
        parts.append(f"{age}yo")
        if baseline.average_age is not None:
            gap = round(age - baseline.average_age)
            # A signed zero reads as a mistake rather than "typical for the level".
            relative = f"{gap:+d}" if gap else "0"
            parts.append(f"{baseline.league_name} {relative}")

    return ", ".join(parts) if parts else None


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def render_skills(evaluation: Evaluation) -> str | None:
    """
    Each skill as its name, its actual rate, and where that rate ranks.

    The rate is carried alongside the rank because a percentile alone says a
    player is better than his peers without ever saying at what: 90th in HR/FB
    means one thing in the California League and another in the PCL, and only
    the number itself settles it.
    """
    parts = [
        f"{skill.name} {_measurement(skill)} {_ordinal(skill.percentile)}"
        for skill in evaluation.skills
        if skill.percentile is not None and skill.value is not None
    ]
    return SKILL_SEPARATOR.join(parts) if parts else None


def _measurement(skill: Skill) -> str:
    if skill.unit is None:
        return f"{skill.value * 100:.1f}%"
    return f"{skill.value:.1f} {skill.unit}"


def _full_line(evaluation: Evaluation) -> str:
    # A pitcher's line already opens with his innings, which is the sample; a
    # batters-faced count on the end would only say it again less clearly.
    if evaluation.is_pitcher:
        return (
            f"{evaluation.slash}, {evaluation.production:.0f} "
            f"{evaluation.production_label}"
        )
    return (
        f"{evaluation.slash}, {evaluation.production:.0f} "
        f"{evaluation.production_label} in {evaluation.sample} PA"
    )


def render_production(evaluation: Evaluation) -> str | None:
    """
    The current stint, with no level on it.

    The header above already says where he is, and saying it twice in two lines
    reads as a stutter.
    """
    if evaluation.production is None:
        return None
    return _full_line(evaluation)


def render_prior(evaluation: Evaluation) -> str | None:
    """
    The level a player came from, at the same depth as where he is now.

    A promotion is exactly the case where the previous stint is the larger body
    of evidence — a hitter called up in July can have twice the plate
    appearances below — so abbreviating it buries the better sample.
    """
    if evaluation.production is None:
        return None
    where = evaluation.where or evaluation.level
    league = evaluation.league_name
    # Complex-league clubs are named for their league — "ACL Mariners" — so
    # appending it would read "ROK ACL Mariners (ACL)".
    suffix = f" ({league})" if league and league not in where else ""
    return f"Before that at {where}{suffix}: {_full_line(evaluation)}"
