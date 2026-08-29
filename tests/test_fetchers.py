from __future__ import annotations

from datetime import date

import pytest

from mlb_report import fetchers
from mlb_report.models import GameLog, Transaction
from mlb_report.prospects import Prospect

ORG = 136
TEAMS = [
    {"id": 529, "sport": {"id": 11}},
    {"id": 619, "sport": {"id": 12}},
]


@pytest.fixture
def api(monkeypatch):
    """Stub the Stats API so the fetch layer is exercised without network."""

    class Fake:
        def __init__(self):
            self.game_log_calls = []
            self.transactions_by_team = {}
            self.people_payload = [
                {"id": 703155, "currentTeam": {"id": 529}},
                {"id": 815549, "currentTeam": {"id": 619}},
            ]
            self.splits = []

        def affiliate_teams(self, org, season):
            return TEAMS

        def people(self, ids, hydrate=None):
            return [p for p in self.people_payload if p["id"] in ids]

        def game_log(self, player_id, group, season, sport_id):
            self.game_log_calls.append((player_id, group, sport_id))
            return self.splits

        def transactions(self, team_id, start, end):
            return self.transactions_by_team.get(team_id, [])

    fake = Fake()
    for name in ("affiliate_teams", "people", "game_log", "transactions"):
        monkeypatch.setattr(fetchers.statsapi, name, getattr(fake, name))
    return fake


def split(day=28, summary="2-4, HR", sport="AAA", game_pk=812345):
    return {
        "date": f"2026-08-{day}",
        "game": {"gamePk": game_pk},
        "player": {"fullName": "Lazaro Montes"},
        "team": {"name": "Tacoma Rainiers"},
        "opponent": {"name": "Salt Lake Bees"},
        "sport": {"abbreviation": sport},
        "stat": {"summary": summary, "hits": 2, "homeRuns": 1},
    }


def test_each_player_is_queried_at_their_current_level(api):
    api.splits = [split()]
    fetchers.game_logs(
        [
            Prospect(5, "Lazaro Montes", "OF", 703155),
            Prospect(2, "Ryan Sloan", "RHP", 815549),
        ],
        ORG,
        2026,
    )
    assert api.game_log_calls == [(703155, "hitting", 11), (815549, "pitching", 12)]


def test_unresolved_prospects_are_skipped_not_fetched(api):
    fetchers.game_logs([Prospect(28, "Chia-Shi Shen", "RHP")], ORG, 2026)
    assert api.game_log_calls == []


def test_players_with_no_known_team_are_skipped(api):
    api.people_payload = []
    fetchers.game_logs([Prospect(5, "Lazaro Montes", "OF", 703155)], ORG, 2026)
    assert api.game_log_calls == []


def test_splits_become_game_logs(api):
    api.splits = [split()]
    logs = fetchers.game_logs([Prospect(5, "Lazaro Montes", "OF", 703155)], ORG, 2026)
    assert logs == [
        GameLog(
            player_id=703155,
            player_name="Lazaro Montes",
            game_date=date(2026, 8, 28),
            game_pk=812345,
            group="hitting",
            level="AAA",
            team="Tacoma Rainiers",
            opponent="Salt Lake Bees",
            summary="2-4, HR",
            stat={"summary": "2-4, HR", "hits": 2, "homeRuns": 1},
        )
    ]


def move(player_id=703155, description="Tacoma Rainiers activated OF Lazaro Montes."):
    return {
        "person": {"id": player_id, "fullName": "Lazaro Montes"},
        "date": "2026-08-25",
        "effectiveDate": "2026-08-25",
        "typeDesc": "Status Change",
        "description": description,
    }


def test_only_tracked_players_moves_are_kept(api):
    api.transactions_by_team = {529: [move(), move(player_id=999)]}
    moves = fetchers.transactions(
        [Prospect(5, "Lazaro Montes", "OF", 703155)],
        ORG,
        2026,
        date(2026, 8, 20),
        date(2026, 8, 29),
    )
    assert [m.player_id for m in moves] == [703155]


def test_a_promotion_reported_by_both_clubs_appears_once(api):
    api.transactions_by_team = {529: [move()], 619: [move()]}
    moves = fetchers.transactions(
        [Prospect(5, "Lazaro Montes", "OF", 703155)],
        ORG,
        2026,
        date(2026, 8, 20),
        date(2026, 8, 29),
    )
    assert len(moves) == 1


