"""
Reading the captured Pipeline rankings for all thirty organizations.

The capture itself lives in `capture_rankings.py` and needs a browser. This
module only reads what it wrote, so the daily run stays on the standard
library.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .config_loader import load_json

RANKINGS_FILE = "prospect_rankings.json"


@dataclass(frozen=True)
class Ranked:
    """A player's standing on the organization that ranked him."""

    player_id: int
    name: str
    position: str
    rank: int
    org_name: str
    org_abbreviation: str

    def describe(self) -> str:
        return f"{self.org_abbreviation} No. {self.rank}"


def load() -> dict[int, Ranked]:
    """
    Every ranked prospect in baseball, keyed by player id.

    Flattened across organizations because the question asked of it is about a
    player rather than a club: this one just arrived, was anybody ranking him?
    A player traded between the capture and now appears under the org that
    ranked him, which is the org he was ranked in and so the useful answer.
    """
    payload = load_json(RANKINGS_FILE)
    ranked: dict[int, Ranked] = {}
    for org in payload.get("orgs", []):
        for entry in org.get("prospects", []):
            player_id = entry.get("player_id")
            if not player_id:
                continue
            ranked[player_id] = Ranked(
                player_id=player_id,
                name=entry.get("name", ""),
                position=entry.get("position", ""),
                rank=entry["rank"],
                org_name=org.get("name", ""),
                org_abbreviation=org.get("abbreviation", ""),
            )
    return ranked


def captured_on() -> date:
    return date.fromisoformat(load_json(RANKINGS_FILE)["captured"])
