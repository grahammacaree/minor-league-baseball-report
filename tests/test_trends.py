from __future__ import annotations

from datetime import date

import pytest

from mlb_report import trends
from mlb_report.models import GameLog

CONFIG = {
    "min_hit_streak": 5,
    "rolling_windows_days": [7, 15],
    "min_rolling_plate_appearances": 15,
    "min_rolling_ops": 0.9,
    "max_rolling_ops": 0.55,
    "min_scoreless_outings": 3,
}


def hitting(day, hits=1, at_bats=4, **stat):
    return GameLog(
        player_id=1,
        player_name="A Hitter",
        game_date=date(2026, 8, day),
        game_pk=700000 + day,
        group="hitting",
        level="AA",
        team="Arkansas Travelers",
        opponent="Tulsa Drillers",
        summary="",
        stat={"hits": hits, "atBats": at_bats, "plateAppearances": at_bats, **stat},
    )


def pitching(day, earned_runs=0, innings="5.0", **stat):
    return GameLog(
        player_id=2,
        player_name="A Pitcher",
        game_date=date(2026, 8, day),
        game_pk=800000 + day,
        group="pitching",
        level="AA",
        team="Arkansas Travelers",
        opponent="Tulsa Drillers",
        summary="",
        stat={"earnedRuns": earned_runs, "inningsPitched": innings, **stat},
    )


def test_hit_streak_counts_back_from_the_latest_game():
    logs = [hitting(1, hits=0), hitting(2), hitting(3), hitting(4)]
    assert trends.hit_streak(logs) == 3


def test_hitless_game_ends_the_streak():
    assert trends.hit_streak([hitting(1), hitting(2, hits=0)]) == 0


def test_appearance_without_an_at_bat_does_not_break_a_streak():
    logs = [hitting(1), hitting(2), hitting(3, hits=0, at_bats=0)]
    assert trends.hit_streak(logs) == 2


def test_scoreless_streak_ends_on_an_earned_run():
    logs = [pitching(1), pitching(2, earned_runs=2), pitching(3), pitching(4)]
    assert trends.scoreless_outings(logs) == 2


def test_rolling_line_computes_the_slash():
    logs = [hitting(1, hits=2, at_bats=4, doubles=1), hitting(2, hits=1, at_bats=4)]
    line = trends.rolling_hitting(logs)
    assert line["avg"] == pytest.approx(3 / 8)
    assert line["slg"] == pytest.approx(4 / 8)


def test_window_is_inclusive_of_both_ends():
    logs = [hitting(1), hitting(5), hitting(7)]
    assert len(trends.window(logs, days=7, as_of=date(2026, 8, 7))) == 3
    assert len(trends.window(logs, days=3, as_of=date(2026, 8, 7))) == 2
    assert len(trends.window(logs, days=2, as_of=date(2026, 8, 7))) == 1


def test_hit_streak_is_reported_once_it_clears_the_bar():
    logs = [hitting(day) for day in range(1, 7)]
    found = trends.for_player(1, "A Hitter", logs, date(2026, 8, 6), CONFIG)
    assert any("6-game hit streak" in t.headline for t in found)


def test_short_streaks_are_not_reported():
    logs = [hitting(day) for day in range(1, 3)]
    found = trends.for_player(1, "A Hitter", logs, date(2026, 8, 2), CONFIG)
    assert not any("hit streak" in t.headline for t in found)


def test_hot_stretch_needs_enough_plate_appearances():
    logs = [hitting(day, hits=3, at_bats=4, homeRuns=1) for day in range(1, 3)]
    found = trends.for_player(1, "A Hitter", logs, date(2026, 8, 2), CONFIG)
    assert not any("hot over" in t.headline for t in found)


def test_hot_stretch_is_reported_with_the_slash_line():
    logs = [hitting(day, hits=3, at_bats=4, homeRuns=1) for day in range(1, 6)]
    found = trends.for_player(1, "A Hitter", logs, date(2026, 8, 5), CONFIG)
    assert any("hot over 7 days" in t.headline for t in found)


def test_cold_stretch_is_reported():
    logs = [hitting(day, hits=0, at_bats=4) for day in range(1, 6)]
    found = trends.for_player(1, "A Hitter", logs, date(2026, 8, 5), CONFIG)
    assert any("cold over 7 days" in t.headline for t in found)


def test_only_the_shortest_qualifying_window_is_reported():
    logs = [hitting(day, hits=3, at_bats=4, homeRuns=1) for day in range(1, 16)]
    found = trends.for_player(1, "A Hitter", logs, date(2026, 8, 15), CONFIG)
    assert len([t for t in found if "hot over" in t.headline]) == 1


def test_scoreless_run_is_reported_for_pitchers():
    logs = [pitching(day) for day in (1, 6, 11)]
    found = trends.for_player(2, "A Pitcher", logs, date(2026, 8, 11), CONFIG)
    assert any("3 straight scoreless outings" in t.headline for t in found)


def test_pitchers_do_not_get_hitting_trends():
    logs = [pitching(day) for day in (1, 6, 11)]
    found = trends.for_player(2, "A Pitcher", logs, date(2026, 8, 11), CONFIG)
    assert not any("hot over" in t.headline for t in found)


def test_no_logs_means_no_trends():
    assert trends.for_player(1, "Nobody", [], date(2026, 8, 1), CONFIG) == []