def test_injury_moves_are_identified():
    placed = Transaction(
        1,
        "A Player",
        date(2026, 8, 1),
        "Status Change",
        "placed on the 7-day injured list.",
    )
    activated = Transaction(
        1, "A Player", date(2026, 8, 1), "Status Change", "activated from the roster."
    )
    assert placed.is_injury
    assert not activated.is_injury


def test_innings_pitched_thirds_convert_to_real_numbers():
    log = GameLog(
        player_id=1,
        player_name="A Pitcher",
        game_date=date(2026, 8, 1),
        game_pk=1,
        group="pitching",
        level="AA",
        team="Arkansas Travelers",
        opponent="Tulsa Drillers",
        summary="",
        stat={"inningsPitched": "5.2"},
    )
    assert log.innings_pitched == pytest.approx(5 + 2 / 3)


def test_a_player_in_the_majors_is_not_fetched(api):
    """
    His games are on television. Fetching them would put major league lines in
    the store, where they would surface as the day's line and feed streaks.
    """
    api.people_payload = [{"id": 703155, "currentTeam": {"id": ORG}}]

    logs = fetchers.game_logs([Prospect(1, "Promoted", "LHP", 703155)], ORG, 2026)

    assert api.game_log_calls == []
    assert logs == []


def test_the_majors_are_reported_as_a_promotion(api):
    """The parent club's own id maps to the majors, not to an affiliate level."""
    api.people_payload = [
        {"id": 703155, "currentTeam": {"id": ORG}},
        {"id": 815549, "currentTeam": {"id": 619}},
    ]
    levels = fetchers.current_levels(
        [
            Prospect(1, "Promoted", "LHP", 703155),
            Prospect(2, "Still Down", "OF", 815549),
        ],
        ORG,
        2026,
    )
    assert fetchers.in_majors(levels) == {703155}


def test_whiffs_are_only_looked_up_for_pitchers(monkeypatch):
    """One request per outing, and none at all for a night of hitters."""
    asked = []

    def fake(game_pk):
        asked.append(game_pk)
        return {77: 12}

    monkeypatch.setattr(fetchers.pitch_data, "whiffs_by_pitcher", fake)
    logs = [
        GameLog(77, "P", date(2026, 8, 28), 5001, "pitching", "AA", "T", "O", "", {}),
        GameLog(88, "H", date(2026, 8, 28), 5002, "hitting", "AA", "T", "O", "", {}),
    ]

    assert fetchers.whiffs_for_outings(logs) == {(77, 5001): 12}
    assert asked == [5001]


def test_a_game_that_cannot_be_read_is_skipped(monkeypatch):
    """The outing still has to render, reporting strikeouts alone."""

    def broken(game_pk):
        raise fetchers.statsapi.StatsApiError("no play-by-play")

    monkeypatch.setattr(fetchers.pitch_data, "whiffs_by_pitcher", broken)
    logs = [
        GameLog(77, "P", date(2026, 8, 28), 5001, "pitching", "AA", "T", "O", "", {})
    ]

    assert fetchers.whiffs_for_outings(logs) == {}


def raw_move(player_id, type_desc="Trade", to_team=529, from_team=145, person=True):
    entry = {
        "typeDesc": type_desc,
        "effectiveDate": "2026-07-30",
        "toTeam": {"id": to_team},
        "fromTeam": {"id": from_team},
        "description": "Traded to the Seattle Mariners.",
    }
    if person:
        entry["person"] = {"id": player_id, "fullName": "Boston Smith"}
    return entry


def test_a_player_joining_from_another_org_is_an_arrival(api):
    api.transactions_by_team = {529: [raw_move(695722)]}
    found, _ = fetchers.crossings(ORG, 2026, date(2026, 3, 1), date(2026, 8, 29))
    assert [a.player_id for a in found] == [695722]


def test_a_promotion_inside_the_org_is_not_an_arrival(api):
    """Both ends are ours, so nobody has actually joined."""
    api.transactions_by_team = {619: [raw_move(703155, to_team=619, from_team=529)]}
    assert fetchers.crossings(ORG, 2026, date(2026, 3, 1), date(2026, 8, 29))[0] == []


