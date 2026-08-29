from __future__ import annotations

from datetime import date

from . import digest as digest_module
from . import fetchers, prospects, store
from .digest import Digest


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

    digest = digest_module.build(
        report_date=report_date,
        tracked=tracked,
        history=store.load(season),
        moves=moves,
        settings=settings,
    )

    captured = prospects.captured_on()
    if prospects.refresh_due(captured, as_of=report_date):
        digest.warnings.append(
            f"The top 30 was captured on {captured} and MLB Pipeline has updated "
            "its org lists since. Time to refresh `config/prospects.json`."
        )
    return digest
