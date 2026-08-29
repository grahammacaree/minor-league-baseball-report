from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from . import trends
from .models import GameLog, Transaction
from .prospects import Prospect

# The level abbreviation the API uses for the majors, and the one level this
# digest deliberately says nothing about.
MAJORS = "MLB"


@dataclass(frozen=True)
class PlayerContext:
    """A prospect's season, already rendered for display."""

    age: str | None = None
    production: str | None = None
    skills: str | None = None
    profile: str | None = None
    prior: str | None = None
    promoted: bool = False


@dataclass
class Digest:
    report_date: date
    watchlist: list[str] = field(default_factory=list)
    notable: list[str] = field(default_factory=list)
    trends: list[str] = field(default_factory=list)
    moves: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.notable or self.trends or self.moves)


def _by_player(logs: list[GameLog]) -> dict[int, list[GameLog]]:
    grouped: dict[int, list[GameLog]] = defaultdict(list)
    for log in logs:
        grouped[log.player_id].append(log)
    return grouped


def _hitting_line(log: GameLog) -> str:
    parts = [log.summary or f"{log.count('hits')}-{log.count('atBats')}"]
    if steals := log.count("stolenBases"):
        parts.append(f"{steals} SB")
    return ", ".join(parts)


def _pitching_line(log: GameLog) -> str:
    innings = log.stat.get("inningsPitched", "0.0")
    return (
        f"{innings} IP, {log.count('hits')} H, {log.count('runs')} R, "
        f"{log.count('earnedRuns')} ER, {log.count('baseOnBalls')} BB, "
        f"{log.count('strikeOuts')} K"
    )


def game_line(log: GameLog) -> str:
    return _pitching_line(log) if log.is_pitching else _hitting_line(log)


def _describe(
    prospect: Prospect,
    logs: list[GameLog],
    context: PlayerContext | None,
) -> str:
    """
    One prospect's day, then the season it sits inside.

    The daily line on its own is noise; it only means something next to what
    the player has been doing all year and how that rates in his league.
    """
    header = f"**{prospect.rank}. {prospect.name}** ({prospect.position}"
    header += f", {context.age}" if context and context.age else ""
    header += ")"

    if context and context.promoted:
        # Nothing about his day belongs here: those games are on television.
        body = [f"{header} — promoted to {MAJORS}"]
    elif logs:
        lines = [f"{game_line(log)} — {log.level} vs {log.opponent}" for log in logs]
        body = [f"{header} — {'; '.join(lines)}"]
    else:
        body = [f"{header} — did not play"]

    if context:
        if context.production:
            body.append(f"  Season at {context.production}")
        if context.skills:
            body.append(f"  {context.skills}")
        if context.profile:
            body.append(f"  {context.profile}")
        if context.prior:
            body.append(f"  {context.prior}")
    return "\n".join(body)


def _is_notable(log: GameLog, thresholds: dict) -> bool:
    if log.is_pitching:
        if log.count("strikeOuts") >= thresholds["strikeouts_pitched"]:
            return True
        scoreless = log.count("earnedRuns") == 0
        return (
            scoreless and log.innings_pitched >= thresholds["scoreless_innings_relief"]
        )
    return (
        log.count("hits") >= thresholds["hits"]
        or log.extra_base_hits >= thresholds["extra_base_hits"]
        or log.count("homeRuns") >= thresholds["home_runs"]
        or log.count("rbi") >= thresholds["rbi"]
        or log.count("stolenBases") >= thresholds["stolen_bases"]
    )


def build(
    report_date: date,
    tracked: list[Prospect],
    history: list[GameLog],
    moves: list[Transaction],
    settings: dict,
    contexts: dict[int, PlayerContext] | None = None,
) -> Digest:
    digest = Digest(report_date=report_date)
    contexts = contexts or {}
    logs_by_player = _by_player(history)
    today_by_player = {
        player_id: [log for log in logs if log.game_date == report_date]
        for player_id, logs in logs_by_player.items()
    }

    watchlist_depth = settings["depth"]["watchlist"]
    thresholds = settings["notable_thresholds"]

    for prospect in tracked:
        today = today_by_player.get(prospect.player_id, [])
        if prospect.rank <= watchlist_depth:
            digest.watchlist.append(
                _describe(prospect, today, contexts.get(prospect.player_id))
            )
            continue
        for log in today:
            if _is_notable(log, thresholds):
                digest.notable.append(
                    f"**{prospect.name}** (#{prospect.rank}, {log.level}) — "
                    f"{game_line(log)} vs {log.opponent}"
                )

    for prospect in tracked:
        player_logs = logs_by_player.get(prospect.player_id, [])
        for trend in trends.for_player(
            prospect.player_id,
            prospect.name,
            player_logs,
            report_date,
            settings["trends"],
        ):
            digest.trends.append(
                f"**{trend.player_name}** (#{prospect.rank}) — {trend.headline}"
            )

    for move in moves:
        label = "Injury" if move.is_injury else move.type_desc
        digest.moves.append(f"**{label}** — {move.description}")

    unresolved = [p.name for p in tracked if p.player_id is None]
    if unresolved:
        digest.warnings.append(
            f"No MLB player id yet for {', '.join(unresolved)} — "
            "usually an unassigned draftee, and they will appear once rostered."
        )
    return digest


def _section(title: str, lines: list[str], empty: str) -> list[str]:
    body = [f"- {line}" for line in lines] if lines else [f"_{empty}_"]
    return [f"## {title}", "", *body, ""]


def render(digest: Digest) -> str:
    out = [f"# Mariners farm report — {digest.report_date:%A %-d %B %Y}", ""]
    out += _section("Watchlist", digest.watchlist, "No tracked prospects played.")
    out += _section("Notable performances", digest.notable, "Nothing cleared the bar.")
    out += _section("Trends and streaks", digest.trends, "No streaks worth flagging.")
    out += _section("Moves and injuries", digest.moves, "No roster moves.")
    if digest.warnings:
        out += _section("Notes", digest.warnings, "")
    return "\n".join(out).rstrip() + "\n"
