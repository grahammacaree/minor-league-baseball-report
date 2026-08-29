from __future__ import annotations

from datetime import date, timedelta

from . import statsapi
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


def game_logs(
    prospects: list[Prospect],
    parent_org_id: int,
    season: int,
) -> list[GameLog]:
    """Fetch every tracked prospect's log at their current level."""
    levels = current_levels(prospects, parent_org_id, season)
    logs: list[GameLog] = []
    for prospect in prospects:
        sport_id = levels.get(prospect.player_id)
        if prospect.player_id is None or sport_id is None:
            continue
        group = "pitching" if prospect.is_pitcher else "hitting"
        splits = statsapi.game_log(prospect.player_id, group, season, sport_id)
        logs.extend(
            GameLog.from_split(prospect.player_id, group, split) for split in splits
        )
    return logs


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
