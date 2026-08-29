from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .config_loader import user_data_dir
from .models import GameLog


def _path(season: int) -> Path:
    return user_data_dir() / f"game_logs_{season}.ndjson"


def _key(log: GameLog) -> tuple[int, int, str]:
    return (log.player_id, log.game_pk, log.group)


def load(season: int) -> list[GameLog]:
    path = _path(season)
    if not path.exists():
        return []
    logs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            logs.append(GameLog.from_dict(json.loads(line)))
    return logs


def save(season: int, logs: list[GameLog]) -> int:
    """
    Merge logs into the season's history, returning how many rows are new.

    The file is rewritten rather than appended to because     a line already on disk
    can change: a corrected box score updates a game already seen, and the later
    fetch should win.
    """
    merged = {_key(log): log for log in load(season)}
    before = len(merged)
    merged.update({_key(log): log for log in logs})

    path = _path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(merged.values(), key=lambda log: (log.game_date, log.player_id))
    path.write_text(
        "".join(json.dumps(log.to_dict()) + "\n" for log in ordered), encoding="utf-8"
    )
    return len(merged) - before


def since(season: int, days: int, as_of: date) -> list[GameLog]:
    cutoff = as_of - timedelta(days=days)
    return [log for log in load(season) if cutoff <= log.game_date <= as_of]
