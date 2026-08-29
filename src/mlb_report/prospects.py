from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from . import statsapi
from .config_loader import load_json, user_data_dir

_RESOLVED_IDS_FILE = "resolved_player_ids.json"

# MLB Pipeline reworks the org lists in the spring and again around the deadline;
# those are the two points where the committed ranking needs regenerating.
_RANKING_UPDATE_DAYS = ((3, 31), (7, 31))


@dataclass(frozen=True)
class Prospect:
    rank: int
    name: str
    position: str
    player_id: int | None = None

    @property
    def is_pitcher(self) -> bool:
        return "HP" in self.position or self.position == "P"


def _normalize(name: str) -> str:
    """Fold accents and case so roster spellings match the ranking list."""
    stripped = unicodedata.normalize("NFKD", name)
    without_accents = "".join(c for c in stripped if not unicodedata.combining(c))
    return " ".join(without_accents.lower().replace(".", "").split())


def load_ranked_list() -> list[Prospect]:
    payload = load_json("prospects.json")
    prospects = [
        Prospect(
            rank=entry["rank"],
            name=entry["name"],
            position=entry["position"],
            player_id=entry.get("player_id"),
        )
        for entry in payload["prospects"]
    ]
    return sorted(prospects, key=lambda p: p.rank)


def captured_on() -> date:
    return date.fromisoformat(load_json("prospects.json")["captured"])


def refresh_due(captured: date, as_of: date | None = None) -> bool:
    """
    Whether a Pipeline ranking update has landed since the list was captured.

    The rankings are maintained by hand because mlb.com only serves the top five
    to non-browser clients, so the digest flags when it is time to redo them
    rather than silently reporting on a stale top 30.
    """
    as_of = as_of or date.today()
    updates = [
        date(year, month, day)
        for year in range(captured.year, as_of.year + 1)
        for month, day in _RANKING_UPDATE_DAYS
    ]
    return any(captured < update <= as_of for update in updates)


def _cache_path() -> Path:
    return user_data_dir() / _RESOLVED_IDS_FILE


def _read_cache() -> dict[str, int]:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_cache(cache: dict[str, int]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def _roster_index(season: int) -> dict[str, int]:
    """Name to player id across every affiliate level, most advanced first."""
    index: dict[str, int] = {}
    for sport_id in statsapi.AFFILIATE_SPORT_IDS:
        for player in statsapi.sport_players(sport_id, season):
            index.setdefault(_normalize(player["fullName"]), player["id"])
    return index


def resolve_player_ids(prospects: list[Prospect], season: int) -> list[Prospect]:
    """
    Fill in ids for prospects the ranking list does not carry one for.

    Complex-level players often have no MLB profile page when they are first
    ranked, so the id is looked up from affiliate rosters and cached. Anyone who
    still cannot be matched is returned unresolved rather than dropped, so the
    digest can report the gap.
    """
    missing = [p for p in prospects if p.player_id is None]
    if not missing:
        return prospects

    cache = _read_cache()
    unresolved = [p for p in missing if _normalize(p.name) not in cache]
    if unresolved:
        index = _roster_index(season)
        for prospect in unresolved:
            key = _normalize(prospect.name)
            if found := index.get(key):
                cache[key] = found
        _write_cache(cache)

    return [
        p
        if p.player_id is not None
        else Prospect(p.rank, p.name, p.position, cache.get(_normalize(p.name)))
        for p in prospects
    ]


def tracked_prospects(season: int) -> list[Prospect]:
    return resolve_player_ids(load_ranked_list(), season)


def to_dicts(prospects: list[Prospect]) -> list[dict]:
    return [asdict(p) for p in prospects]
