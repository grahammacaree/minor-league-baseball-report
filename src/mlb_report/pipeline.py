from __future__ import annotations

from datetime import date

from . import (
    baselines,
    diagnostics,
    evaluation,
    fetchers,
    park,
    prospects,
    rankings,
    statsapi,
    store,
)
from . import digest as digest_module
from .digest import MAJORS, Digest, PlayerContext


def _latest_levels(history: list) -> dict[int, str]:
    """Each player's most recent level, which is the one to report on."""
    latest: dict[int, tuple] = {}
    for log in history:
        key = (log.game_date, log.game_pk)
        if log.player_id not in latest or key > latest[log.player_id][0]:
            latest[log.player_id] = (key, log.level)
    return {player_id: value[1] for player_id, value in latest.items()}


def _contexts(
    tracked: list[prospects.Prospect],
    history: list,
    report_date: date,
    season: int,
    settings: dict,
    promoted: set[int] | None = None,
    changed_org: set[int] | None = None,
    run: diagnostics.Run | None = None,
) -> dict[int, PlayerContext]:
    """
    Season context for every tracked prospect, in league terms.

    Both groups are pulled because a ranking's position label does not always
    match how a player is being used. Players who changed level mid-season get
    one leaderboard row per stint, so the current level is reported and the
    previous one kept as context — a promotion is exactly the thing worth
    seeing.

    A player traded within a level is the awkward case: the leaderboards pool
    his line into one row under his new club, so the halves cannot be told
    apart. His park and his league are blended instead, weighted by how much of
    the season each accounts for, which measures the whole line against the mix
    of conditions it was actually earned in.

    The majors are left out of the pool entirely. A promoted player's season
    then reads as the last thing he did in the minors, and his age no longer
    gets measured against a major league average he is obviously young for.
    """
    tracked_ids = {p.player_id for p in tracked if p.player_id}
    sport_ids = statsapi.AFFILIATE_SPORT_IDS
    minimum = settings["minimum_sample"]
    current_level = _latest_levels(history)

    contexts: dict[int, PlayerContext] = {}
    for group in ("hitting", "pitching"):
        pool = baselines.load_pools(sport_ids, season, group, as_of=report_date)
        leagues = {player.league_id for player in pool}
        parks = park.load(sorted(leagues), season)
        league_baselines = baselines.build(pool, group, minimum[group], parks=parks)

        if run is not None:
            run.record(
                f"{group} pool", f"{len(pool):,} players, {len(leagues)} leagues"
            )
            # Factors are per league, not per group, so once is enough.
            if group == "hitting":
                diagnostics.park_coverage(run, sorted(leagues), season)
        # Which league a club plays in, so a former club can be looked up from
        # the shares without another request. Every club is in the pool already,
        # by way of its own players.
        by_league = {player.team_id: player.league_id for player in pool}

        stints: dict[int, list] = {}
        for player in pool:
            if player.player_id in tracked_ids:
                stints.setdefault(player.player_id, []).append(player)

        for player_id, player_stints in stints.items():
            current, earlier = evaluation.split_stints(
                player_stints, current_level.get(player_id)
            )
            baseline = league_baselines.get(current.league_id)
            if baseline is None:
                # Too few qualified players in the league to rank against, so
                # the player is left out of the digest entirely. Worth saying:
                # from the outside it looks the same as not having played.
                if run is not None:
                    run.warn(
                        f"No {group} baseline for league {current.league_id}: "
                        f"{current.name} has no season line in this digest."
                    )
                continue

            shares = (
                fetchers.club_shares(player_id, group, season, current.sport_id)
                if player_id in (changed_org or set())
                else {}
            )
            known = {
                team: weight
                for team, weight in shares.items()
                if by_league.get(team) in league_baselines
            }
            if len(known) > 1:
                baseline = baselines.blend(
                    [
                        (league_baselines[by_league[team]], weight)
                        for team, weight in known.items()
                    ]
                )
                park_factor = parks.blended_runs_factor(known)
                components = parks.blended(known)
            else:
                park_factor = parks.runs_factor(current.team_id)
                components = parks.for_team(current.team_id)

            result = evaluation.evaluate(
                current,
                baseline,
                minimum[group],
                park_factor=park_factor,
                park_components=components,
            )
            if player_id in contexts and not result.has_enough_sample:
                continue  # keep whichever group the player has a real season in

            priors = []
            for previous in earlier:
                prior_baseline = league_baselines.get(previous.league_id)
                if prior_baseline is None:
                    continue
                prior_result = evaluation.evaluate(
                    previous,
                    prior_baseline,
                    minimum[group],
                    park_factor=parks.runs_factor(previous.team_id),
                    park_components=parks.for_team(previous.team_id),
                )
                if line := evaluation.render_prior(prior_result):
                    priors.append(line)

            contexts[player_id] = PlayerContext(
                age=evaluation.age_context(current, baseline),
                production=evaluation.render_production(result),
                skills=evaluation.render_skills(result),
                priors=priors,
                promoted=player_id in (promoted or set()),
            )
    return contexts


