from __future__ import annotations

import pytest

from mlb_report import pitch_data


def pitch(description, is_pitch=True, hit_data=None, zone=None, speed=None):
    event = {"isPitch": is_pitch, "details": {"description": description}}
    if hit_data:
        event["hitData"] = hit_data
    if zone is not None:
        event["pitchData"] = {"zone": zone}
    if speed is not None:
        event.setdefault("hitData", {})["launchSpeed"] = speed
    return event


def play(half, *descriptions, bat_side="R", batter=1, pitcher=2):
    return {
        "about": {"halfInning": half},
        "matchup": {
            "batSide": {"code": bat_side},
            "batter": {"id": batter},
            "pitcher": {"id": pitcher},
        },
        "playEvents": [pitch(d) if isinstance(d, str) else d for d in descriptions],
    }


def batted(trajectory, coord_x, coord_y):
    return pitch(
        "In play, out(s)",
        hit_data={
            "trajectory": trajectory,
            "coordinates": {"coordX": coord_x, "coordY": coord_y},
        },
    )


SIDES = {"home": 10, "away": 20}


def parse(payload, monkeypatch):
    monkeypatch.setattr(pitch_data.statsapi, "get", lambda *a, **k: payload)
    return pitch_data.parse_game(1, SIDES)["clubs"]


def full(**overrides):
    totals = pitch_data._blank()
    totals.update(overrides)
    return totals


def test_the_batting_side_follows_the_half_inning(monkeypatch):
    """Visitors hit in the top, so their outcomes belong to the away club."""
    result = parse(
        {"allPlays": [play("top", "Swinging Strike"), play("bottom", "Called Strike")]},
        monkeypatch,
    )
    assert result[20]["whiffs"] == 1
    assert result[20]["called_strikes"] == 0
    assert result[10]["called_strikes"] == 1
    assert result[10]["whiffs"] == 0


def test_swings_cover_every_way_a_bat_moves(monkeypatch):
    result = parse(
        {
            "allPlays": [
                play(
                    "top",
                    "Swinging Strike",
                    "Swinging Strike (Blocked)",
                    "Foul",
                    "Foul Tip",
                    "In play, out(s)",
                    "Missed Bunt",
                )
            ]
        },
        monkeypatch,
    )
    assert result[20]["swings"] == 6


def test_taken_pitches_are_not_swings(monkeypatch):
    result = parse(
        {"allPlays": [play("top", "Ball", "Called Strike", "Ball In Dirt")]},
        monkeypatch,
    )
    assert result[20]["swings"] == 0
    assert result[20]["pitches"] == 3
    assert result[20]["called_strikes"] == 1


def test_a_foul_tip_counts_as_a_whiff(monkeypatch):
    """The bat did not change the ball's path enough to put it in play."""
    result = parse({"allPlays": [play("top", "Foul Tip")]}, monkeypatch)
    assert result[20]["whiffs"] == 1
    assert result[20]["swings"] == 1


def test_a_foul_is_a_swing_but_not_a_whiff(monkeypatch):
    result = parse({"allPlays": [play("top", "Foul")]}, monkeypatch)
    assert result[20]["swings"] == 1
    assert result[20]["whiffs"] == 0


def test_non_pitch_events_are_ignored(monkeypatch):
    """Pickoffs, substitutions and mound visits are in the same event list."""
    payload = {
        "allPlays": [
            {
                "about": {"halfInning": "top"},
                "playEvents": [
                    pitch("Pickoff Attempt 1B", is_pitch=False),
                    pitch("Ball"),
                ],
            }
        ]
    }
    result = parse(payload, monkeypatch)
    assert result[20]["pitches"] == 1


def test_rates_are_per_swing_and_per_taken_pitch():
    rates = pitch_data.rates(full(pitches=100, swings=40, whiffs=10, called_strikes=18))
    assert rates["whiffs"] == pytest.approx(0.25)
    assert rates["called_strikes"] == pytest.approx(18 / 60)


def test_batted_ball_rates_use_their_own_denominators():
    """
    A park sees far fewer batted balls than pitches, and only some of those
    balls carry a landing spot, so each rate counts its own chances.
    """
    rates = pitch_data.rates(
        full(ground=30, line=20, fly=40, pop=10, pull=45, center=30, oppo=25)
    )
    assert rates["ground_balls"] == pytest.approx(0.30)
    assert rates["pull"] == pytest.approx(0.45)


