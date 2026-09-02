from __future__ import annotations

from datetime import date

from mlb_report import digest as digest_module
from mlb_report.models import GameLog, Transaction
from mlb_report.prospects import Prospect
from mlb_report.rankings import Ranked

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


def all_played(digest):
    return [line for lines in digest.played.values() for line in lines]


def test_a_season_line_is_written_for_every_watchlist_prospect():
    """Whether or not he played — the season is the standing context."""
    digest = build([hitting(2)])
    assert len(digest.seasons) == 2


def test_only_players_who_played_appear_under_a_level():
    digest = build([hitting(2)])
    played = all_played(digest)
    assert len(played) == 1
    assert "Lazaro Montes" in played[0]


def test_levels_are_ordered_with_the_highest_first():
    digest = build([pitching(1), hitting(2)])
    assert list(digest.played) == ["AAA", "AA"]


def test_both_games_of_a_doubleheader_land_on_one_line():
    """A player should appear once wherever the reader looks for him."""
    digest = build([hitting(2), hitting(2, summary="1-3")])
    played = all_played(digest)
    assert len(played) == 1
    assert "1-3" in played[0] and "2-4, HR" in played[0]


def test_pitchers_get_a_pitching_line():
    digest = build([pitching(1)])
    line = all_played(digest)[0]
    assert "6.0 IP" in line and "8 K" in line


def test_below_the_watchlist_only_the_notable_get_in():
    digest = build([hitting(2, hits=4), hitting(3, hits=4)])
    played = all_played(digest)
    assert len(played) == 2
    assert digest.standouts == 1


def test_quiet_games_outside_the_watchlist_are_omitted():
    digest = build([hitting(3, hits=1, summary="1-4")])
    assert all_played(digest) == []


def test_a_quiet_game_inside_the_watchlist_is_still_shown():
    """The watchlist is read every day, not only on the good days."""
    digest = build([hitting(2, hits=1, summary="1-4")])
    assert len(all_played(digest)) == 1
    assert digest.standouts == 0


def test_a_home_run_is_notable():
    digest = build([hitting(3, hits=1, homeRuns=1, summary="1-4, HR")])
    assert digest.standouts == 1


def test_a_strikeout_heavy_start_is_notable():
    digest = build([pitching(4, strikeOuts=9)])
    assert digest.standouts == 1


def test_a_short_scoreless_relief_outing_is_notable():
    digest = build([pitching(4, strikeOuts=2, earnedRuns=0, inningsPitched="2.0")])
    assert digest.standouts == 1


def test_a_scoreless_single_inning_is_not_notable():
    digest = build([pitching(4, strikeOuts=1, earnedRuns=0, inningsPitched="1.0")])
    assert digest.standouts == 0


def test_form_rides_along_on_the_season_line_as_an_arrow():
    """Read as a direction rather than as a sentence in its own section."""
    history = [hitting(2, day=day, hits=1, summary="1-4") for day in range(20, 29)]
    digest = build(history)
    montes = next(entry for entry in digest.seasons if "Lazaro Montes" in entry)
    assert "↑" in montes
    assert "hit streak" in montes


def test_form_is_only_computed_for_the_watchlist():
    history = [hitting(3, day=day, hits=1, summary="1-4") for day in range(20, 29)]
    digest = build(history)
    assert not any("hit streak" in entry for entry in digest.seasons)


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
        Transaction(
            4,
            "Lazaro Montes",
            REPORT_DATE,
            "Selected",
            "Seattle Mariners selected the contract of RF Lazaro Montes "
            "from Tacoma Rainiers.",
        ),
    ]
    digest = build(moves=moves)
    assert "**Injury**" in digest.moves[0]
    assert "**Optioned**" in digest.moves[1]
    assert "**Promoted**" in digest.moves[2]
    assert "**Selected**" not in digest.moves[2]


def test_unresolved_prospects_are_flagged_as_a_note():
    digest = digest_module.build(
        REPORT_DATE, [Prospect(1, "Unrostered Kid", "RHP")], [], [], SETTINGS
    )
    assert digest.warnings
    assert "Unrostered Kid" in digest.warnings[0]


def test_a_digest_with_only_the_watchlist_playing_counts_as_quiet():
    """They play most days; that on its own is not why an email should arrive."""
    assert build([hitting(2, hits=1, summary="1-4")]).is_empty
    assert not build([hitting(3, hits=4)]).is_empty


def test_render_includes_every_section():
    output = digest_module.render(build([hitting(2)]))
    for heading in ("Played yesterday", "Top 10 season lines", "Moves and injuries"):
        assert f"## {heading}" in output


def test_render_puts_each_level_under_its_own_heading():
    output = digest_module.render(build([pitching(1), hitting(2)]))
    levels = [
        line.removeprefix("### ").split(" (")[0]
        for line in output.splitlines()
        if line.startswith("### ")
    ]
    assert levels == ["AAA", "AA"]


