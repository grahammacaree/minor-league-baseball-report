from __future__ import annotations

import json
from datetime import date

import pytest

from mlb_report import prospects
from mlb_report.prospects import Prospect


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def bundled_config(monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", "/nonexistent")


def test_committed_list_is_a_complete_top_30(bundled_config):
    ranked = prospects.load_ranked_list()
    assert [p.rank for p in ranked] == list(range(1, 31))
    assert all(p.name and p.position for p in ranked)


def test_pitchers_are_identified_by_position():
    assert Prospect(1, "Kade Anderson", "LHP").is_pitcher
    assert not Prospect(3, "Michael Arroyo", "OF/2B").is_pitcher


def test_missing_ids_are_looked_up_and_cached(config_home, monkeypatch):
    calls = []

    def fake_sport_players(sport_id, season):
        calls.append(sport_id)
        return [{"id": 999, "fullName": "Chia-Shi Shen"}]

    monkeypatch.setattr(prospects.statsapi, "sport_players", fake_sport_players)

    resolved = prospects.resolve_player_ids(
        [
            Prospect(28, "Chia-Shi Shen", "RHP"),
            Prospect(1, "Kade Anderson", "LHP", 807739),
        ],
        season=2026,
    )

    assert resolved[0].player_id == 999
    assert resolved[1].player_id == 807739
    assert calls, "expected a roster lookup for the unresolved prospect"

    calls.clear()
    prospects.resolve_player_ids([Prospect(28, "Chia-Shi Shen", "RHP")], season=2026)
    assert not calls, "cached ids should avoid a second roster fetch"


def test_lookup_folds_accents(config_home, monkeypatch):
    monkeypatch.setattr(
        prospects.statsapi,
        "sport_players",
        lambda sport_id, season: [{"id": 42, "fullName": "Lázaro Montes"}],
    )
    resolved = prospects.resolve_player_ids([Prospect(5, "Lazaro Montes", "OF")], 2026)
    assert resolved[0].player_id == 42


def test_unmatched_prospects_survive_unresolved(config_home, monkeypatch):
    monkeypatch.setattr(prospects.statsapi, "sport_players", lambda s, y: [])
    resolved = prospects.resolve_player_ids(
        [Prospect(30, "Nobody At All", "RHP")], 2026
    )
    assert len(resolved) == 1
    assert resolved[0].player_id is None


def test_no_network_when_every_id_is_known(config_home, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("should not hit the network")

    monkeypatch.setattr(prospects.statsapi, "sport_players", explode)
    resolved = prospects.resolve_player_ids(
        [Prospect(1, "Kade Anderson", "LHP", 807739)], 2026
    )
    assert resolved[0].player_id == 807739


def test_corrupt_cache_is_ignored(config_home, monkeypatch):
    cache_dir = config_home / "data"
    cache_dir.mkdir()
    (cache_dir / "resolved_player_ids.json").write_text("{not json")
    monkeypatch.setattr(
        prospects.statsapi,
        "sport_players",
        lambda s, y: [{"id": 7, "fullName": "Griffin Hugus"}],
    )
    resolved = prospects.resolve_player_ids(
        [Prospect(15, "Griffin Hugus", "RHP")], 2026
    )
    assert resolved[0].player_id == 7
    assert json.loads((cache_dir / "resolved_player_ids.json").read_text())


def test_committed_list_records_when_it_was_captured(bundled_config):
    assert prospects.captured_on() == date(2026, 8, 29)


def test_refresh_is_due_once_a_ranking_update_has_passed(bundled_config):
    captured = date(2026, 4, 2)
    assert not prospects.refresh_due(captured, as_of=date(2026, 4, 10))
    assert not prospects.refresh_due(captured, as_of=date(2026, 7, 20))
    assert prospects.refresh_due(captured, as_of=date(2026, 8, 5))


def test_refresh_is_due_when_the_list_predates_this_season(bundled_config):
    assert prospects.refresh_due(date(2025, 8, 1), as_of=date(2026, 4, 10))
