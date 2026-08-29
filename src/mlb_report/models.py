from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class GameLog:
    """One player's line from one game, at whatever level they played it."""

    player_id: int
    player_name: str
    game_date: date
    game_pk: int  # identifies the game itself, so doubleheaders stay distinct
    group: str  # "hitting" or "pitching"
    level: str  # AAA, AA, A+, A, ROK, DSL, MLB
    team: str
    opponent: str
    summary: str
    stat: dict = field(default_factory=dict, repr=False)

    @property
    def is_pitching(self) -> bool:
        return self.group == "pitching"

    def value(self, key: str, default: float = 0) -> float:
        raw = self.stat.get(key, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def count(self, key: str) -> int:
        return int(self.value(key))

    @property
    def extra_base_hits(self) -> int:
        return self.count("doubles") + self.count("triples") + self.count("homeRuns")

    @property
    def innings_pitched(self) -> float:
        """
        Innings as a real number.

        The API reports thirds as .1 and .2, which do not sum correctly, so the
        fractional part is converted before any arithmetic.
        """
        raw = self.stat.get("inningsPitched", "0.0")
        try:
            whole, _, thirds = str(raw).partition(".")
            return int(whole or 0) + int(thirds or 0) / 3
        except ValueError:
            return 0.0

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "game_date": self.game_date.isoformat(),
            "game_pk": self.game_pk,
            "group": self.group,
            "level": self.level,
            "team": self.team,
            "opponent": self.opponent,
            "summary": self.summary,
            "stat": self.stat,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> GameLog:
        return cls(
            player_id=payload["player_id"],
            player_name=payload["player_name"],
            game_date=date.fromisoformat(payload["game_date"]),
            game_pk=payload["game_pk"],
            group=payload["group"],
            level=payload["level"],
            team=payload["team"],
            opponent=payload["opponent"],
            summary=payload["summary"],
            stat=payload.get("stat", {}),
        )

    @classmethod
    def from_split(cls, player_id: int, group: str, split: dict) -> GameLog:
        stat = split.get("stat", {})
        return cls(
            player_id=player_id,
            player_name=split.get("player", {}).get("fullName", ""),
            game_date=date.fromisoformat(split["date"]),
            game_pk=split.get("game", {}).get("gamePk", 0),
            group=group,
            level=split.get("sport", {}).get("abbreviation", "?"),
            team=split.get("team", {}).get("name", ""),
            opponent=split.get("opponent", {}).get("name", ""),
            summary=stat.get("summary", ""),
            stat=stat,
        )


@dataclass(frozen=True)
class Transaction:
    """A roster move or injury placement affecting a tracked prospect."""

    player_id: int
    player_name: str
    effective_date: date
    type_desc: str
    description: str

    @property
    def is_injury(self) -> bool:
        text = self.description.lower()
        return "injured list" in text or "rehab assignment" in text
