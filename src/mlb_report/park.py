"""
Park factors, per component.

Run environments differ by park in ways that are not only about runs: a park
that suppresses strikeouts is telling you something different from one that
suppresses home runs, and a prospect's contact rate deserves the same context
as his slugging.

Factors are computed once per offseason by scripts/build-park-factors and
committed. Nothing here fetches anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .config_loader import bundled_config_dir

# Recency weights across the three most recent completed seasons. A convention
# rather than a fitted result; see docs/METRICS.md for why it is flagged for
# validation.
SEASON_WEIGHTS = (5, 3, 1)

# Derived from game logs, which every season has.
BOX_COMPONENTS = (
    "runs",
    "strikeouts",
    "walks",
    "home_runs",
    "hits_in_play",
    "extra_base_hits",
)

# Derived from play-by-play, and so only present for seasons that have been
# gathered. Strikeouts blend whiffs and called strikes, and across parks the two
# are unrelated to each other, so adjusting a bat-to-ball rate by the strikeout
# factor imports zone variation that has nothing to do with it. Trajectory and
# spray have no box-score equivalent at all: a scorer's ground ball and a hitter's
# pulled ball are only ever recorded pitch by pitch.
PITCH_COMPONENTS = ("whiffs", "called_strikes", "ground_balls", "pull")

COMPONENTS = BOX_COMPONENTS + PITCH_COMPONENTS

NEUTRAL = dict.fromkeys(COMPONENTS, 1.0)


@dataclass(frozen=True)
class ParkFactors:
    """Blended factors by team, on the scale where 1.0 is league neutral."""

    season: int
    by_team: dict[int, dict[str, float]]

    def for_team(self, team_id: int | None) -> dict[str, float]:
        return self.by_team.get(team_id or 0, dict(NEUTRAL))

    def runs_factor(self, team_id: int | None) -> float:
        """
        The runs factor as applied to a player's season line.

        Halved toward neutral because roughly half a player's games are on the
        road: a park that inflates scoring by 10 percent only inflates his own
        line by about 5.
        """
        raw = self.for_team(team_id).get("runs", 1.0)
        return (raw + 1.0) / 2


def _factors_dir():
    return bundled_config_dir() / "park_factors"


def available_seasons(league_id: int) -> list[int]:
    directory = _factors_dir()
    if not directory.exists():
        return []
    seasons = []
    for path in directory.glob(f"{league_id}-*.json"):
        try:
            seasons.append(int(path.stem.split("-")[-1]))
        except ValueError:
            continue
    return sorted(seasons, reverse=True)


def load_season(league_id: int, season: int) -> dict:
    path = _factors_dir() / f"{league_id}-{season}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def blend(seasons: list[dict], weights: tuple[int, ...] = SEASON_WEIGHTS) -> dict:
    """
    Weighted average of per-season factors, most recent first.

    Weights are renormalized over whatever seasons exist, so an early year with
    only one season of history stays centered on 1.0 instead of being pulled
    toward it by missing data.
    """
    if not seasons:
        return {}

    usable = list(zip(seasons, weights, strict=False))
    total_weight = sum(weight for _, weight in usable)
    if total_weight <= 0:
        return {}

    blended: dict[int, dict[str, float]] = {}
    team_ids = {int(team_id) for payload, _ in usable for team_id in payload}
    for team_id in team_ids:
        components = {}
        for component in COMPONENTS:
            weighted = 0.0
            applied = 0
            for payload, weight in usable:
                value = payload.get(str(team_id), {}).get(component)
                if value is not None:
                    weighted += weight * value
                    applied += weight
            components[component] = weighted / applied if applied else 1.0
        blended[team_id] = components
    return blended


def load(league_ids: list[int], season: int) -> ParkFactors:
    """Blended factors for every league in play, keyed by team."""
    by_team: dict[int, dict[str, float]] = {}
    for league_id in league_ids:
        seasons = [
            load_season(league_id, year)
            for year in available_seasons(league_id)
            if year < season
        ][: len(SEASON_WEIGHTS)]
        by_team.update(blend(seasons))
    return ParkFactors(season=season, by_team=by_team)


def describe(factors: dict[str, float], threshold: float = 0.06) -> str | None:
    """
    Flag a park only when it distorts something enough to matter.

    Most parks are unremarkable and saying so every day would be noise.
    """
    notable = []
    for component in COMPONENTS:
        value = factors.get(component, 1.0)
        if abs(value - 1.0) < threshold:
            continue
        direction = "inflates" if value > 1 else "suppresses"
        label = component.replace("_", " ")
        notable.append(f"{direction} {label} {abs(value - 1) * 100:.0f}%")
    return "; ".join(notable) if notable else None