def test_rates_are_none_without_a_denominator():
    rates = pitch_data.rates(full())
    assert rates["whiffs"] is None
    assert rates["called_strikes"] is None
    assert rates["ground_balls"] is None
    assert rates["pull"] is None


def test_a_swing_at_a_pitch_outside_the_zone_is_a_chase(monkeypatch):
    result = parse(
        {
            "allPlays": [
                play(
                    "top",
                    pitch("Swinging Strike", zone=13),
                    pitch("Ball", zone=14),
                    pitch("Swinging Strike", zone=5),
                )
            ]
        },
        monkeypatch,
    )
    assert result[20]["out_of_zone"] == 2
    assert result[20]["chases"] == 1


def test_a_level_that_tracks_nothing_reports_no_chase_rate(monkeypatch):
    """Below Triple-A no pitch carries a zone, and a rate of nothing is absent."""
    result = parse({"allPlays": [play("top", "Swinging Strike", "Ball")]}, monkeypatch)
    assert result[20]["out_of_zone"] == 0
    assert pitch_data.rates(result[20])["chases"] is None


def test_exit_velocity_is_totalled_so_it_can_be_averaged(monkeypatch):
    result = parse(
        {
            "allPlays": [
                play(
                    "top",
                    pitch("In play, out(s)", speed=100.0),
                    pitch("In play, no out", speed=80.0),
                )
            ]
        },
        monkeypatch,
    )
    assert result[20]["measured"] == 2
    assert pitch_data.rates(result[20])["exit_speed"] == pytest.approx(90.0)


def test_a_ball_hit_hard_enough_is_counted_apart(monkeypatch):
    result = parse(
        {
            "allPlays": [
                play(
                    "top",
                    pitch("In play, out(s)", speed=pitch_data.HARD_HIT_MPH),
                    pitch("In play, out(s)", speed=pitch_data.HARD_HIT_MPH - 0.1),
                )
            ]
        },
        monkeypatch,
    )
    assert result[20]["hard_hit"] == 1


def test_an_untracked_ball_in_play_adds_nothing_to_the_average(monkeypatch):
    """One measured ball and one unmeasured must not average to half its speed."""
    result = parse(
        {
            "allPlays": [
                play(
                    "top",
                    pitch("In play, out(s)", speed=100.0),
                    pitch("In play, out(s)"),
                )
            ]
        },
        monkeypatch,
    )
    assert result[20]["measured"] == 1
    assert pitch_data.rates(result[20])["exit_speed"] == pytest.approx(100.0)


def test_a_cache_from_an_older_shape_is_cleared_away(monkeypatch, tmp_path):
    """Otherwise it rides along in the artifact that carries the cache."""
    monkeypatch.setattr(pitch_data, "user_data_dir", lambda: tmp_path)
    stale = tmp_path / f"pitch_v{pitch_data.SCHEMA - 1}_11_2026.json"
    stale.write_text("{}", encoding="utf-8")
    current = tmp_path / f"pitch_v{pitch_data.SCHEMA}_11_2026.json"
    current.write_text("{}", encoding="utf-8")
    other = tmp_path / f"pitch_v{pitch_data.SCHEMA - 1}_12_2026.json"
    other.write_text("{}", encoding="utf-8")

    removed = pitch_data.discard_old_schemas(11, 2026)

    assert removed == [stale.name]
    assert current.exists()
    # A different level's cache is not this run's to tidy up.
    assert other.exists()


def test_both_men_are_credited_with_the_chase_and_the_contact(monkeypatch):
    """A chase is the hitter's lapse and the pitcher's doing at once."""
    monkeypatch.setattr(
        pitch_data.statsapi,
        "get",
        lambda *a, **k: {
            "allPlays": [
                play(
                    "top",
                    pitch("Swinging Strike", zone=13),
                    pitch("In play, out(s)", speed=101.0),
                    batter=7,
                    pitcher=9,
                )
            ]
        },
    )
    parsed = pitch_data.parse_game(1, SIDES)
    for side, player in (("batters", 7), ("pitchers", 9)):
        counts = parsed[side][player]
        assert counts["chases"] == 1
        assert counts["out_of_zone"] == 1
        assert counts["measured"] == 1
        assert counts["exit_speed_total"] == pytest.approx(101.0)