def test_a_level_where_everyone_faced_one_club_names_it_in_the_heading():
    """One club plays one opponent a day, so the line beneath need not repeat it."""
    output = digest_module.render(build([pitching(1)]))
    assert "### AA (vs Tulsa Drillers)" in output
    # Named once, by the heading, rather than again on the line beneath it.
    assert output.count("Tulsa Drillers") == 1


def test_render_notes_empty_sections_rather_than_dropping_them():
    output = digest_module.render(build())
    assert "_No roster moves._" in output
    assert "Friday 28 August 2026" in output


def test_a_promoted_player_is_marked_on_his_season_line():
    """His major league games are on television; the digest stays in the minors."""
    digest = digest_module.build(
        report_date=REPORT_DATE,
        tracked=TOP_FOUR,
        history=[],
        moves=[],
        settings=SETTINGS,
        contexts={
            2: digest_module.PlayerContext(
                production="AAA (PCL): 119 wRC+ in 194 PA", promoted=True
            )
        },
    )
    entry = next(line for line in digest.seasons if "Lazaro Montes" in line)
    assert "promoted to MLB" in entry
    # The season still reads as the last thing he did in the minors.
    assert "AAA (PCL): 119 wRC+ in 194 PA" in entry


def test_a_player_still_in_the_minors_carries_no_promotion_note():
    digest = digest_module.build(
        report_date=REPORT_DATE,
        tracked=TOP_FOUR,
        history=[hitting(2)],
        moves=[],
        settings=SETTINGS,
        contexts={2: digest_module.PlayerContext(promoted=False)},
    )
    entry = next(line for line in digest.seasons if "Lazaro Montes" in line)
    assert "promoted to MLB" not in entry
    assert "2-4, HR" in all_played(digest)[0]


def test_a_pitching_line_carries_whiffs_when_they_are_known():
    """Six strikeouts on eight whiffs is a different night from six on eighteen."""
    log = pitching(4, strikeOuts=9)
    digest = digest_module.build(
        REPORT_DATE,
        TOP_FOUR,
        [log],
        [],
        SETTINGS,
        whiffs={(4, log.game_pk): 18},
    )
    assert "9 K (18 whiffs)" in all_played(digest)[0]


def test_a_pitching_line_without_whiffs_reports_strikeouts_alone():
    """Play-by-play is not always readable, and the line still has to render."""
    digest = build([pitching(4, strikeOuts=9)])
    line = all_played(digest)[0]
    assert "9 K" in line
    assert "whiffs" not in line


def test_whiffs_belong_to_one_pitcher_in_one_game():
    """The key is the outing, so a doubleheader does not share a whiff count."""
    first, second = pitching(4, strikeOuts=9), pitching(4, day=27, strikeOuts=2)
    digest = digest_module.build(
        REPORT_DATE,
        TOP_FOUR,
        [first, second],
        [],
        SETTINGS,
        whiffs={(4, second.game_pk): 5},
    )
    assert "whiffs" not in all_played(digest)[0]


def acquired():
    transaction = Transaction(
        player_id=695722,
        player_name="Boston Smith",
        effective_date=date(2026, 7, 30),
        type_desc="Trade",
        description="Traded to the Seattle Mariners.",
    )
    entry = Ranked(
        player_id=695722,
        name="Boston Smith",
        position="C",
        rank=4,
        org_name="Chicago White Sox",
        org_abbreviation="CWS",
    )
    return [(transaction, entry)]


def test_an_arrival_is_reported_by_where_he_was_ranked():
    """A club's own top 30 is the closest thing to a verdict on a player."""
    digest = digest_module.build(
        report_date=REPORT_DATE,
        tracked=TOP_FOUR,
        history=[],
        moves=[],
        settings=SETTINGS,
        arrivals=acquired(),
    )
    assert digest.arrivals == [
        "**C [Boston Smith](https://www.mlb.com/player/695722)** — "
        "CWS No. 4, acquired 30 July"
    ]
    assert "## New in the system" in digest_module.render(digest)


def test_a_new_prospect_is_reason_enough_to_send():
    digest = digest_module.build(
        report_date=REPORT_DATE,
        tracked=TOP_FOUR,
        history=[],
        moves=[],
        settings=SETTINGS,
        arrivals=acquired(),
    )
    assert not digest.is_empty


def test_the_arrivals_heading_is_absent_on_a_day_without_one():
    """An empty heading every day trains the reader to skip it."""
    assert "New in the system" not in digest_module.render(build())


def test_a_player_is_linked_to_his_page():
    output = digest_module.render(build([hitting(2)]))
    assert "[Lazaro Montes](https://www.mlb.com/player/2)" in output


def test_a_player_without_an_id_is_named_but_not_linked():
    """An unassigned draftee has no page, and a guessed link is worse than none."""
    assert digest_module._named("RHP", "Nobody Yet", None) == "RHP Nobody Yet"
