"""
Rate stats and skill components.

Pure functions over stat dictionaries: no I/O, no fetching. League context
arrives as an already-computed baseline so the same maths can be pointed at a
season, a date range, or a hypothetical.

Every constant here is documented in docs/METRICS.md, including which are
derived from the data and which are conventions carried over from the majors.
"""

from __future__ import annotations

from dataclasses import dataclass

# wOBA event weights, on the "above zero" scale. The absolute values are
# conventional; what matters is their ratios, because the whole set is rescaled
# per league-season so that league wOBA equals league OBP.
WOBA_WEIGHTS = {
    "walk": 0.69,
    "hitByPitch": 0.72,
    "single": 0.89,
    "double": 1.27,
    "triple": 1.62,
    "homeRun": 2.10,
}

# Linear weights in runs above average. Used for wRAA directly, which avoids
# needing a separate wOBA scale factor.
RUN_VALUES = {
    "walk": 0.33,
    "hitByPitch": 0.36,
    "single": 0.47,
    "double": 0.78,
    "triple": 1.09,
    "homeRun": 1.40,
    "out": -0.27,
}


def _n(stat: dict, key: str) -> float:
    raw = stat.get(key, 0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class Events:
    """The plate-appearance outcomes every rate stat is built from."""

    plate_appearances: float
    at_bats: float
    singles: float
    doubles: float
    triples: float
    home_runs: float
    walks: float
    hit_by_pitch: float
    sac_flies: float
    strikeouts: float

    @property
    def hits(self) -> float:
        return self.singles + self.doubles + self.triples + self.home_runs

    @property
    def outs(self) -> float:
        return self.at_bats - self.hits


def events(stat: dict) -> Events:
    hits = _n(stat, "hits")
    doubles = _n(stat, "doubles")
    triples = _n(stat, "triples")
    home_runs = _n(stat, "homeRuns")
    walks = _n(stat, "baseOnBalls") - _n(stat, "intentionalWalks")
    return Events(
        plate_appearances=_n(stat, "plateAppearances"),
        at_bats=_n(stat, "atBats"),
        singles=hits - doubles - triples - home_runs,
        doubles=doubles,
        triples=triples,
        home_runs=home_runs,
        walks=max(walks, 0.0),
        hit_by_pitch=_n(stat, "hitByPitch"),
        sac_flies=_n(stat, "sacFlies"),
        strikeouts=_n(stat, "strikeOuts"),
    )


def raw_woba(ev: Events) -> float:
    """wOBA before the per-league rescaling that puts it on the OBP scale."""
    chances = ev.at_bats + ev.walks + ev.hit_by_pitch + ev.sac_flies
    if chances <= 0:
        return 0.0
    numerator = (
        WOBA_WEIGHTS["walk"] * ev.walks
        + WOBA_WEIGHTS["hitByPitch"] * ev.hit_by_pitch
        + WOBA_WEIGHTS["single"] * ev.singles
        + WOBA_WEIGHTS["double"] * ev.doubles
        + WOBA_WEIGHTS["triple"] * ev.triples
        + WOBA_WEIGHTS["homeRun"] * ev.home_runs
    )
    return numerator / chances


def on_base_percentage(ev: Events) -> float:
    chances = ev.at_bats + ev.walks + ev.hit_by_pitch + ev.sac_flies
    if chances <= 0:
        return 0.0
    return (ev.hits + ev.walks + ev.hit_by_pitch) / chances


def woba(ev: Events, scale: float) -> float:
    return raw_woba(ev) * scale


def runs_above_average(ev: Events) -> float:
    """
    Runs above average from linear weights.

    Working in runs directly sidesteps the wOBA scale factor, which cannot be
    derived from these endpoints without play-by-play run expectancy.
    """
    return (
        RUN_VALUES["walk"] * ev.walks
        + RUN_VALUES["hitByPitch"] * ev.hit_by_pitch
        + RUN_VALUES["single"] * ev.singles
        + RUN_VALUES["double"] * ev.doubles
        + RUN_VALUES["triple"] * ev.triples
        + RUN_VALUES["homeRun"] * ev.home_runs
        + RUN_VALUES["out"] * ev.outs
    )


def wrc_plus(
    ev: Events,
    league_runs_per_pa: float,
    league_raa_per_pa: float,
    park_factor: float = 1.0,
) -> float:
    """
    Runs created per PA against the league, indexed so 100 is average.

    The run values are calibrated to major-league scoring, so applying them to
    a minor league leaves a systematic offset. Subtracting the league's own
    average removes it, which is what guarantees that a league-average line
    indexes to exactly 100 at every level.

    The park factor divides, so a hitter's park drags his index down.
    """
    if ev.plate_appearances <= 0 or league_runs_per_pa <= 0:
        return 0.0
    relative = runs_above_average(ev) / ev.plate_appearances - league_raa_per_pa
    return 100 * (relative + league_runs_per_pa) / (park_factor * league_runs_per_pa)


def innings(stat: dict) -> float:
    """
    Innings pitched as a number, reading the box-score fraction correctly.

    "74.1" means 74 innings and one out, not 74 and a tenth. Casting it straight
    to a float understates the workload by up to two thirds of an inning, which
    flows into every rate divided by it.
    """
    raw = str(stat.get("inningsPitched", "") or "").strip()
    if not raw:
        return 0.0
    whole, _, outs = raw.partition(".")
    try:
        total = float(whole or 0)
    except ValueError:
        return 0.0
    if outs in ("1", "2"):
        total += int(outs) / 3
    return total


def earned_run_average(stat: dict) -> float | None:
    pitched = innings(stat)
    if pitched <= 0:
        return None
    return 9 * _n(stat, "earnedRuns") / pitched


def fip_constant(league_era: float, league_stat: dict) -> float:
    """Solved per league-season so that league FIP equals league ERA."""
    innings = _n(league_stat, "inningsPitched")
    if innings <= 0:
        return 3.10
    raw = (
        13 * _n(league_stat, "homeRuns")
        + 3 * (_n(league_stat, "baseOnBalls") + _n(league_stat, "hitByPitch"))
        - 2 * _n(league_stat, "strikeOuts")
    ) / innings
    return league_era - raw


def fip(stat: dict, constant: float) -> float:
    pitched = innings(stat)
    if pitched <= 0:
        return 0.0
    raw = (
        13 * _n(stat, "homeRuns")
        + 3 * (_n(stat, "baseOnBalls") + _n(stat, "hitByPitch"))
        - 2 * _n(stat, "strikeOuts")
    ) / pitched
    return raw + constant


def fip_minus(player_fip: float, league_fip: float, park_factor: float = 1.0) -> float:
    """Indexed so 100 is average and lower is better."""
    if league_fip <= 0:
        return 0.0
    return 100 * player_fip / (park_factor * league_fip)


def contact_rate(stat: dict) -> float | None:
    """Share of swings that hit the ball. The closest thing to a bat-to-ball
    skill measure available without Statcast."""
    swings = _n(stat, "totalSwings")
    if swings <= 0:
        return None
    return 1 - _n(stat, "swingAndMisses") / swings


def whiff_rate(stat: dict) -> float | None:
    """
    Share of swings missed, the pitcher's side of the same event.

    Reported rather than strikeout rate because a strikeout also depends on
    called strikes, which parks affect independently of swings and misses.
    """
    swings = _n(stat, "totalSwings")
    if swings <= 0:
        return None
    return _n(stat, "swingAndMisses") / swings


def _opportunities(stat: dict) -> float:
    """
    Plate appearances for a hitter, batters faced for a pitcher.

    The API gives pitchers `battersFaced` and no `plateAppearances`, so a rate
    keyed only on the latter silently returns nothing for every pitcher.
    """
    return _n(stat, "plateAppearances") or _n(stat, "battersFaced")


def strikeout_rate(stat: dict) -> float | None:
    opportunities = _opportunities(stat)
    if opportunities <= 0:
        return None
    return _n(stat, "strikeOuts") / opportunities


def walk_rate(stat: dict) -> float | None:
    opportunities = _opportunities(stat)
    if opportunities <= 0:
        return None
    return _n(stat, "baseOnBalls") / opportunities


def isolated_power(ev: Events) -> float | None:
    if ev.at_bats <= 0:
        return None
    total_bases = ev.singles + 2 * ev.doubles + 3 * ev.triples + 4 * ev.home_runs
    return (total_bases - ev.hits) / ev.at_bats


def solid_contact_rate(stat: dict) -> float | None:
    """
    Line drives and fly balls as a share of balls in play.

    A stand-in for contact quality: with no exit velocity in the minors, the
    batted-ball mix is the only evidence of how hard the ball is being hit.
    """
    in_play = _n(stat, "ballsInPlay")
    if in_play <= 0:
        return None
    hard = (
        _n(stat, "lineHits")
        + _n(stat, "lineOuts")
        + _n(stat, "flyHits")
        + _n(stat, "flyOuts")
    )
    return hard / in_play


def ground_ball_rate(stat: dict) -> float | None:
    """
    Ground balls as a share of batted balls, from play-by-play.

    The season feed carries its own ground-ball counts, hits included, and they
    are self-consistent. Play-by-play is preferred anyway so that one
    definition of a ground ball runs through the whole calculation: the park
    factor this rate is divided by is built from play-by-play trajectories, and
    a rate measured one way cannot be adjusted by a factor measured another.
    """
    batted = _n(stat, "battedBalls")
    if batted <= 0:
        return None
    return _n(stat, "groundBalls") / batted


def pull_rate(stat: dict) -> float | None:
    """
    Batted balls hit to the pull side, as a share of those with a location.

    The counts come from play-by-play rather than the season feed, which has no
    spray fields, and are absent for any player or season not gathered.
    """
    placed = _n(stat, "sprayedBalls")
    if placed <= 0:
        return None
    return _n(stat, "pulledBalls") / placed


def air_rate(stat: dict) -> float | None:
    """
    Batted balls hit in the air, as a share of batted balls.

    The exact complement of the ground-ball rate, and reported instead of it for
    hitters because lift is the half of that pairing power is read from.
    """
    batted = _n(stat, "battedBalls")
    if batted <= 0:
        return None
    return (batted - _n(stat, "groundBalls")) / batted


def home_runs_per_fly_ball(stat: dict) -> float | None:
    """
    Home runs as a share of fly balls.

    Power per opportunity rather than per at-bat, which is what separates a
    hitter who does damage from one who merely gets the ball airborne often.

    The numerator is the season feed's home run count and the denominator a
    play-by-play trajectory count, so the two only agree when the season has
    been gathered in full. Levels gathered partway through would overstate this.
    """
    fly_balls = _n(stat, "flyBalls")
    if fly_balls <= 0:
        return None
    return _n(stat, "homeRuns") / fly_balls


def home_runs_per_nine(stat: dict) -> float | None:
    pitched = innings(stat)
    if pitched <= 0:
        return None
    return 9 * _n(stat, "homeRuns") / pitched


def strikeouts_minus_walks(stat: dict) -> float | None:
    """K-BB%, the most predictive single pitching rate at these sample sizes."""
    faced = _opportunities(stat)
    if faced <= 0:
        return None
    return (_n(stat, "strikeOuts") - _n(stat, "baseOnBalls")) / faced
