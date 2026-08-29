from __future__ import annotations

from datetime import date

from mlb_report import digest as digest_module
from mlb_report.models import GameLog, Transaction
from mlb_report.prospects import Prospect

REPORT_DATE = date(2026, 8, 28)

SETTINGS = {
    "depth": {"watchlist": 2, "notable": 4},
    "notable_thresholds": {
        "hits": 2,
        "extra_base_hits": 2,
        "home_runs": 1,
        "rbi": 3,
        "stolen_bases": 2,
        "strikeouts_pitched": 6,
        "scoreless_innings_relief": 2,
    },
    "trends": {
        "min_hit_streak": 5,
        "rolling_windows_days": [7],
        "min_rolling_plate_appearances": 100,
        "min_rolling_ops": 0.9,
        "max_rolling_ops": 0.55,
        "min_scoreless_outings": 3,
    },
}

TOP_FOUR = [
    Prospect(1, "Kade Anderson", "LHP", 1),
    Prospect(2, "Lazaro Montes", "OF", 2),
    Prospect(3, "Henry Ford", "3B", 3),
    Prospect(4, "Ryan Sloan", "RHP", 4),
]


def hitting(player_id, day=28, **stat):
    return GameLog(
        player_id=player_id,
        player_name="Hitter",
        game_date=date(2026, 8, day),
        game_pk=900000 + day,
        group="hitting",
        level="AAA",
        team="Tacoma Rainiers",
        opponent="Salt Lake Bees",
        summary=stat.pop("summary", "2-4, HR"),
        stat={"hits": 2, "atBats": 4, "plateAppearances": 4, **stat},
    )


def pitching(player_id, day=28, **stat):
    return GameLog(
        player_id=player_id,
        player_name="Pitcher",
        game_date=date(2026, 8, day),
        game_pk=910000 + day,
        group="pitching",
        level="AA",
        team="Arkansas Travelers",
        opponent="Tulsa Drillers",
        summary="",
        stat={
            "inningsPitched": "6.0",
            "strikeOuts": 8,
            "earnedRuns": 1,
            "hits": 3,
            "runs": 1,
            "baseOnBalls": 2,
            **stat,
        },
    )


def build(history=(), moves=()):
    return digest_module.build(
        REPORT_DATE, TOP_FOUR, list(history), list(moves), SETTINGS
    )


def test_watchlist_covers_every_top_ranked_prospect():
    digest = build([hitting(2)])
    assert len(digest.watchlist) == 2


def test_watchlist_says_so_when_a_prospect_did_not_play():
    digest = build([hitting(2)])
    assert "did not play" in digest.watchlist[0]
    assert "did not play" not in digest.watchlist[1]


def test_watchlist_shows_both_games_of_a_doubleheader():
    digest = build([hitting(2), hitting(2, summary="1-3")])
    assert digest.watchlist[1].count("—") >= 1
    assert "1-3" in digest.watchlist[1]


def test_pitchers_get_a_pitching_line():
    digest = build([pitching(1)])
    assert "6.0 IP" in digest.watchlist[0]
    assert "8 K" in digest.watchlist[0]


def test_notable_only_covers_ranks_below_the_watchlist():
    digest = build([hitting(2, hits=4), hitting(3, hits=4)])
    assert len(digest.notable) == 1
    assert "Henry Ford" in digest.notable[0]


def test_quiet_games_outside_the_watchlist_are_omitted():
    digest = build([hitting(3, hits=1, summary="1-4")])
    assert digest.notable == []


def test_a_home_run_is_notable():
    digest = build([hitting(3, hits=1, homeRuns=1, summary="1-4, HR")])
    assert len(digest.notable) == 1


def test_a_strikeout_heavy_start_is_notable():
    digest = build([pitching(4, strikeOuts=9)])
    assert len(digest.notable) == 1


def test_a_short_scoreless_relief_outing_is_notable():
    digest = build([pitching(4, strikeOuts=2, earnedRuns=0, inningsPitched="2.0")])
    assert len(digest.notable) == 1


def test_a_scoreless_single_inning_is_not_notable():
    digest = build([pitching(4, strikeOuts=1, earnedRuns=0, inningsPitched="1.0")])
    assert digest.notable == []


def test_trends_read_the_whole_history_not_just_today():
    history = [hitting(3, day=day, hits=1, summary="1-4") for day in range(20, 29)]
    digest = build(history)
    assert any("hit streak" in line for line in digest.trends)


def test_moves_are_listed_with_injuries_labelled():
    moves = [
        Transaction(
            2,
            "Lazaro Montes",
            REPORT_DATE,
            "Status Change",
            "placed on the injured list.",
        ),
        Transaction(3, "Henry Ford", REPORT_DATE, "Optioned", "optioned to Everett."),
    ]
    digest = build(moves=moves)
    assert "**Injury**" in digest.moves[0]
    assert "**Optioned**" in digest.moves[1]


def test_unresolved_prospects_are_flagged_as_a_note():
    digest = digest_module.build(
        REPORT_DATE, [Prospect(1, "Unrostered Kid", "RHP")], [], [], SETTINGS
    )
    assert digest.warnings
    assert "Unrostered Kid" in digest.warnings[0]


def test_a_digest_with_only_a_watchlist_counts_as_empty():
    assert build([hitting(2, hits=1, summary="1-4")]).is_empty
    assert not build([hitting(3, hits=4)]).is_empty


def test_render_includes_every_section():
    output = digest_module.render(build([hitting(2)]))
    for heading in (
        "Watchlist",
        "Notable performances",
        "Trends and streaks",
        "Moves and injuries",
    ):
        assert f"## {heading}" in output


def test_render_notes_empty_sections_rather_than_dropping_them():
    output = digest_module.render(build())
    assert "_No roster moves._" in output
    assert "Friday 28 August 2026" in output


def test_a_promoted_player_shows_the_note_not_his_day():
    """His major league games are on television; the digest stays in the minors."""
    digest = digest_module.build(
        report_date=REPORT_DATE,
        tracked=TOP_FOUR,
        history=[hitting(2)],
        moves=[],
        settings=SETTINGS,
        contexts={
            2: digest_module.PlayerContext(
                production="AAA (PCL): 119 wRC+ in 194 PA", promoted=True
            )
        },
    )
    entry = next(line for line in digest.watchlist if "Lazaro Montes" in line)
    assert "promoted to MLB" in entry
    assert "2-4, HR" not in entry
    # The season still reads as the last thing he did in the minors.
    assert "AAA (PCL): 119 wRC+ in 194 PA" in entry


def test_a_player_still_in_the_minors_shows_his_day():
    digest = digest_module.build(
        report_date=REPORT_DATE,
        tracked=TOP_FOUR,
        history=[hitting(2)],
        moves=[],
        settings=SETTINGS,
        contexts={2: digest_module.PlayerContext(promoted=False)},
    )
    entry = next(line for line in digest.watchlist if "Lazaro Montes" in line)
    assert "promoted to MLB" not in entry
    assert "2-4, HR" in entry
