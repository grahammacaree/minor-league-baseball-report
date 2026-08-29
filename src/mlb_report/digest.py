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

# Most advanced first. A level a reader does not care about today is then a
# heading to skip rather than a line to check the label on.
LEVEL_ORDER = ("AAA", "AA", "A+", "A", "ROK", "DSL")

ARROWS = {"up": "↑", "down": "↓"}


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
    # Level abbreviation to the lines played at it, ordered by LEVEL_ORDER.
    played: dict[str, list[str]] = field(default_factory=dict)
    seasons: list[str] = field(default_factory=list)
    # Players from outside the watchlist who did enough to be listed at all,
    # which is the one count that says whether the email is worth opening now.
    standouts: int = 0
    moves: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """
        Whether the day is quiet enough to skip sending.

        The watchlist playing is not news — they play most days. What makes an
        email worth arriving is somebody outside it forcing his way in, or a
        roster move.
        """
        return not (self.standouts or self.moves)


def _by_player(logs: list[GameLog]) -> dict[int, list[GameLog]]:
    grouped: dict[int, list[GameLog]] = defaultdict(list)
    for log in logs:
        grouped[log.player_id].append(log)
    return grouped


def _by_level(logs: list[GameLog]) -> dict[str, list[GameLog]]:
    grouped: dict[str, list[GameLog]] = defaultdict(list)
    for log in logs:
        grouped[log.level].append(log)
    return grouped


def _level_rank(level: str) -> int:
    """Anything unrecognised sorts last rather than crashing the digest."""
    return LEVEL_ORDER.index(level) if level in LEVEL_ORDER else len(LEVEL_ORDER)


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


def _played_line(prospect: Prospect, logs: list[GameLog]) -> str:
    """
    What a prospect did yesterday, with the level carried by the heading above.

    Doubleheaders are joined rather than split into two entries, so a player
    appears once wherever the reader looks for him.
    """
    lines = "; ".join(f"{game_line(log)} vs {log.opponent}" for log in logs)
    return f"**{prospect.rank}. {prospect.name}** — {lines}"


def _season_entry(
    prospect: Prospect,
    context: PlayerContext | None,
    form: list[str],
) -> str:
    """
    A prospect's season, and how it rates in his league.

    Separated from the day's line because the two are read for different
    reasons: one is news, the other is the thing news gets judged against.
    """
    header = f"**{prospect.rank}. {prospect.name}** ({prospect.position}"
    header += f", {context.age}" if context and context.age else ""
    header += ")"
    if context and context.promoted:
        # Nothing about his day belongs here: those games are on television.
        header += f" — promoted to {MAJORS}"

    body = [header]
    if context and context.production:
        body.append(f"  Season at {context.production}")
    # Form is reported even when the league context is missing: a hit streak is
    # observed from the game logs alone and does not depend on a baseline.
    body.extend(f"  {marker}" for marker in form)
    if context:
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

    # Everyone on the watchlist who played, and everyone below it who did
    # something worth stopping for. Grouped by level, since that is how a farm
    # system is actually read.
    by_level: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for prospect in tracked:
        today = today_by_player.get(prospect.player_id, [])
        watched = prospect.rank <= watchlist_depth
        for level, logs in _by_level(today).items():
            shown = logs if watched else [t for t in logs if _is_notable(t, thresholds)]
            if shown:
                by_level[level].append((prospect.rank, _played_line(prospect, shown)))
                if not watched:
                    digest.standouts += 1

    for level in sorted(by_level, key=_level_rank):
        digest.played[level] = [line for _, line in sorted(by_level[level])]

    for prospect in tracked:
        if prospect.rank > watchlist_depth:
            continue
        form = [
            f"{ARROWS[trend.direction]} {trend.headline}"
            for trend in trends.for_player(
                prospect.player_id,
                prospect.name,
                logs_by_player.get(prospect.player_id, []),
                report_date,
                settings["trends"],
            )
        ]
        digest.seasons.append(
            _season_entry(prospect, contexts.get(prospect.player_id), form)
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


def _played_section(played: dict[str, list[str]]) -> list[str]:
    if not played:
        return _section("Played yesterday", [], "Nobody played.")
    out = ["## Played yesterday", ""]
    for level, lines in played.items():
        out += [f"### {level}", "", *[f"- {line}" for line in lines], ""]
    return out


def render(digest: Digest) -> str:
    out = [f"# Mariners farm report — {digest.report_date:%A %-d %B %Y}", ""]
    out += _played_section(digest.played)
    out += _section("Top 10 season lines", digest.seasons, "No seasons to report.")
    out += _section("Moves and injuries", digest.moves, "No roster moves.")
    if digest.warnings:
        out += _section("Notes", digest.warnings, "")
    return "\n".join(out).rstrip() + "\n"
