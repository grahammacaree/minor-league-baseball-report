from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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

    wanted = []
    for prospect in prospects:
        sport_id = levels.get(prospect.player_id)
        if prospect.player_id is None or sport_id is None:
            continue
        if sport_id == MLB_SPORT_ID:
            continue
        group = "pitching" if prospect.is_pitcher else "hitting"
        wanted.append((prospect.player_id, group, sport_id))

    def fetch(request: tuple[int, str, int]) -> list[GameLog]:
        player_id, group, sport_id = request
        splits = statsapi.game_log(player_id, group, season, sport_id)
        return [GameLog.from_split(player_id, group, split) for split in splits]

    # One request per player, fetched concurrently. Thirty players at most of a
    # second each is otherwise half the run, and they do not depend on one
    # another. Results keep the order asked in, so the store is written the same
    # way every day.
    with ThreadPoolExecutor(pitch_data.WORKERS) as pool:
        return [log for logs in pool.map(fetch, wanted) for log in logs]


def whiffs_for_outings(logs: list[GameLog]) -> dict[tuple[int, int], int]:
    """
    Whiffs by pitcher and game, for one day's outings.

    This is the only play-by-play the daily run touches, and it is bounded by
    how many tracked pitchers threw yesterday — a handful of requests, not the
    season-scale pass the park factors need. A game that cannot be read is
    simply left out, and the line reports strikeouts alone.
    """
    wanted = sorted({log.game_pk for log in logs if log.is_pitching})

    def read(game_pk: int) -> dict[int, int]:
        try:
            return pitch_data.whiffs_by_pitcher(game_pk)
        except statsapi.StatsApiError:
            return {}

    found: dict[tuple[int, int], int] = {}
    with ThreadPoolExecutor(pitch_data.WORKERS) as pool:
        for game_pk, by_pitcher in zip(wanted, pool.map(read, wanted), strict=True):
            for pitcher, whiffs in by_pitcher.items():
                found[(pitcher, game_pk)] = whiffs
    return found


def _club_transactions(team_ids: list[int], since: date, until: date) -> list[dict]:
    """
    The feed for every club in an organization, fetched concurrently.

    Both directions of a move are reported, once by each club involved, so
    callers deduplicate. Order follows the clubs asked for, which keeps that
    deduplication deciding the same way each run.
    """

    def fetch(team_id: int) -> list[dict]:
        return statsapi.transactions(team_id, since.isoformat(), until.isoformat())

    with ThreadPoolExecutor(pitch_data.WORKERS) as pool:
        return [row for page in pool.map(fetch, team_ids) for row in page]


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
    for raw in _club_transactions(team_ids, since, until):
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


def club_shares(
    player_id: int, group: str, season: int, sport_id: int
) -> dict[int, float]:
    """
    How a player's time at one level divides between the clubs he played for.

    The leaderboards pool a within-level trade into a single row credited to
    whichever club he finished with, so the split has to be asked for by name.
    The per-player feed does break it out, and returns an unattributed total
    alongside the clubs, which is dropped.

    Returns an empty mapping for the ordinary case of one club, so callers can
    treat "nothing to blend" and "nothing to see" alike.
    """
    payload = statsapi.get(
        f"people/{player_id}/stats",
        stats="season",
        group=group,
        season=season,
        sportId=sport_id,
    )
    shares: dict[int, float] = {}
    for block in payload.get("stats", []):
        for split in block.get("splits", []):
            team_id = (split.get("team") or {}).get("id")
            if not team_id:
                continue  # the combined row, which is what we are unpicking
            stat = split.get("stat", {})
            played = stat.get("plateAppearances") or stat.get("battersFaced") or 0
            if played:
                shares[team_id] = shares.get(team_id, 0.0) + float(played)
    return shares if len(shares) > 1 else {}


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
    for raw in _club_transactions(sorted(inside), since, until):
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
