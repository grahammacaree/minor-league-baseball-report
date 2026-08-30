from __future__ import annotations

import pytest

from mlb_report import park, park_builder, pitch_data
from mlb_report.park_builder import Totals


def season(runs, team="529"):
    return {
        team: {
            "runs": runs,
            "strikeouts": 1.0,
            "walks": 1.0,
            "home_runs": 1.0,
            "hits_in_play": 1.0,
            "extra_base_hits": 1.0,
        }
    }


def test_blend_applies_recency_weights():
    """5/3/1 over nine: the most recent season carries the most."""
    blended = park.blend([season(1.20), season(1.00), season(1.00)])
    expected = (5 * 1.20 + 3 * 1.00 + 1 * 1.00) / 9
    assert blended[529]["runs"] == pytest.approx(expected)


def test_blend_stays_centred_when_every_season_agrees():
    blended = park.blend([season(1.10), season(1.10), season(1.10)])
    assert blended[529]["runs"] == pytest.approx(1.10)


def test_weights_are_renormalized_over_missing_seasons():
    """One season of history should not be dragged toward 1.0 by absent years."""
    blended = park.blend([season(1.20)])
    assert blended[529]["runs"] == pytest.approx(1.20)


def test_a_component_younger_than_the_window_is_not_dragged_toward_neutral():
    """
    Tracking arrives at a level long after the seasons behind it were played,
    so a component can exist in one season of three. Renormalising per
    component is what keeps its first year from being two-thirds absent data.
    """
    seasons = [season(1.10), season(1.10), season(1.10)]
    seasons[0]["529"]["pull"] = 1.06

    blended = park.blend(seasons)
    assert blended[529]["pull"] == pytest.approx(1.06)
    assert blended[529]["runs"] == pytest.approx(1.10)


def test_blend_of_nothing_is_empty():
    assert park.blend([]) == {}


def test_unknown_teams_are_neutral():
    factors = park.ParkFactors(season=2026, by_team={})
    assert factors.for_team(999) == park.NEUTRAL
    assert factors.runs_factor(999) == pytest.approx(1.0)


def test_the_runs_factor_is_halved_toward_neutral():
    """Half a player's games are on the road, so his park only counts half."""
    factors = park.ParkFactors(season=2026, by_team={529: {"runs": 1.10}})
    assert factors.runs_factor(529) == pytest.approx(1.05)


def test_describe_stays_quiet_about_ordinary_parks():
    assert park.describe({"runs": 1.01, "strikeouts": 0.98}) is None


def test_describe_flags_a_distorting_park():
    described = park.describe({"runs": 1.12, "strikeouts": 0.90})
    assert "inflates runs 12%" in described
    assert "suppresses strikeouts 10%" in described


def totals(plate_appearances, **events):
    result = Totals()
    result.add({"plateAppearances": plate_appearances, **events})
    return result


def test_hits_in_play_are_rated_per_ball_in_play():
    """Otherwise a park that changes strikeouts moves this for the wrong reason."""
    result = totals(100, strikeOuts=20, baseOnBalls=10, homeRuns=2, hits=30)
    assert result.balls_in_play == pytest.approx(68)
    assert result.rate("hits_in_play") == pytest.approx(28 / 68)


def test_other_components_are_rated_per_plate_appearance():
    result = totals(100, strikeOuts=25)
    assert result.rate("strikeouts") == pytest.approx(0.25)


def test_rates_are_none_without_a_denominator():
    assert Totals().rate("runs") is None


def test_regression_pulls_small_samples_toward_neutral():
    barely = park_builder._regress(1.50, sample=100)
    full = park_builder._regress(1.50, sample=100000)
    assert 1.0 < barely < 1.05
    assert full > 1.45


def test_factors_are_normalized_within_the_league():
    """A league's parks average to 1.0, so the index means 'neutral here'."""
    collected = {}
    for park_id, runs in ((1, 60.0), (2, 50.0), (3, 40.0)):
        at = Totals()
        at.add({"plateAppearances": 10000, "runs": runs * 100})
        away = Totals()
        away.add({"plateAppearances": 10000, "runs": 5000})
        collected[park_id] = {"at": at, "elsewhere": away, "league_id": 112}

    by_league = park_builder.factors(collected)
    values = [factors["runs"] for factors in by_league[112].values()]
    assert sum(values) / len(values) == pytest.approx(1.0)
    assert values[0] > values[1] > values[2]


def test_collect_holds_the_home_club_constant_and_counts_both_sides(monkeypatch):
    """
    The property the whole construction rests on.

    A park's totals must come from the home club's own games, both sides of the
    ball, compared against that same club's games elsewhere. That is what keeps
    the club's roster on both sides of the ratio, so only the park differs.
    """
    # Club 1 hosts club 2, then visits club 2.
    home_of = {100: 1, 200: 2}
    logs = {
        1: {
            100: {"plateAppearances": 40, "runs": 8},
            200: {"plateAppearances": 40, "runs": 1},
        },
        2: {
            100: {"plateAppearances": 40, "runs": 6},
            200: {"plateAppearances": 40, "runs": 2},
        },
    }
    teams = {1: {"league": {"id": 109}}, 2: {"league": {"id": 109}}}

    monkeypatch.setattr(park_builder, "home_team_by_game", lambda *_: home_of)
    monkeypatch.setattr(park_builder, "team_game_logs", lambda *_: (logs, teams))

    collected = park_builder.collect(12, 2025)

    # Club 1's home game: its own 8 runs plus the 6 it allowed.
    assert collected[1]["at"].events["runs"] == 14
    assert collected[1]["at"].plate_appearances == 80
    # Its road game: the 1 it scored plus the 2 it allowed.
    assert collected[1]["elsewhere"].events["runs"] == 3