def test_by_club_counts_both_sides_in_every_game():
    """
    Same construction as the park factors: the home club's own games, both
    sides of the ball, split into here and elsewhere.
    """
    games = {
        1: {
            "clubs": {
                10: full(pitches=100, swings=40, whiffs=10, called_strikes=15),
                20: full(pitches=100, swings=30, whiffs=5, called_strikes=10),
            },
            "batters": {},
            "pitchers": {},
        },
        2: {
            "clubs": {
                10: full(pitches=50, swings=20, whiffs=4, called_strikes=7),
                20: full(pitches=50, swings=25, whiffs=6, called_strikes=8),
            },
            "batters": {},
            "pitchers": {},
        },
    }
    at_home, on_road = pitch_data.by_club(games, home_of={1: 10, 2: 20})

    # Club 10 hosted game 1, so both clubs' lines land in its home totals.
    assert at_home[10]["whiffs"] == 15
    assert at_home[10]["pitches"] == 200
    # Game 2 was away for club 10.
    assert on_road[10]["whiffs"] == 10


def test_pull_depends_on_which_way_the_batter_stands():
    """The same ball down the left-field line is pulled only by a right-hander."""
    down_the_left_line = (60.0, 100.0)
    assert pitch_data.spray(*down_the_left_line, "R") == "pull"
    assert pitch_data.spray(*down_the_left_line, "L") == "oppo"


def test_balls_up_the_middle_are_neither_pulled_nor_served():
    assert pitch_data.spray(125.0, 60.0, "R") == "center"
    assert pitch_data.spray(125.0, 60.0, "L") == "center"


def test_a_switch_hitter_without_a_recorded_side_is_not_guessed():
    assert pitch_data.spray(60.0, 100.0, None) is None


def test_batted_balls_are_credited_to_batter_and_pitcher(monkeypatch):
    """
    Both ends of the same event. The pitcher's line is what was hit against
    him, which is the measure read from the other side.
    """
    payload = {
        "allPlays": [
            play(
                "top",
                batted("ground_ball", 60.0, 100.0),
                bat_side="R",
                batter=101,
                pitcher=202,
            )
        ]
    }
    monkeypatch.setattr(pitch_data.statsapi, "get", lambda *a, **k: payload)
    result = pitch_data.parse_game(1, SIDES)

    assert result["batters"][101]["ground"] == 1
    assert result["batters"][101]["pull"] == 1
    assert result["pitchers"][202]["ground"] == 1
    assert result["clubs"][20]["ground"] == 1


def test_a_ball_without_coordinates_still_counts_as_a_grounder(monkeypatch):
    """Trajectory and location are recorded independently, so one can be missing."""
    grounder = pitch("In play, out(s)", hit_data={"trajectory": "ground_ball"})
    payload = {"allPlays": [play("top", grounder)]}
    monkeypatch.setattr(pitch_data.statsapi, "get", lambda *a, **k: payload)
    result = pitch_data.parse_game(1, SIDES)

    assert result["clubs"][20]["ground"] == 1
    assert sum(result["clubs"][20][f] for f in pitch_data.SPRAY_FIELDS) == 0


def test_by_player_totals_a_season_across_games():
    games = {
        1: {
            "clubs": {},
            "batters": {
                101: {
                    "ground": 2,
                    "line": 1,
                    "fly": 0,
                    "pop": 0,
                    "pull": 2,
                    "center": 1,
                    "oppo": 0,
                }
            },
            "pitchers": {},
        },
        2: {
            "clubs": {},
            "batters": {
                101: {
                    "ground": 1,
                    "line": 0,
                    "fly": 3,
                    "pop": 0,
                    "pull": 1,
                    "center": 0,
                    "oppo": 3,
                }
            },
            "pitchers": {},
        },
    }
    totals = pitch_data.by_player(games, "batters")
    assert totals[101]["ground"] == 3
    assert totals[101]["oppo"] == 3
