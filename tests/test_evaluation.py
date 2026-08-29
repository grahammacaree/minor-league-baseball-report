from __future__ import annotations

import pytest

from mlb_report import baselines, evaluation
from mlb_report.baselines import LeagueBaseline, PlayerSeason

BATTED_BALL_KEYS = (
    "battedBalls",
    "groundBalls",
    "flyBalls",
    "sprayedBalls",
    "pulledBalls",
)


def player(level="AA", league_id=109, group="hitting", **stat):
    base = {
        "plateAppearances": 400,
        "atBats": 350,
        "hits": 100,
        "doubles": 20,
        "triples": 2,
        "homeRuns": 15,
        "baseOnBalls": 40,
        "hitByPitch": 5,
        "sacFlies": 3,
        "strikeOuts": 80,
        "totalSwings": 600,
        "swingAndMisses": 120,
        "ballsInPlay": 250,
        "lineHits": 40,
        "lineOuts": 20,
        "flyHits": 20,
        "flyOuts": 40,
        "groundHits": 30,
        "groundOuts": 60,
        "battedBalls": 250,
        "groundBalls": 100,
        "flyBalls": 75,
        "sprayedBalls": 240,
        "pulledBalls": 96,
        "age": 21,
    }
    base.update(stat)
    return PlayerSeason(
        player_id=1,
        name="A Prospect",
        league_id=league_id,
        league_name="TEX",
        level=level,
        group=group,
        stat=base,
    )