def build_digest(
    report_date: date,
    season: int,
    settings: dict,
    run: diagnostics.Run | None = None,
) -> Digest:
    """
    Refresh the local history, then report on it.

    Trends need more than one day of context, so the digest is built from the
    accumulated store rather than from the day's fetch alone.
    """
    org_id = settings["org"]["team_id"]
    tracked = prospects.tracked_prospects(season)

    # Who the organization actually has is settled before anything is fetched,
    # so a prospect traded in is followed from the day he arrives and one traded
    # away stops being fetched at all. The window runs back to the capture
    # itself: a July trade is still the reason the list is wrong in September,
    # long after it stopped being news.
    # Scanned from the turn of the year rather than from the capture, because
    # the two questions want different windows: whether to follow a player is
    # about what has changed since the list was committed, while whether his
    # numbers need blending is about anything that happened this season.
    joined, left = fetchers.crossings(org_id, season, date(season, 1, 1), report_date)
    changed_org = {move.player_id for move in joined}
    tracked, departed = prospects.without_departures(tracked, left)
    tracked, acquired = prospects.with_acquisitions(
        tracked,
        [move for move in joined if move.effective_date >= rankings.captured_on()],
        rankings.load(),
    )

    levels = fetchers.current_levels(tracked, org_id, season)
    promoted = fetchers.in_majors(levels)
    logs = fetchers.game_logs(tracked, org_id, season, levels=levels)
    added = store.save(season, logs)

    if run is not None:
        run.record("report date", f"{report_date} (season {season})")
        run.record("tracked", f"{len(tracked)} prospects")
        run.record("game logs", f"{len(logs):,} fetched, {added:,} new")
        run.record("crossings", f"{len(joined)} in, {len(left)} out")
        if unresolved := [p.name for p in tracked if not p.player_id]:
            run.warn(
                f"No player id for {', '.join(unresolved)}: nothing of theirs "
                "is fetched or reported."
            )
        diagnostics.pitch_coverage(run, statsapi.FULL_SEASON_SPORT_IDS, season)

    since, until = fetchers.lookback_window(
        report_date, days=settings["moves_lookback_days"]
    )
    moves = fetchers.transactions(tracked, org_id, season, since, until)
    # Followed all season, but reported only while it is still news. A trade
    # from July would otherwise head the digest into September.
    recent = [pair for pair in acquired if since <= pair[0].effective_date <= until]
    recently_gone = [move for move in departed if since <= move.effective_date <= until]
    # Major league games are dropped on the way out of the store as well as on
    # the way in, since a player promoted before this rule existed already has
    # them on disk. Everything downstream -- the day's line, streaks, notable
    # performances, which level is current -- then sees only the minors.
    history = [log for log in store.load(season) if log.level != MAJORS]

    # Only yesterday's outings, so the daily run makes a handful of play-by-play
    # requests rather than the season-scale pass the park factors need.
    today = [log for log in history if log.game_date == report_date]
    whiffs = fetchers.whiffs_for_outings(today)

    contexts = _contexts(
        tracked,
        history,
        report_date,
        season,
        settings,
        promoted=promoted,
        changed_org=changed_org,
        run=run,
    )

    digest = digest_module.build(
        report_date=report_date,
        tracked=tracked,
        history=history,
        moves=moves,
        settings=settings,
        contexts=contexts,
        whiffs=whiffs,
        arrivals=recent,
        departures=recently_gone,
    )

    if run is not None:
        run.record("season lines", f"{len(contexts)} of {len(tracked)} tracked")
        played = sum(len(lines) for lines in digest.played.values())
        run.record(
            "digest",
            f"{played} played across {len(digest.played)} levels, "
            f"{len(digest.moves)} moves, {len(digest.arrivals)} in, "
            f"{len(digest.departures)} out",
        )
        # The bars are the part that fails without complaining, so they are
        # counted rather than assumed: a run where every player is short of
        # them is a cache that never loaded, not a quiet day.
        bars = [
            context.skills.count(evaluation.SKILL_SEPARATOR) + 1
            if context.skills
            else 0
            for context in contexts.values()
        ]
        run.record("skill bars", f"{sum(bars)} across {len(bars)} players")
        if bars and not sum(bars):
            run.warn(
                "Not one skill bar was rendered, so every player is being "
                "reported without any league context at all."
            )

    captured = prospects.captured_on()
    if prospects.refresh_due(captured, as_of=report_date):
        digest.warnings.append(
            f"The top 30 was captured on {captured} and MLB Pipeline has updated "
            "its org lists since. Time to refresh `config/prospects.json`."
        )
    return digest