def test_a_club_with_no_road_games_is_dropped(monkeypatch):
    """Without both halves there is no comparison to make."""
    monkeypatch.setattr(park_builder, "home_team_by_game", lambda *_: {100: 1})
    monkeypatch.setattr(
        park_builder,
        "team_game_logs",
        lambda *_: ({1: {100: {"plateAppearances": 40}}}, {1: {"league": {"id": 109}}}),
    )
    assert park_builder.collect(12, 2025) == {}


def game(home, away, home_counts, away_counts):
    def totals(counts):
        blank = pitch_data._blank()
        blank.update(counts)
        return blank

    return {home: totals(home_counts), away: totals(away_counts)}


def test_a_tracked_level_gets_a_chase_and_exit_speed_factor(monkeypatch):
    """
    Both are built exactly like the others: home club, both sides, here
    against elsewhere. A park where visitors chase more is a park where its
    own hitters chase more, and only the park is left in the ratio.
    """
    # Club 1 hosts, then visits. Chases and exit speed both run high at home.
    games = {
        100: {"clubs": game(1, 2, {"out_of_zone": 5000, "chases": 1500,
                                   "measured": 5000, "exit_speed_total": 450000},
                            {"out_of_zone": 5000, "chases": 1500,
                             "measured": 5000, "exit_speed_total": 450000})},
        200: {"clubs": game(2, 1, {"out_of_zone": 5000, "chases": 1250,
                                   "measured": 5000, "exit_speed_total": 435000},
                            {"out_of_zone": 5000, "chases": 1250,
                             "measured": 5000, "exit_speed_total": 435000})},
    }
    monkeypatch.setattr(park_builder.pitch_data, "load_cached", lambda *_: games)

    by_league = park_builder.pitch_factors(11, 2025, {1: 112, 2: 112}, {100: 1, 200: 2})

    assert by_league[112][1]["chases"] > 1.0
    assert by_league[112][1]["exit_speed"] > 1.0
    assert by_league[112][2]["chases"] < 1.0


def test_a_level_that_tracks_nothing_gets_neither_factor(monkeypatch):
    """Double-A still earns its whiff factor; it just has no chase to measure."""
    games = {
        100: {"clubs": game(1, 2, {"pitches": 3000, "swings": 1500, "whiffs": 400},
                            {"pitches": 3000, "swings": 1500, "whiffs": 400})},
        200: {"clubs": game(2, 1, {"pitches": 3000, "swings": 1500, "whiffs": 300},
                            {"pitches": 3000, "swings": 1500, "whiffs": 300})},
    }
    monkeypatch.setattr(park_builder.pitch_data, "load_cached", lambda *_: games)

    by_league = park_builder.pitch_factors(12, 2025, {1: 112, 2: 112}, {100: 1, 200: 2})

    assert "whiffs" in by_league[112][1]
    assert "chases" not in by_league[112][1]
    assert "exit_speed" not in by_league[112][1]


def test_parks_in_different_leagues_normalize_separately():
    collected = {}
    for park_id, league_id in ((1, 112), (2, 117)):
        at = Totals()
        at.add({"plateAppearances": 10000, "runs": 5000})
        away = Totals()
        away.add({"plateAppearances": 10000, "runs": 5000})
        collected[park_id] = {"at": at, "elsewhere": away, "league_id": league_id}

    by_league = park_builder.factors(collected)
    assert set(by_league) == {112, 117}


def factors_for(**by_team) -> park.ParkFactors:
    return park.ParkFactors(
        season=2026,
        by_team={
            int(team): {**park.NEUTRAL, **values} for team, values in by_team.items()
        },
    )


def test_two_parks_blend_by_how_much_of_a_season_each_holds():
    parks = factors_for(**{"1": {"runs": 1.20}, "2": {"runs": 1.00}})
    mostly_first = parks.blended({1: 90.0, 2: 10.0})["runs"]
    mostly_second = parks.blended({1: 10.0, 2: 90.0})["runs"]
    assert mostly_first > mostly_second
    assert 1.00 < mostly_second < mostly_first < 1.20


def test_opposite_parks_cancel():
    """These are multipliers, so a fifth up and a sixth down is neutral."""
    parks = factors_for(**{"1": {"home_runs": 1.2}, "2": {"home_runs": 1 / 1.2}})
    assert parks.blended({1: 50.0, 2: 50.0})["home_runs"] == pytest.approx(1.0)


def test_one_club_blends_to_its_own_factors():
    parks = factors_for(**{"1": {"runs": 1.15}})
    assert parks.blended({1: 200.0})["runs"] == pytest.approx(1.15)


def test_blending_nothing_is_neutral():
    assert factors_for(**{"1": {"runs": 1.15}}).blended({}) == park.NEUTRAL


def test_the_blended_runs_factor_is_halved_like_any_other():
    """Half his games are on the road wherever he was traded from."""
    parks = factors_for(**{"1": {"runs": 1.20}, "2": {"runs": 1.20}})
    assert parks.blended_runs_factor({1: 50.0, 2: 50.0}) == pytest.approx(1.10)
