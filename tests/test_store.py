from __future__ import annotations

from datetime import date

import pytest

from mlb_report import store
from mlb_report.models import GameLog


@pytest.fixture(autouse=True)
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    return tmp_path


def log(player_id=1, day=1, group="hitting", summary="1-4", game_pk=None):
    return GameLog(
        player_id=player_id,
        player_name="Test Player",
        game_date=date(2026, 8, day),
        game_pk=game_pk if game_pk is not None else 700000 + day,
        group=group,
        level="AA",
        team="Arkansas Travelers",
        opponent="Tulsa Drillers",
        summary=summary,
        stat={"hits": 1},
    )


def test_missing_history_reads_as_empty():
    assert store.load(2026) == []


def test_saving_reports_only_new_rows():
    assert store.save(2026, [log(day=1), log(day=2)]) == 2
    assert store.save(2026, [log(day=2), log(day=3)]) == 1
    assert len(store.load(2026)) == 3


def test_a_corrected_line_replaces_the_earlier_one():
    store.save(2026, [log(day=1, summary="1-4")])
    store.save(2026, [log(day=1, summary="2-4")])

    history = store.load(2026)
    assert len(history) == 1
    assert history[0].summary == "2-4"


def test_both_ends_of_a_doubleheader_are_kept():
    store.save(2026, [log(day=1, game_pk=1), log(day=1, game_pk=2)])
    assert len(store.load(2026)) == 2


def test_hitting_and_pitching_on_one_day_are_separate_rows():
    store.save(2026, [log(day=1, group="hitting"), log(day=1, group="pitching")])
    assert len(store.load(2026)) == 2


def test_history_round_trips_through_disk():
    store.save(2026, [log()])
    restored = store.load(2026)[0]
    assert restored == log()


def test_since_filters_to_the_window():
    store.save(2026, [log(day=1), log(day=10), log(day=20)])
    recent = store.since(2026, days=7, as_of=date(2026, 8, 20))
    assert [entry.game_date.day for entry in recent] == [20]


def test_rows_from_an_older_schema_are_dropped_not_fatal(config_home):
    store.save(2026, [log(day=1)])
    path = config_home / "data" / "game_logs_2026.ndjson"
    path.write_text(path.read_text() + '{"player_id": 2, "game_date": "2026-08-02"}\n')

    history = store.load(2026)
    assert [entry.player_id for entry in history] == [1]


def test_seasons_are_stored_separately():
    store.save(2026, [log()])
    assert store.load(2025) == []
