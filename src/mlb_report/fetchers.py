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
    Moves affecting tracked prospects.

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
            if not effective:
                continue
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

    return sorted(moves, key=lambda move: (move.effective_date, move.player_name))


# Ways a player crosses an organization's boundary. Minor-league free agent
# signings are left out: they are mostly depth, and would bury the case this is
# here to catch — a ranked prospect moving between capture points.
CROSSING_TYPES = ("Trade", "Claimed Off Waivers", "Rule 5 Draft", "Selected")


def crossings(
    parent_org_id: int,
    season: int,
    since: date,
    until: date,
) -> tuple[list[Transaction], list[Transaction]]:
    """
    Players who joined the organization from outside it, and who left it.

    The rankings are captured twice a year, so a prospect acquired in July is
    invisible to a list committed in March, and one traded away in July stays on
    it long after he stopped being ours. Both directions are read from the same
    scan, since the feed has to be walked either way.

    A move within the organization has both clubs inside it, so comparing the
    two ends is what separates a crossing from a promotion.
    """
    inside = {team["id"] for team in statsapi.affiliate_teams(parent_org_id, season)}
    inside.add(parent_org_id)

    def ends(raw: dict) -> tuple[bool, bool] | None:
        if raw.get("typeDesc") not in CROSSING_TYPES:
            return None
        # A trade carries a row for the cash as well as for the players, and
        # that one names no person.
        if not raw.get("person", {}).get("id"):
            return None
        to_inside = (raw.get("toTeam") or {}).get("id") in inside
        from_inside = (raw.get("fromTeam") or {}).get("id") in inside
        return to_inside, from_inside

    def build(raw: dict, effective: str) -> Transaction:
        return Transaction(
            player_id=raw["person"]["id"],
            player_name=raw.get("person", {}).get("fullName", ""),
            effective_date=date.fromisoformat(effective),
            type_desc=raw.get("typeDesc", ""),
            description=raw.get("description", ""),
        )

    seen: set[tuple[int, str]] = set()
    joined: list[Transaction] = []
    left: list[Transaction] = []
    for team_id in sorted(inside):
        for raw in statsapi.transactions(team_id, since.isoformat(), until.isoformat()):
            effective = raw.get("effectiveDate") or raw.get("date")
            if not effective:
                continue
            crossing = ends(raw)
            if crossing is None:
                continue
            to_inside, from_inside = crossing
            if to_inside == from_inside:
                continue  # internal move, or nothing to do with us
            key = (raw["person"]["id"], effective)
            if key in seen:
                continue
            seen.add(key)
            (joined if to_inside else left).append(build(raw, effective))

    def order(move: Transaction) -> tuple[date, str]:
        return move.effective_date, move.player_name

    return sorted(joined, key=order), sorted(left, key=order)


def lookback_window(as_of: date, days: int) -> tuple[date, date]:
    return as_of - timedelta(days=days), as_of
