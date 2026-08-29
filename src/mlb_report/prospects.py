from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from . import statsapi
from .config_loader import load_json, user_data_dir
from .models import Transaction
from .rankings import Ranked

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


def without_departures(
    tracked: list[Prospect], departures: list[Transaction]
) -> tuple[list[Prospect], list[Transaction]]:
    """
    Drop players the organization has traded away.

    A committed list outlives the roster it describes. Until the next capture a
    departed prospect would keep being fetched, reported on, and counted as one
    of the ten the digest follows most closely — all for another team's farm
    system.

    Ranks are left as they were rather than closed up. They are Pipeline's
    numbering, not ours to renumber, and a gap at 7 is a truer description of
    the list than promoting everyone below it.
    """
    gone = {move.player_id for move in departures}
    if not gone:
        return tracked, []
    remaining = [p for p in tracked if p.player_id not in gone]
    departed = [
        move for move in departures if move.player_id in {p.player_id for p in tracked}
    ]
    return remaining, sorted(departed, key=lambda m: (m.effective_date, m.player_name))


def with_acquisitions(
    tracked: list[Prospect],
    arrivals: list[Transaction],
    ranked: dict[int, Ranked],
) -> tuple[list[Prospect], list[tuple[Transaction, Ranked]]]:
    """
    Add acquired players that somebody had in their top 30 to the tracked list.

    Being ranked anywhere is the test. It is the same judgement the committed
    list is built from, only applied to the org a player is arriving from, and
    it is far sharper than asking how old he is: a 24-year-old nobody ranked is
    organizational depth, and a 24-year-old ranked fourth is the reason this
    exists.

    They are appended below the committed thirty rather than slotted into it.
    Where an acquisition belongs in our own order is a judgement for the next
    capture to make; until then he is followed without displacing anyone or
    pushing into the watchlist, where he would crowd out a top ten prospect on
    the strength of another club's opinion.
    """
    known = {p.player_id for p in tracked if p.player_id}
    acquired: list[tuple[Transaction, Ranked]] = []
    for transaction in arrivals:
        entry = ranked.get(transaction.player_id)
        if entry is None or transaction.player_id in known:
            continue
        known.add(transaction.player_id)
        acquired.append((transaction, entry))

    # Best prospect first, so a headline acquisition leads.
    acquired.sort(key=lambda pair: pair[1].rank)
    next_rank = max((p.rank for p in tracked), default=0)
    added = [
        Prospect(
            rank=next_rank + offset,
            name=entry.name,
            position=entry.position,
            player_id=entry.player_id,
        )
        for offset, (_, entry) in enumerate(acquired, start=1)
    ]
    return tracked + added, acquired


def tracked_prospects(season: int) -> list[Prospect]:
    return resolve_player_ids(load_ranked_list(), season)


def to_dicts(prospects: list[Prospect]) -> list[dict]:
    return [asdict(p) for p in prospects]
