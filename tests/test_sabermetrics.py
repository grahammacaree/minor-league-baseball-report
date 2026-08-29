from __future__ import annotations

import pytest

from mlb_report import sabermetrics as sm

# A league-average-ish line, used as the reference point for the index stats.
LEAGUE = {
    "runs": 5000.0,
    "plateAppearances": 40000.0,
    "atBats": 35000.0,
    "hits": 8750.0,
    "doubles": 1750.0,
    "triples": 175.0,
    "homeRuns": 875.0,
    "baseOnBalls": 3600.0,
    "intentionalWalks": 0.0,
    "hitByPitch": 400.0,
    "sacFlies": 300.0,
    "strikeOuts": 9000.0,
}


def hitter(**overrides):
    stat = {
        "plateAppearances": 400.0,
        "atBats": 350.0,
        "hits": 87.5,
        "doubles": 17.5,
        "triples": 1.75,
        "homeRuns": 8.75,
        "baseOnBalls": 36.0,
        "intentionalWalks": 0.0,
        "hitByPitch": 4.0,
        "sacFlies": 3.0,
        "strikeOuts": 90.0,
    }
    stat.update(overrides)
    return sm.events(stat)


def league_context():
    events = sm.events(LEAGUE)
    return (
        LEAGUE["runs"] / LEAGUE["plateAppearances"],
        sm.runs_above_average(events) / LEAGUE["plateAppearances"],
    )


def test_singles_are_derived_from_the_other_hit_types():
    events = sm.events({"hits": 10, "doubles": 3, "triples": 1, "homeRuns": 2})
    assert events.singles == 4


def test_intentional_walks_are_excluded_from_woba():
    unintentional = sm.events({"baseOnBalls": 10, "intentionalWalks": 4})
    assert unintentional.walks == 6


def test_woba_is_rescaled_onto_the_obp_scale():
    events = sm.events(LEAGUE)
    scale = sm.on_base_percentage(events) / sm.raw_woba(events)
    assert sm.woba(events, scale) == pytest.approx(sm.on_base_percentage(events))


def test_a_league_average_line_indexes_to_100():
    runs_per_pa, raa_per_pa = league_context()
    index = sm.wrc_plus(hitter(), runs_per_pa, raa_per_pa)
    assert index == pytest.approx(100, abs=1)


def test_a_better_line_indexes_above_100():
    runs_per_pa, raa_per_pa = league_context()
    slugger = hitter(hits=120.0, doubles=30.0, homeRuns=30.0, baseOnBalls=60.0)
    assert sm.wrc_plus(slugger, runs_per_pa, raa_per_pa) > 130


def test_a_worse_line_indexes_below_100():
    runs_per_pa, raa_per_pa = league_context()
    weak = hitter(hits=60.0, doubles=8.0, triples=0.0, homeRuns=1.0, baseOnBalls=15.0)
    assert sm.wrc_plus(weak, runs_per_pa, raa_per_pa) < 80


def test_a_hitters_park_drags_the_index_down():
    runs_per_pa, raa_per_pa = league_context()
    neutral = sm.wrc_plus(hitter(), runs_per_pa, raa_per_pa, park_factor=1.0)
    inflated = sm.wrc_plus(hitter(), runs_per_pa, raa_per_pa, park_factor=1.10)
    assert inflated < neutral


def test_empty_lines_do_not_divide_by_zero():
    runs_per_pa, raa_per_pa = league_context()
    assert sm.wrc_plus(sm.events({}), runs_per_pa, raa_per_pa) == 0.0
    assert sm.raw_woba(sm.events({})) == 0.0
    assert sm.on_base_percentage(sm.events({})) == 0.0


def test_fip_constant_makes_league_fip_equal_league_era():
    league = {
        "homeRuns": 1000.0,
        "baseOnBalls": 3600.0,
        "hitByPitch": 400.0,
        "strikeOuts": 9000.0,
        "inningsPitched": 9000.0,
    }
    constant = sm.fip_constant(4.20, league)
    assert sm.fip(league, constant) == pytest.approx(4.20)


def test_fip_punishes_home_runs_and_rewards_strikeouts():
    constant = 3.10
    baseline = {
        "homeRuns": 10,
        "baseOnBalls": 40,
        "strikeOuts": 100,
        "inningsPitched": 100,
    }
    homer_prone = {**baseline, "homeRuns": 25}
    strikeout_heavy = {**baseline, "strikeOuts": 140}
    assert sm.fip(homer_prone, constant) > sm.fip(baseline, constant)
    assert sm.fip(strikeout_heavy, constant) < sm.fip(baseline, constant)


def test_fip_minus_indexes_against_the_league_with_lower_being_better():
    assert sm.fip_minus(4.00, 4.00) == pytest.approx(100)
    assert sm.fip_minus(3.00, 4.00) < 100


def test_contact_rate_is_the_complement_of_whiffs():
    assert sm.contact_rate(
        {"totalSwings": 400, "swingAndMisses": 100}
    ) == pytest.approx(0.75)
    assert sm.contact_rate({"totalSwings": 0}) is None


def test_isolated_power_excludes_singles():
    singles_only = hitter(hits=50.0, doubles=0.0, triples=0.0, homeRuns=0.0)
    assert sm.isolated_power(singles_only) == pytest.approx(0.0)


def test_solid_contact_counts_line_drives_and_fly_balls():
    stat = {
        "ballsInPlay": 100,
        "lineHits": 20,
        "lineOuts": 10,
        "flyHits": 5,
        "flyOuts": 15,
    }
    assert sm.solid_contact_rate(stat) == pytest.approx(0.50)


def test_rate_stats_return_none_rather_than_zero_without_a_sample():
    assert sm.strikeout_rate({}) is None
    assert sm.walk_rate({}) is None
    assert sm.ground_ball_rate({}) is None
    assert sm.air_rate({}) is None
    assert sm.home_runs_per_fly_ball({}) is None
    assert sm.home_runs_per_nine({}) is None
    assert sm.strikeouts_minus_walks({}) is None


def test_air_is_exactly_what_is_not_on_the_ground():
    stat = {"battedBalls": 250, "groundBalls": 100}
    assert sm.air_rate(stat) == pytest.approx(0.60)
    assert sm.air_rate(stat) + sm.ground_ball_rate(stat) == pytest.approx(1.0)


def test_home_runs_per_fly_ball_is_damage_per_chance_to_do_it():
    """
    Fly balls come from play-by-play and home runs from the season feed, so the
    two only line up when the level has been gathered in full.
    """
    assert sm.home_runs_per_fly_ball({"homeRuns": 15, "flyBalls": 75}) == pytest.approx(
        0.20
    )
