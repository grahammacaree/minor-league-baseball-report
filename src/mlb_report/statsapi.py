from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://statsapi.mlb.com/api/v1"

# MiLB levels, most advanced first. Sport 17 is the Dominican Summer League.
AFFILIATE_SPORT_IDS = (11, 12, 13, 14, 16, 17)

_USER_AGENT = "minor-league-baseball-report (+https://github.com/grahammacaree)"
_TIMEOUT_SECONDS = 20
_MAX_ATTEMPTS = 3


class StatsApiError(RuntimeError):
    pass


def get(path: str, **params: Any) -> dict:
    """GET a Stats API endpoint, retrying briefly on transient failures."""
    query = urllib.parse.urlencode(
        {k: v for k, v in params.items() if v is not None}, safe="[],()="
    )
    url = f"{BASE_URL}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(2**attempt)
    raise StatsApiError(f"GET {url} failed: {last_error}")


def affiliate_teams(parent_org_id: int, season: int) -> list[dict]:
    """
    Minor-league clubs belonging to an organization.

    The teams endpoint accepts a single sportId per call, so each level is a
    separate request.
    """
    teams: list[dict] = []
    for sport_id in AFFILIATE_SPORT_IDS:
        payload = get("teams", sportId=sport_id, season=season)
        teams.extend(
            team
            for team in payload.get("teams", [])
            if team.get("parentOrgId") == parent_org_id
        )
    return teams


def sport_players(sport_id: int, season: int) -> list[dict]:
    return get(f"sports/{sport_id}/players", season=season).get("people", [])


def people(player_ids: list[int], hydrate: str | None = None) -> list[dict]:
    if not player_ids:
        return []
    ids = ",".join(str(i) for i in player_ids)
    return get("people", personIds=ids, hydrate=hydrate).get("people", [])


def game_log(player_id: int, group: str, season: int, sport_id: int) -> list[dict]:
    """
    One player's game-by-game log at a single level.

    The endpoint rejects a comma-separated sportId, so callers fetch the levels
    they care about one at a time.
    """
    payload = get(
        f"people/{player_id}/stats",
        stats="gameLog",
        group=group,
        season=season,
        sportId=sport_id,
    )
    return [split for block in payload.get("stats", []) for split in block["splits"]]


def transactions(team_id: int, start_date: str, end_date: str) -> list[dict]:
    payload = get(
        "transactions", teamId=team_id, startDate=start_date, endDate=end_date
    )
    return payload.get("transactions", [])
