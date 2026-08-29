from __future__ import annotations

import json
from datetime import date

import pytest

from mlb_report import prospects
from mlb_report.models import Transaction
from mlb_report.prospects import Prospect
from mlb_report.rankings import Ranked


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


def acquisition(player_id: int, name: str = "Boston Smith") -> Transaction:
    return Transaction(
        player_id=player_id,
        player_name=name,
        effective_date=date(2026, 7, 30),
        type_desc="Trade",
        description=f"{name} traded to the Seattle Mariners.",
    )


def ranked(player_id: int, rank: int, position: str = "C") -> Ranked:
    return Ranked(
        player_id=player_id,
        name="Boston Smith",
        position=position,
        rank=rank,
        org_name="Chicago White Sox",
        org_abbreviation="CWS",
    )


def test_an_acquired_prospect_joins_the_tracked_list():
    tracked = [Prospect(1, "Kade Anderson", "LHP", 807739)]
    extended, acquired = prospects.with_acquisitions(
        tracked, [acquisition(695722)], {695722: ranked(695722, 4)}
    )
    assert [p.player_id for p in extended] == [807739, 695722]
    assert extended[-1].position == "C"
    assert acquired[0][1].describe() == "CWS No. 4"


def test_an_acquisition_nobody_ranked_is_left_alone():
    """Most players changing organizations are depth, and not worth following."""
    tracked = [Prospect(1, "Kade Anderson", "LHP", 807739)]
    extended, acquired = prospects.with_acquisitions(
        tracked, [acquisition(111111, "A Reliever")], {}
    )
    assert extended == tracked
    assert acquired == []


def test_an_acquisition_is_added_below_the_committed_list():
    """
    Another club's opinion should not push a player into our watchlist, which
    is the top ten of a ranking somebody made about this organization.
    """
    tracked = [Prospect(rank, f"Player {rank}", "OF", rank) for rank in range(1, 31)]
    extended, _ = prospects.with_acquisitions(
        tracked, [acquisition(695722)], {695722: ranked(695722, 1)}
    )
    assert extended[-1].rank == 31


def test_the_best_acquisition_is_listed_first():
    tracked = [Prospect(1, "Kade Anderson", "LHP", 807739)]
    extended, _ = prospects.with_acquisitions(
        tracked,
        [acquisition(222), acquisition(111)],
        {222: ranked(222, 20), 111: ranked(111, 3)},
    )
    assert [p.player_id for p in extended[1:]] == [111, 222]


def test_a_player_already_tracked_is_not_added_twice():
    """A prospect can be reacquired, and the ranking may already carry him."""
    tracked = [Prospect(13, "Boston Smith", "C", 695722)]
    extended, acquired = prospects.with_acquisitions(
        tracked, [acquisition(695722)], {695722: ranked(695722, 4)}
    )
    assert extended == tracked
    assert acquired == []


def departure(player_id: int, name: str = "Traded Away") -> Transaction:
    return Transaction(
        player_id=player_id,
        player_name=name,
        effective_date=date(2026, 7, 30),
        type_desc="Trade",
        description=f"{name} traded to the Chicago White Sox.",
    )


def test_a_prospect_traded_away_stops_being_tracked():
    tracked = [
        Prospect(1, "Kade Anderson", "LHP", 807739),
        Prospect(2, "Ryan Sloan", "RHP", 815549),
    ]
    remaining, departed = prospects.without_departures(tracked, [departure(815549)])
    assert [p.player_id for p in remaining] == [807739]
    assert [move.player_id for move in departed] == [815549]


def test_ranks_are_left_alone_when_somebody_leaves():
    """Pipeline's numbering is not ours to close up; a gap is the truer record."""
    tracked = [Prospect(rank, f"Player {rank}", "OF", rank) for rank in range(1, 4)]
    remaining, _ = prospects.without_departures(tracked, [departure(2)])
    assert [p.rank for p in remaining] == [1, 3]


def test_a_departure_of_someone_untracked_changes_nothing():
    tracked = [Prospect(1, "Kade Anderson", "LHP", 807739)]
    remaining, departed = prospects.without_departures(tracked, [departure(999999)])
    assert remaining == tracked
    assert departed == []
