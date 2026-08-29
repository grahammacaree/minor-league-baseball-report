from __future__ import annotations

from datetime import date

from . import baselines, evaluation, fetchers, park, prospects, statsapi, store
from . import digest as digest_module
from .digest import Digest, PlayerContext


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
) -> dict[int, PlayerContext]:
    """
    Season context for every tracked prospect, in league terms.

    Both groups are pulled because a ranking's position label does not always
    match how a player is being used. Players who changed level mid-season get
    one leaderboard row per stint, so the current level is reported and the
    previous one kept as context — a promotion is exactly the thing worth
    seeing.
    """
    tracked_ids = {p.player_id for p in tracked if p.player_id}
    sport_ids = statsapi.AFFILIATE_SPORT_IDS + (fetchers.MLB_SPORT_ID,)
    minimum = settings["minimum_sample"]
    current_level = _latest_levels(history)

    contexts: dict[int, PlayerContext] = {}
    for group in ("hitting", "pitching"):
        pool = baselines.load_pools(sport_ids, season, group, as_of=report_date)
        leagues = {player.league_id for player in pool}
        parks = park.load(sorted(leagues), season)
        league_baselines = baselines.build(pool, group, minimum[group], parks=parks)

        stints: dict[int, list] = {}
        for player in pool:
            if player.player_id in tracked_ids:
                stints.setdefault(player.player_id, []).append(player)

        for player_id, player_stints in stints.items():
            current, previous = evaluation.split_stints(
                player_stints, current_level.get(player_id)
            )
            baseline = league_baselines.get(current.league_id)
            if baseline is None:
                continue

            result = evaluation.evaluate(
                current,
                baseline,
                minimum[group],
                park_factor=parks.runs_factor(current.team_id),
                park_components=parks.for_team(current.team_id),
            )
            if player_id in contexts and not result.has_enough_sample:
                continue  # keep whichever group the player has a real season in

            prior = None
            if previous is not None:
                prior_baseline = league_baselines.get(previous.league_id)
                if prior_baseline is not None:
                    prior_result = evaluation.evaluate(
                        previous,
                        prior_baseline,
                        minimum[group],
                        park_factor=parks.runs_factor(previous.team_id),
                        park_components=parks.for_team(previous.team_id),
                    )
                    prior = evaluation.render_prior(prior_result)

            contexts[player_id] = PlayerContext(
                age=evaluation.age_context(current, baseline),
                production=evaluation.render_production(result),
                skills=evaluation.render_skills(result),
                profile=evaluation.render_profile(result),
                prior=prior,
            )
    return contexts


def build_digest(report_date: date, season: int, settings: dict) -> Digest:
    """
    Refresh the local history, then report on it.

    Trends need more than one day of context, so the digest is built from the
    accumulated store rather than from the day's fetch alone.
    """
    org_id = settings["org"]["team_id"]
    tracked = prospects.tracked_prospects(season)

    store.save(season, fetchers.game_logs(tracked, org_id, season))

    since, until = fetchers.lookback_window(
        report_date, days=settings["moves_lookback_days"]
    )
    moves = fetchers.transactions(tracked, org_id, season, since, until)
    history = store.load(season)

    digest = digest_module.build(
        report_date=report_date,
        tracked=tracked,
        history=history,
        moves=moves,
        settings=settings,
        contexts=_contexts(tracked, history, report_date, season, settings),
    )

    captured = prospects.captured_on()
    if prospects.refresh_due(captured, as_of=report_date):
        digest.warnings.append(
            f"The top 30 was captured on {captured} and MLB Pipeline has updated "
            "its org lists since. Time to refresh `config/prospects.json`."
        )
    return digest
