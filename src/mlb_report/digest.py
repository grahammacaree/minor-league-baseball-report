from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from . import trends
from .models import GameLog, Transaction
from .prospects import Prospect
from .rankings import Ranked

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
    # Every level and club he has left this season, largest sample first. A
    # promotion is the case where the stint behind him is the better evidence.
    priors: list[str] = field(default_factory=list)
    promoted: bool = False


@dataclass
class Digest:
    report_date: date
    # Level abbreviation to the lines played at it, ordered by LEVEL_ORDER.
    played: dict[str, list[str]] = field(default_factory=dict)
    # Level to the one opponent everybody under it faced, where there was one.
    opponents: dict[str, str] = field(default_factory=dict)
    seasons: list[str] = field(default_factory=list)
    # Players from outside the watchlist who did enough to be listed at all,
    # which is the one count that says whether the email is worth opening now.
    standouts: int = 0
    moves: list[str] = field(default_factory=list)
    # Ranked players who have just joined the organization.
    arrivals: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """
        Whether the day is quiet enough to skip sending.

        The watchlist playing is not news — they play most days. What makes an
        email worth arriving is somebody outside it forcing his way in, a roster
        move, or a new prospect in the system.
        """
        return not (self.standouts or self.moves or self.arrivals)


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
    # The feed separates the batting line from the events with a pipe; a comma
    # reads the same and keeps one separator running through the line.
    summary = (log.summary or f"{log.count('hits')}-{log.count('atBats')}").replace(
        " | ", ", "
    )
    parts = [summary]
    if steals := log.count("stolenBases"):
        parts.append(f"{steals} SB")
    return ", ".join(parts)


def _pitching_line(log: GameLog, whiffs: int | None = None) -> str:
    """
    One outing, with the whiff count beside the strikeouts where it is known.

    Strikeouts say how the outing ended, which depends on the hitters and on
    the umpire. Whiffs say how the stuff played. Six strikeouts on eight whiffs
    is a different night from six on eighteen.
    """
    innings = log.stat.get("inningsPitched", "0.0")
    strikeouts = f"{log.count('strikeOuts')} K"
    if whiffs is not None:
        strikeouts += f" ({whiffs} whiffs)"
    return (
        f"{innings} IP, {log.count('hits')} H, {log.count('runs')} R, "
        f"{log.count('earnedRuns')} ER, {log.count('baseOnBalls')} BB, "
        f"{strikeouts}"
    )


def game_line(log: GameLog, whiffs: int | None = None) -> str:
    return _pitching_line(log, whiffs) if log.is_pitching else _hitting_line(log)


def _opponents(logs: list[GameLog]) -> set[str]:
    return {log.opponent for log in logs if log.opponent}


def _played_line(
    prospect: Prospect,
    logs: list[GameLog],
    whiffs: dict[tuple[int, int], int],
    name_opponent: bool = False,
) -> str:
    """
    What a prospect did yesterday, with the level carried by the heading above.

    The opponent is usually carried by the heading too, since one club plays one
    opponent on one day. It comes back onto the line only when the heading could
    not name a single opponent for everyone under it.

    Doubleheaders are joined rather than split into two entries, so a player
    appears once wherever the reader looks for him.
    """
    lines = "; ".join(
        game_line(log, whiffs.get((log.player_id, log.game_pk)))
        + (f" vs {log.opponent}" if name_opponent and log.opponent else "")
        for log in logs
    )
    return f"**{prospect.rank}. {prospect.position} {prospect.name}**: {lines}"


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
    header = f"**{prospect.rank}. {prospect.position} {prospect.name}**"
    if context and context.age:
        header += f" ({context.age})"
    if context and context.promoted:
        # Nothing about his day belongs here: those games are on television.
        header += f" — promoted to {MAJORS}"

    body = [header]
    if context and context.production:
        body.append(f"  Season: {context.production}")
    # Form is reported even when the league context is missing: a hit streak is
    # observed from the game logs alone and does not depend on a baseline.
    body.extend(f"  {marker}" for marker in form)
    if context:
        if context.skills:
            body.append(f"  {context.skills}")
        body.extend(f"  {prior}" for prior in context.priors)
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
    whiffs: dict[tuple[int, int], int] | None = None,
    arrivals: list[tuple[Transaction, Ranked]] | None = None,
) -> Digest:
    digest = Digest(report_date=report_date)
    contexts = contexts or {}
    whiffs = whiffs or {}
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
    by_level: dict[str, list[tuple[int, Prospect, list[GameLog]]]] = defaultdict(list)
    for prospect in tracked:
        today = today_by_player.get(prospect.player_id, [])
        watched = prospect.rank <= watchlist_depth
        for level, logs in _by_level(today).items():
            shown = logs if watched else [t for t in logs if _is_notable(t, thresholds)]
            if shown:
                by_level[level].append((prospect.rank, prospect, shown))
                if not watched:
                    digest.standouts += 1

    for level in sorted(by_level, key=_level_rank):
        entries = sorted(by_level[level], key=lambda entry: entry[0])
        # One club plays one opponent on one day, so the opponent belongs to the
        # heading rather than to every line beneath it. The exception is a level
        # where the org fields two clubs, which do not share an opponent.
        opponents = _opponents([log for _, _, logs in entries for log in logs])
        shared = len(opponents) == 1
        if shared:
            digest.opponents[level] = next(iter(opponents))
        digest.played[level] = [
            _played_line(prospect, logs, whiffs, name_opponent=not shared)
            for _, prospect, logs in entries
        ]

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

    # Where he was ranked, rather than what the transaction wire called him.
    # A club's own top 30 is the closest thing to a verdict on a player, and it
    # is the reason he is being followed here at all.
    for transaction, ranked in arrivals or []:
        digest.arrivals.append(
            f"**{ranked.position} {ranked.name}** — {ranked.describe()}, "
            f"acquired {transaction.effective_date:%-d %B}"
        )

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


def _played_section(
    played: dict[str, list[str]], opponents: dict[str, str]
) -> list[str]:
    if not played:
        return _section("Played yesterday", [], "Nobody played.")
    out = ["## Played yesterday", ""]
    for level, lines in played.items():
        heading = level
        if opponent := opponents.get(level):
            heading += f" (vs {opponent})"
        out += [f"### {heading}", "", *[f"- {line}" for line in lines], ""]
    return out


# What has been adjusted and what has not, since the two sit side by side on
# every season line and look alike. Stated every day rather than only when
# something is unusual, because a reader who has forgotten which is which has no
# way to tell from the numbers themselves.
ADJUSTMENT_NOTE = (
    "wRC+ and FIP- are adjusted for park and league. Skill bars rank a player "
    "against his own league on park-adjusted rates, but the rate printed beside "
    "each bar is what he actually did, unadjusted. Slash lines, wOBA and raw FIP "
    "are unadjusted throughout."
)


def render(digest: Digest) -> str:
    out = [f"# Mariners farm report — {digest.report_date:%A %-d %B %Y}", ""]
    out += _played_section(digest.played, digest.opponents)
    out += _section("Top 10 season lines", digest.seasons, "No seasons to report.")
    out += _section("Moves and injuries", digest.moves, "No roster moves.")
    # Only when there is one. An empty heading every day would train the reader
    # to skip the section on the day it finally matters.
    if digest.arrivals:
        out += _section("New in the system", digest.arrivals, "")
    out += _section("Notes", [ADJUSTMENT_NOTE, *digest.warnings], "")
    return "\n".join(out).rstrip() + "\n"
