from __future__ import annotations

import pytest

from mlb_report import baselines, evaluation
from mlb_report.baselines import LeagueBaseline, PlayerSeason


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
            "power": values,
            "discipline": values,
            "contact_suppression": values,
            "damage_limitation": values,
            "command": values,
            "ground_ball": values,
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
    result = evaluation.evaluate(player(), baseline(), 50)
    assert result.production is not None
    assert len(result.skills) == 3


def test_percentiles_for_lower_is_better_metrics_are_inverted():
    """Command is walk rate: a low rate should rank high."""
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
    command = {s.name: s.percentile for s in wild.skills}["Command"]
    better = {s.name: s.percentile for s in stingy.skills}["Command"]
    assert better > command


def test_a_small_league_pool_yields_no_percentile():
    thin = baseline(distributions={"contact": [0.7, 0.8]})
    result = evaluation.evaluate(player(), thin, 50)
    assert {s.name: s.percentile for s in result.skills}["Contact"] is None


def test_age_context_reads_relative_to_the_league():
    assert "3 years young for the TEX" in evaluation.age_context(
        player(age=21), baseline()
    )
    assert "2 years old for the TEX" in evaluation.age_context(
        player(age=26), baseline()
    )
    assert "typical age" in evaluation.age_context(player(age=24), baseline())


def test_age_context_needs_both_an_age_and_a_league_average():
    assert evaluation.age_context(player(age=None), baseline()) is None
    assert evaluation.age_context(player(), baseline(average_age=None)) is None


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


def test_production_line_names_the_level_and_league():
    rendered = evaluation.render_production(
        evaluation.evaluate(player(), baseline(), 50)
    )
    assert "AA (TEX)" in rendered
    assert "wRC+" in rendered
    assert "400 PA" in rendered


def test_park_adjustment_divides_out_the_component_at_half_strength():
    power = evaluation.baselines.park_adjust(0.200, "power", {"extra_base_hits": 1.20})
    assert power == pytest.approx(0.200 / 1.10)


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

    command = [{s.name: s.percentile for s in skills}["Command"] for skills in results]
    assert command[0] == command[1]


def test_ordinals_read_naturally():
    assert evaluation._ordinal(1) == "1st"
    assert evaluation._ordinal(2) == "2nd"
    assert evaluation._ordinal(3) == "3rd"
    assert evaluation._ordinal(11) == "11th"
    assert evaluation._ordinal(21) == "21st"


def test_batted_ball_profile_reports_the_rate_with_its_rank():
    """The rate leads and the rank only places it, since neither has a good end."""
    result = evaluation.evaluate(player(), baseline(), minimum_sample=50)
    rendered = evaluation.render_profile(result)

    assert "40% grounders" in rendered
    assert "40% pulled" in rendered
    assert "(39th)" in rendered


def test_a_pitcher_does_not_report_grounders_twice():
    """It is already a headline skill for him, where it does have a good end."""
    result = evaluation.evaluate(
        player(group="pitching", battersFaced=400),
        baseline(group="pitching"),
        minimum_sample=50,
    )
    assert [entry.name for entry in result.profile] == ["pulled"]


def test_profile_is_absent_when_play_by_play_was_never_gathered():
    """A season without a pass reports nothing rather than a zero rate."""
    thin = player()
    for key in ("battedBalls", "groundBalls", "sprayedBalls", "pulledBalls"):
        del thin.stat[key]

    result = evaluation.evaluate(thin, baseline(), minimum_sample=50)
    assert evaluation.render_profile(result) is None