def test_a_departure_is_not_an_arrival(api):
    api.transactions_by_team = {529: [raw_move(703155, to_team=145, from_team=529)]}
    assert fetchers.crossings(ORG, 2026, date(2026, 3, 1), date(2026, 8, 29))[0] == []


def test_the_cash_in_a_trade_names_no_player_and_is_dropped(api):
    api.transactions_by_team = {529: [raw_move(None, person=False)]}
    assert fetchers.crossings(ORG, 2026, date(2026, 3, 1), date(2026, 8, 29))[0] == []


def test_a_minor_league_signing_is_not_treated_as_an_acquisition(api):
    """Mostly organizational depth, and it would bury the case worth catching."""
    api.transactions_by_team = {
        529: [raw_move(695722, type_desc="Signed as Free Agent")]
    }
    assert fetchers.crossings(ORG, 2026, date(2026, 3, 1), date(2026, 8, 29))[0] == []


def test_an_arrival_reported_by_two_clubs_is_listed_once(api):
    api.transactions_by_team = {529: [raw_move(695722)], 619: [raw_move(695722)]}
    found, _ = fetchers.crossings(ORG, 2026, date(2026, 3, 1), date(2026, 8, 29))
    assert len(found) == 1


def test_a_player_traded_out_of_the_org_is_a_departure(api):
    api.transactions_by_team = {529: [raw_move(703155, to_team=145, from_team=529)]}
    _, left = fetchers.crossings(ORG, 2026, date(2026, 3, 1), date(2026, 8, 29))
    assert [move.player_id for move in left] == [703155]


def test_an_arrival_is_not_also_counted_as_a_departure(api):
    api.transactions_by_team = {529: [raw_move(695722)]}
    joined, left = fetchers.crossings(ORG, 2026, date(2026, 3, 1), date(2026, 8, 29))
    assert [move.player_id for move in joined] == [695722]
    assert left == []


def test_a_promotion_is_neither_coming_nor_going(api):
    """Both ends are ours, so nothing crossed the boundary."""
    api.transactions_by_team = {619: [raw_move(703155, to_team=619, from_team=529)]}
    joined, left = fetchers.crossings(ORG, 2026, date(2026, 3, 1), date(2026, 8, 29))
    assert joined == [] and left == []


def split_payload(*clubs) -> dict:
    """The per-player feed, which reports each club and an unattributed total."""
    splits = [
        {"team": {"id": team}, "stat": {"plateAppearances": pa}} for team, pa in clubs
    ]
    total = sum(pa for _, pa in clubs)
    splits.insert(0, {"stat": {"plateAppearances": total}})
    return {"stats": [{"splits": splits}]}


def test_a_traded_player_reports_time_at_each_club(monkeypatch):
    monkeypatch.setattr(
        fetchers.statsapi, "get", lambda *a, **k: split_payload((247, 97), (574, 89))
    )
    assert fetchers.club_shares(695722, "hitting", 2026, 12) == {247: 97.0, 574: 89.0}


def test_the_ordinary_one_club_season_needs_no_blending(monkeypatch):
    monkeypatch.setattr(
        fetchers.statsapi, "get", lambda *a, **k: split_payload((574, 186))
    )
    assert fetchers.club_shares(807739, "hitting", 2026, 12) == {}


def test_a_club_he_never_played_for_is_not_a_share(monkeypatch):
    monkeypatch.setattr(
        fetchers.statsapi, "get", lambda *a, **k: split_payload((247, 97), (574, 0))
    )
    assert fetchers.club_shares(695722, "hitting", 2026, 12) == {}


def test_a_pitcher_is_weighted_by_batters_faced(monkeypatch):
    monkeypatch.setattr(
        fetchers.statsapi,
        "get",
        lambda *a, **k: {
            "stats": [
                {
                    "splits": [
                        {"team": {"id": 1}, "stat": {"battersFaced": 200}},
                        {"team": {"id": 2}, "stat": {"battersFaced": 100}},
                    ]
                }
            ]
        },
    )
    assert fetchers.club_shares(1, "pitching", 2026, 12) == {1: 200.0, 2: 100.0}
