from __future__ import annotations

from datetime import date, timedelta

from . import pitch_data, statsapi
from .models import GameLog, Transaction
from .prospects import Prospect

MLB_SPORT_ID = 1


def _sport_by_team(parent_org_id: int, season: int) -> dict[int, int]:
    """Team id to sport id for the whole organization, majors included."""
    mapping = {
        team["id"]: team["sport"]["id"]
        for team in statsapi.affiliate_teams(parent_org_id, season)
    }
    mapping[parent_org_id] = MLB_SPORT_ID
    return mapping


def current_levels(prospects: list[Prospect], parent_org_id: int, season: int) -> dict:
    """
    The sport id each tracked prospect is currently playing at.

    Game logs must be requested one level at a time, so knowing where a player
    is now keeps the daily run to roughly one request per player instead of one
    per player per level.
    """
    player_ids = [p.player_id for p in prospects if p.player_id]
    sport_by_team = _sport_by_team(parent_org_id, season)
    levels = {}
    for person in statsapi.people(player_ids, hydrate="currentTeam"):
        team_id = person.get("currentTeam", {}).get("id")
        if sport_id := sport_by_team.get(team_id):
            levels[person["id"]] = sport_id
    return levels


def in_majors(levels: dict[int, int]) -> set[int]:
    """Tracked players currently on the big league roster."""
    return {
        player_id for player_id, sport_id in levels.items() if sport_id == MLB_SPORT_ID
    }


def game_logs(
    prospects: list[Prospect],
    parent_org_id: int,
    season: int,
    levels: dict[int, int] | None = None,
) -> list[GameLog]:
    """
    Fetch every tracked prospect's log at their current level, majors excluded.

    A prospect who reaches Seattle stops being something this digest can tell
    you anything useful about — those games are on television. His minor league
    season stays as the last thing worth reporting.
    """
    if levels is None:
        levels = current_levels(prospects, parent_org_id, season)
    logs: list[GameLog] = []
    for prospect in prospects:
        sport_id = levels.get(prospect.player_id)
        if prospect.player_id is None or sport_id is None:
            continue
        if sport_id == MLB_SPORT_ID:
            continue
        group = "pitching" if prospect.is_pitcher else "hitting"
        splits = statsapi.game_log(prospect.player_id, group, season, sport_id)
        logs.extend(
            GameLog.from_split(prospect.player_id, group, split) for split in splits
        )
    return logs


def whiffs_for_outings(logs: list[GameLog]) -> dict[tuple[int, int], int]:
    """
    Whiffs by pitcher and game, for one day's outings.

    This is the only play-by-play the daily run touches, and it is bounded by
    how many tracked pitchers threw yesterday — a handful of requests, not the
    season-scale pass the park factors need. A game that cannot be read is
    simply left out, and the line reports strikeouts alone.
    """
    wanted = {log.game_pk for log in logs if log.is_pitching}
    found: dict[tuple[int, int], int] = {}
    for game_pk in sorted(wanted):
        try:
            by_pitcher = pitch_data.whiffs_by_pitcher(game_pk)
        except statsapi.StatsApiError:
            continue
        for pitcher, whiffs in by_pitcher.items():
            found[(pitcher, game_pk)] = whiffs
    return found


def transactions(
    prospects: list[Prospect],
    parent_org_id: int,
    season: int,
    since: date,
    until: date,
) -> list[Transaction]:
    """
    Moves affecting tracked prospects across the whole organization.

    Both ends of a promotion appear in the feed — the club a player left and the
    one he joined — so results are deduplicated on the transaction text.
    """
    tracked = {p.player_id: p for p in prospects if p.player_id}
    team_ids = [t["id"] for t in statsapi.affiliate_teams(parent_org_id, season)]
    team_ids.append(parent_org_id)

    seen: set[tuple[int, str, str]] = set()
    moves: list[Transaction] = []
    for team_id in team_ids:
        for raw in statsapi.transactions(team_id, since.isoformat(), until.isoformat()):
            player_id = raw.get("person", {}).get("id")
            if player_id not in tracked:
                continue
            effective = raw.get("effectiveDate") or raw.get("date")
            key = (player_id, effective, raw.get("description", ""))
            if key in seen:
                continue
            seen.add(key)
            moves.append(
                Transaction(
                    player_id=player_id,
                    player_name=raw.get("person", {}).get("fullName", ""),
                    effective_date=date.fromisoformat(effective),
                    type_desc=raw.get("typeDesc", ""),
                    description=raw.get("description", ""),
                )
            )
    return sorted(moves, key=lambda m: (m.effective_date, m.player_name))


def lookback_window(as_of: date, days: int) -> tuple[date, date]:
    return as_of - timedelta(days=days), as_of
