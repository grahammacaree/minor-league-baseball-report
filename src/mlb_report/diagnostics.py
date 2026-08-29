"""
What the run found, and what it went without.

Nearly every gap in this pipeline is silent by design. A missing park factor
file, a level whose play-by-play was never gathered and a cache written by an
older shape all read as "no data", and the digest reports the skills it can
measure rather than refusing to arrive. That is the right bargain for the
email and a poor one for the morning after, when the question is why half the
bars vanished and the only way to find out is to run the whole thing again.

Nothing here changes what the digest says. It records what the run had to work
with, so a thin digest can be told apart from a thin farm system.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import park, pitch_data


@dataclass
class Run:
    """Facts gathered as the digest is built, reported once at the end."""

    facts: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def record(self, label: str, value: object) -> None:
        self.facts.append((label, str(value)))

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def pitch_coverage(run: Run, sport_ids: tuple[int, ...], season: int) -> None:
    """
    How many games of play-by-play each level has behind it.

    A level at zero is the failure that hides best: every batted-ball skill is
    dropped from the digest and nothing anywhere says so.
    """
    for sport_id in sport_ids:
        held = len(pitch_data.load_cached(sport_id, season))
        run.record(f"play-by-play cached, sport {sport_id}", f"{held:,} games")
        if not held:
            run.warn(
                f"No play-by-play for sport {sport_id} in {season}: whiff, "
                "grounder, spray and home-run-per-fly bars will be missing. "
                "Run scripts/gather-pitch-data."
            )


def park_coverage(run: Run, league_ids: list[int], season: int) -> None:
    """
    Which leagues have factors on disk, and how stale they are.

    Factors are built from completed seasons, so the current one never has its
    own; a league with nothing at all is the thing worth saying.
    """
    missing = [league for league in league_ids if not park.available_seasons(league)]
    run.record(
        "park factors", f"{len(league_ids) - len(missing)}/{len(league_ids)} leagues"
    )
    if missing:
        run.warn(
            "No park factors for league(s) "
            f"{', '.join(str(league) for league in sorted(missing))}: those "
            "players are being measured unadjusted. Run "
            "scripts/build-park-factors."
        )


def render(run: Run) -> str:
    lines = ["## Digest run", ""]
    lines += [f"- {label}: {value}" for label, value in run.facts]
    if run.warnings:
        lines += ["", "### Warnings", ""]
        lines += [f"- {warning}" for warning in run.warnings]
    return "\n".join(lines)


def emit(run: Run, stream=None) -> None:
    """
    Report to the log, and to the run summary when there is one.

    Warnings are also written as workflow annotations, which is what puts them
    at the top of the run rather than several hundred lines into a log nobody
    opens on a green build.
    """
    stream = stream or sys.stdout
    print(render(run), file=stream)

    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(render(run) + "\n")

    if os.environ.get("GITHUB_ACTIONS"):
        for warning in run.warnings:
            print(f"::warning::{warning}", file=stream)