def baseline(**overrides):
    values = sorted(i / 100 for i in range(1, 101))
    base = LeagueBaseline(
        league_id=109,
        league_name="TEX",
        group="hitting",
        runs_per_pa=0.12,
        raa_per_pa=0.0,
        woba_scale=1.0,
        league_woba=0.320,
        league_fip=4.00,
        fip_constant=3.10,
        average_age=24.0,
        distributions={
            "contact": values,
            "home_runs_per_fly": values,
            "air": values,
            "discipline": values,
            "contact_suppression": values,
            "damage_limitation": values,
            "command": values,
            "pull": values,
        },
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_a_thin_sample_produces_no_production_or_skills():
    result = evaluation.evaluate(player(plateAppearances=20), baseline(), 50)
    assert result.production is None
    assert result.skills == []
    assert evaluation.render_production(result) is None
    assert evaluation.render_skills(result) is None


def test_a_full_season_is_evaluated():
    """Metrics are named for what they are, not for the virtue they imply."""
    result = evaluation.evaluate(player(), baseline(), 50)
    assert result.production is not None
    assert [skill.name for skill in result.skills] == [
        "Contact%",
        "HR/FB",
        "Air%",
        "Pull%",
        "BB%",
    ]


def test_the_pitching_side_mirrors_the_hitting_side():
    """Ground balls stand in for air, since one is the complement of the other."""
    result = evaluation.evaluate(
        player(group="pitching", battersFaced=400, plateAppearances=0),
        baseline(group="pitching"),
        50,
    )
    assert [skill.name for skill in result.skills] == [
        "Whiff%",
        "HR/FB\u2193",
        "GB%",
        "Pull%\u2193",
        "BB%\u2193",
    ]


def test_percentiles_for_lower_is_better_metrics_are_inverted():
    """A pitcher's walk rate: a low rate should rank high."""
    wild = evaluation.evaluate(
        player(group="pitching", battersFaced=400, baseOnBalls=60, plateAppearances=0),
        baseline(group="pitching"),
        50,
    )
    stingy = evaluation.evaluate(
        player(group="pitching", battersFaced=400, baseOnBalls=8, plateAppearances=0),
        baseline(group="pitching"),
        50,
    )
    walks = {s.name: s.percentile for s in wild.skills}["BB%\u2193"]
    better = {s.name: s.percentile for s in stingy.skills}["BB%\u2193"]
    assert better > walks


def test_the_same_rate_points_opposite_ways_for_the_two_sides():
    """A high HR/FB is a hitter's power and a pitcher's problem."""
    hitter = evaluation.evaluate(player(), baseline(), 50)
    pitcher = evaluation.evaluate(
        player(group="pitching", battersFaced=400, plateAppearances=0),
        baseline(group="pitching"),
        50,
    )
    batting = {s.name: s.percentile for s in hitter.skills}["HR/FB"]
    pitching = {s.name: s.percentile for s in pitcher.skills}["HR/FB\u2193"]
    assert batting == 100 - pitching


def test_a_small_league_pool_yields_no_percentile():
    thin = baseline(distributions={"contact": [0.7, 0.8]})
    result = evaluation.evaluate(player(), thin, 50)
    assert {s.name: s.percentile for s in result.skills}["Contact%"] is None


def test_age_context_reads_relative_to_the_league():
    """Negative is young for the level, the direction that flatters a prospect."""
    assert evaluation.age_context(player(age=21), baseline()) == "AA, 21yo, TEX -3"
    assert evaluation.age_context(player(age=26), baseline()) == "AA, 26yo, TEX +2"
    # A signed zero would read as a mistake rather than as typical for the level.
    assert evaluation.age_context(player(age=24), baseline()) == "AA, 24yo, TEX 0"


def test_age_context_keeps_the_level_when_the_age_is_missing():
    """The level is worth stating on its own; the comparison is what needs both."""
    assert evaluation.age_context(player(age=None), baseline()) == "AA"
    assert evaluation.age_context(player(), baseline(average_age=None)) == "AA, 21yo"


def test_the_current_stint_is_the_level_of_the_latest_game():
    aa = player(level="AA", plateAppearances=400)
    aaa = player(level="AAA", plateAppearances=100)
    current, previous = evaluation.split_stints([aa, aaa], current_level="AAA")
    assert current.level == "AAA"
    assert previous.level == "AA"


def test_the_biggest_stint_is_used_when_the_level_is_unknown():
    aa = player(level="AA", plateAppearances=400)
    aaa = player(level="AAA", plateAppearances=100)
    current, _ = evaluation.split_stints([aa, aaa], current_level=None)
    assert current.level == "AA"


def test_a_single_stint_has_no_previous_level():
    current, previous = evaluation.split_stints([player()], current_level="AA")
    assert current.level == "AA"
    assert previous is None


def test_production_line_leaves_the_level_to_the_heading_above_it():
    """The entry header already names the level, so repeating it is noise."""
    rendered = evaluation.render_production(
        evaluation.evaluate(player(), baseline(), 50)
    )
    assert "AA (TEX)" not in rendered
    assert "wRC+" in rendered
    assert "400 PA" in rendered


def test_a_prior_stint_carries_the_same_full_line_as_the_current_one():
    """A level a prospect has left is still a season worth reading in full."""
    rendered = evaluation.render_prior(evaluation.evaluate(player(), baseline(), 50))
    assert "AA (TEX)" in rendered
    assert "wOBA" in rendered
    assert "wRC+" in rendered
    assert "400 PA" in rendered


def test_park_adjustment_divides_out_the_component_at_half_strength():
    rate = evaluation.baselines.park_adjust(
        0.200, "home_runs_per_fly", {"home_runs": 1.20}
    )
    assert rate == pytest.approx(0.200 / 1.10)


def test_air_is_measured_against_the_ground_ball_factor_turned_over():
    """A park that inflates grounders deflates the air rate, so it is flipped."""
    inflated = evaluation.baselines.park_adjust(0.60, "air", {"ground_balls": 1.20})
    assert inflated > 0.60


def test_contact_is_measured_against_whiffs_not_strikeouts():
    """
    Strikeouts bundle whiffs with called strikes, and parks move the two
    independently, so a bat-to-ball rate is adjusted by the whiff factor alone.
    """
    adjusted = evaluation.baselines.park_adjust(0.75, "contact", {"whiffs": 1.20})
    assert adjusted > 0.75
    # The strikeout factor must not leak into it.
    assert (
        evaluation.baselines.park_adjust(0.75, "contact", {"strikeouts": 1.20}) == 0.75
    )


def test_walk_rates_are_measured_against_the_walk_factor():
    """
    The called-strike factor describes the mechanism but tracks the park's
    actual walk effect only weakly, so the direct measurement is used.
    """
    assert evaluation.baselines.park_adjust(
        0.10, "discipline", {"walks": 1.20}
    ) == pytest.approx(0.10 / 1.10)
    assert (
        evaluation.baselines.park_adjust(0.10, "command", {"called_strikes": 0.50})
        == 0.10
    )


def test_a_neutral_park_changes_nothing():
    assert evaluation.baselines.park_adjust(0.25, "command", {"walks": 1.0}) == 0.25


def test_park_adjustment_passes_missing_values_through():
    assert (
        evaluation.baselines.park_adjust(None, "contact", {"strikeouts": 1.2}) is None
    )


def test_the_player_and_the_league_are_adjusted_the_same_way():
    """
    The double-counting trap.

    A player adjusted against an unadjusted league would be credited for his
    park while his peers still carry theirs. Two identical players in identical
    parks must land on the same percentile however extreme the park is.
    """
    neutral_pool = [
        PlayerSeason(
            player_id=i,
            name=f"P{i}",
            league_id=109,
            league_name="TEX",
            level="AA",
            group="pitching",
            stat={"battersFaced": 400, "baseOnBalls": i, "strikeOuts": 100},
            team_id=1,
        )
        for i in range(1, 61)
    ]

    class Parks:
        def __init__(self, factor):
            self.factor = factor

        def for_team(self, team_id):
            return {"walks": self.factor, "whiffs": 1.0}

    subject = neutral_pool[30]
    results = []
    for factor in (1.0, 1.30):
        parks = Parks(factor)
        built = baselines.build(neutral_pool, "pitching", 50, parks=parks)[109]
        results.append(
            evaluation.evaluate(
                subject, built, 50, park_components=parks.for_team(1)
            ).skills
        )

    walks = [{s.name: s.percentile for s in skills}["BB%\u2193"] for skills in results]
    assert walks[0] == walks[1]


def test_batted_balls_are_matched_to_the_stint_they_were_hit_in(monkeypatch):
    """
    A promoted player has one row per level, each with that level's home runs.
    Pooling his batted balls across both would divide one level's damage by two
    levels' chances at it.
    """

    def counts(fly, ground):
        return {
            "fly": fly,
            "ground": ground,
            "line": 0,
            "pop": 0,
            "pull": fly,
            "oppo": 0,
        }

    per_level = {11: {7: counts(20, 10)}, 12: {7: counts(80, 40)}}

    class Stub:
        PLAYER_FIELDS = ("ground", "line", "fly", "pop", "pull", "oppo")
        TRAJECTORY_FIELDS = ("ground", "line", "fly", "pop")
        SPRAY_FIELDS = ("pull", "oppo")

        @staticmethod
        def load_cached(sport_id, season):
            return per_level.get(sport_id)

        @staticmethod
        def by_player(games, side):
            return games

    monkeypatch.setattr(baselines, "pitch_data", Stub)

    def stint(sport_id, level):
        return PlayerSeason(
            player_id=7,
            name="A Prospect",
            league_id=109,
            league_name="TEX",
            level=level,
            group="hitting",
            stat={},
            sport_id=sport_id,
        )

    triple_a, double_a = baselines._with_batted_ball(
        [stint(11, "AAA"), stint(12, "AA")], (11, 12), 2026, "hitting"
    )
    assert triple_a.stat["flyBalls"] == 20
    assert double_a.stat["flyBalls"] == 80


def test_ordinals_read_naturally():
    assert evaluation._ordinal(1) == "1st"
    assert evaluation._ordinal(2) == "2nd"
    assert evaluation._ordinal(3) == "3rd"
    assert evaluation._ordinal(11) == "11th"
    assert evaluation._ordinal(21) == "21st"


def test_a_skill_carries_its_own_rate_beside_the_rank():
    """
    A percentile alone says a player beats his peers without saying at what.
    90th in HR/FB means one thing in the California League and another in the
    PCL, and only the number itself settles it.
    """
    rendered = evaluation.render_skills(
        evaluation.evaluate(player(), baseline(), minimum_sample=50)
    )
    # 96 pulled of 240 located batted balls.
    assert "Pull% 40.0% 39th" in rendered
    assert " · " in rendered


def test_power_bars_are_absent_when_play_by_play_was_never_gathered():
    """All three lean on play-by-play, so none of them guesses at a zero."""
    thin = player()
    for key in BATTED_BALL_KEYS:
        del thin.stat[key]

    result = evaluation.evaluate(thin, baseline(), minimum_sample=50)
    ranked = {skill.name: skill.percentile for skill in result.skills}
    assert ranked["HR/FB"] is None
    assert ranked["Air%"] is None
    assert ranked["Pull%"] is None
    assert ranked["Contact%"] is not None
