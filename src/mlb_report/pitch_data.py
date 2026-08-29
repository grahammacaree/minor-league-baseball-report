"""
Per-game swing outcomes and batted-ball profiles, from play-by-play.

Season and game-log feeds carry strikeouts but not swings, and a strikeout is a
blend of two park effects that turn out to be unrelated: whiffs and called
strikes correlate +0.04 across parks. Adjusting a contact rate by the strikeout
factor therefore over-corrects by roughly 44%, importing zone variation into a
bat-to-ball measure.

The same feed carries batted-ball trajectory and landing coordinates. Trajectory
is redundant at the player level — season stats already break hits and outs out
by ground ball, line drive, fly ball and popup for hitters and pitchers alike —
but it is the only club-level source for a ground-ball park factor. Spray
direction has no season-stat equivalent at all, so pull rate can only be
measured here.

Play-by-play is expensive — one request per game — so results are aggregated to
a few numbers per game and cached. Fetching happens once per completed season,
never in the daily digest.
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import statsapi
from .config_loader import user_data_dir

# Deliberately modest. This is an unauthenticated public API, and a full
# backfill asks more of it than everything else in the project combined.
WORKERS = 6

SWING_FIELDS = ("pitches", "swings", "whiffs", "called_strikes")
TRAJECTORY_FIELDS = ("ground", "line", "fly", "pop")
SPRAY_FIELDS = ("pull", "center", "oppo")

FIELDS = SWING_FIELDS + TRAJECTORY_FIELDS + SPRAY_FIELDS

# Players carry the batted-ball half of the line. Trajectory is recorded here
# rather than read from the season feed, whose ground and air counts are built
# from outs and so miss every ball that fell in: a hitter's grounders through
# the infield are exactly the ones a ground-ball rate should be counting.
PLAYER_FIELDS = TRAJECTORY_FIELDS + SPRAY_FIELDS

TRAJECTORIES = {
    "ground_ball": "ground",
    "line_drive": "line",
    "fly_ball": "fly",
    "popup": "pop",
}

# Home plate and the outfield sit on a fixed axis in the gameday coordinate
# frame. Checked against the fielder who handled each ball: third base reads
# -29 degrees, centre field +2, first base +41, which is the field laid out in
# order. A 30-degree middle band splits the 90-degree field into rough thirds.
PLATE_X, PLATE_Y = 125.0, 205.0
CENTER_BAND = 15.0


def _blank(fields: tuple[str, ...] = FIELDS) -> dict[str, int]:
    return dict.fromkeys(fields, 0)


def spray(coord_x: float, coord_y: float, bat_side: str) -> str | None:
    """
    Pull, centre or opposite field, from where the ball came down.

    Handedness is what makes a direction a pull: the same ball down the left
    field line is pulled by a right-handed hitter and served the other way by a
    left-handed one.
    """
    if bat_side not in ("R", "L"):
        return None
    angle = math.degrees(math.atan2(coord_x - PLATE_X, PLATE_Y - coord_y))
    if abs(angle) <= CENTER_BAND:
        return "center"
    # Negative angles are the left-field side, which a right-hander pulls.
    to_left = angle < 0
    return "pull" if to_left == (bat_side == "R") else "oppo"


def game_sides(sport_id: int, season: int) -> dict[int, dict[str, int]]:
    """Both clubs in every completed game, so a half inning can be attributed."""
    payload = statsapi.get(
        "schedule",
        sportId=sport_id,
        season=season,
        gameType="R",
        fields="dates,games,gamePk,status,detailedState,teams,home,away,team,id",
    )
    sides = {}
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            if game.get("status", {}).get("detailedState") != "Final":
                continue
            teams = game.get("teams", {})
            home = teams.get("home", {}).get("team", {}).get("id")
            away = teams.get("away", {}).get("team", {}).get("id")
            if home and away:
                sides[game["gamePk"]] = {"home": home, "away": away}
    return sides


def parse_game(game_pk: int, sides: dict[str, int]) -> dict:
    """
    Swing outcomes and batted balls for one game.

    Clubs carry the full line, since park factors need the pitch counts too.
    Batters and pitchers carry the batted-ball line only.

    The batting side follows the half inning: visitors hit in the top.
    """
    payload = statsapi.get(f"game/{game_pk}/playByPlay")
    by_side = {"home": _blank(), "away": _blank()}
    batters: dict[int, dict[str, int]] = {}
    pitchers: dict[int, dict[str, int]] = {}

    for play in payload.get("allPlays", []):
        side = "away" if play.get("about", {}).get("halfInning") == "top" else "home"
        totals = by_side[side]
        matchup = play.get("matchup", {})
        bat_side = matchup.get("batSide", {}).get("code")
        batter = matchup.get("batter", {}).get("id")
        pitcher = matchup.get("pitcher", {}).get("id")

        for event in play.get("playEvents", []):
            if not event.get("isPitch"):
                continue
            description = (event.get("details", {}).get("description") or "").lower()
            totals["pitches"] += 1
            if any(
                token in description
                for token in ("swinging strike", "foul", "in play", "missed bunt")
            ):
                totals["swings"] += 1
            # A foul tip is a whiff by convention: the bat did not change the
            # ball's path enough to put it in play.
            if "swinging strike" in description or "foul tip" in description:
                totals["whiffs"] += 1
            elif "called strike" in description:
                totals["called_strikes"] += 1

            hit = event.get("hitData") or {}
            coords = hit.get("coordinates") or {}
            trajectory = TRAJECTORIES.get(hit.get("trajectory"))
            direction = (
                spray(coords["coordX"], coords["coordY"], bat_side)
                if coords.get("coordX") is not None and coords.get("coordY") is not None
                else None
            )

            for field in (trajectory, direction):
                if not field:
                    continue
                totals[field] += 1
                if batter:
                    batters.setdefault(batter, _blank(PLAYER_FIELDS))[field] += 1
                if pitcher:
                    pitchers.setdefault(pitcher, _blank(PLAYER_FIELDS))[field] += 1

    return {
        "clubs": {sides[side]: totals for side, totals in by_side.items()},
        "batters": batters,
        "pitchers": pitchers,
    }


# Bumped when the parsed shape changes. An older file is simply ignored, which
# costs a refetch but never mixes two shapes in one calculation.
SCHEMA = 3


def _cache_path(sport_id: int, season: int):
    return user_data_dir() / f"pitch_v{SCHEMA}_{sport_id}_{season}.json"


def _keyed(raw: dict) -> dict[int, dict[str, int]]:
    return {int(player): counts for player, counts in raw.items()}


def load_cached(sport_id: int, season: int) -> dict[int, dict]:
    """
    Previously gathered games.

    Entries that do not carry every field are dropped rather than trusted, so a
    cache written by an older shape simply refetches instead of failing deep in
    the arithmetic.
    """
    path = _cache_path(sport_id, season)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    games = {}
    for game, entry in raw.items():
        try:
            clubs = _keyed(entry["clubs"])
            parsed = {
                "clubs": clubs,
                "batters": _keyed(entry["batters"]),
                "pitchers": _keyed(entry["pitchers"]),
            }
        except (ValueError, AttributeError, KeyError, TypeError):
            continue
        if all(set(FIELDS) <= set(totals) for totals in clubs.values()):
            games[int(game)] = parsed
    return games


def _save(sport_id: int, season: int, games: dict) -> None:
    path = _cache_path(sport_id, season)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                str(game): {
                    part: {str(key): counts for key, counts in group.items()}
                    for part, group in entry.items()
                }
                for game, entry in games.items()
            }
        ),
        encoding="utf-8",
    )


def gather(sport_id: int, season: int, progress: bool = True) -> dict:
    """
    Every completed game's swing outcomes, fetched once and cached.

    Games already cached are skipped, so an interrupted backfill resumes where
    it stopped rather than starting again.
    """
    games = load_cached(sport_id, season)
    sides = game_sides(sport_id, season)
    missing = [game for game in sides if game not in games]

    if progress:
        print(
            f"  sport {sport_id} {season}: {len(sides):,} games, "
            f"{len(games):,} cached, {len(missing):,} to fetch",
            flush=True,
        )
    if not missing:
        return games

    def work(game_pk):
        try:
            return game_pk, parse_game(game_pk, sides[game_pk])
        except statsapi.StatsApiError:
            return game_pk, None

    started = time.time()
    done = failed = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        for game_pk, parsed in pool.map(work, missing):
            done += 1
            if parsed:
                games[game_pk] = parsed
            else:
                failed += 1
            if progress and done % 500 == 0:
                rate = done / (time.time() - started)
                remaining = (len(missing) - done) / rate / 60
                print(
                    f"    {done:,}/{len(missing):,} at {rate:.1f}/s, "
                    f"~{remaining:.1f} min left",
                    flush=True,
                )

    _save(sport_id, season, games)
    if progress and failed:
        print(f"    {failed} game(s) could not be fetched", flush=True)
    return games


def by_club(games: dict, home_of: dict[int, int]) -> tuple[dict, dict]:
    """
    Swing outcomes split into each club's home games and road games.

    Both clubs' batting lines are counted in every game, matching the park
    factor construction: the home club's roster then sits on both sides of the
    comparison and cancels.
    """
    at_home, on_road = defaultdict(_blank), defaultdict(_blank)
    for game_pk, entry in games.items():
        host = home_of.get(game_pk)
        if host is None:
            continue
        clubs = entry["clubs"]
        for club in clubs:
            bucket = at_home if host == club else on_road
            for totals in clubs.values():
                for field in FIELDS:
                    bucket[club][field] += totals[field]
    return at_home, on_road


def by_player(games: dict, side: str) -> dict[int, dict[str, int]]:
    """
    Season batted-ball totals for every batter, or every pitcher.

    Pitchers accumulate what was hit against them, which is the same measure
    read from the other end: a pitcher whose contact is pulled and on the
    ground is being beaten into the dirt, not merely unlucky.
    """
    totals: dict[int, dict[str, int]] = defaultdict(lambda: _blank(PLAYER_FIELDS))
    for entry in games.values():
        for player, counts in entry[side].items():
            for field in PLAYER_FIELDS:
                totals[player][field] += counts.get(field, 0)
    return dict(totals)


def rates(totals: dict[str, int]) -> dict[str, float | None]:
    """Park-comparable rates: per swing, per taken pitch, per ball in play."""
    swings = totals["swings"]
    taken = totals["pitches"] - swings
    tracked = sum(totals[field] for field in TRAJECTORY_FIELDS)
    placed = sum(totals[field] for field in SPRAY_FIELDS)
    return {
        "whiffs": totals["whiffs"] / swings if swings else None,
        "called_strikes": totals["called_strikes"] / taken if taken else None,
        "ground_balls": totals["ground"] / tracked if tracked else None,
        "pull": totals["pull"] / placed if placed else None,
    }
