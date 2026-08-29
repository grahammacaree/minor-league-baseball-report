"""
Capture every organization's Pipeline top 30.

This is the one part of the project that needs a browser. mlb.com serves five
prospects to a non-browser client and the remaining twenty-five only after a
click, which is why the tracked list was maintained by hand for so long.

It runs at the two points a year Pipeline reworks its lists, not daily, and
writes a committed file the rest of the project reads with the standard
library. Playwright is therefore a capture-time dependency rather than a
runtime one.

    scripts/capture-rankings

Names and positions come from the Stats API rather than the page, so the only
thing read out of the DOM is an ordered list of player ids. That keeps the
scrape to the one thing the API cannot answer — who Pipeline ranked, and where.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from typing import Any

from . import statsapi
from .config_loader import bundled_config_dir
from .rankings import RANKINGS_FILE

PROSPECTS_URL = "https://www.mlb.com/milb/prospects/{slug}"

# Every ranking row links to the player's story page, and nothing else on the
# page does. The id at the end of that URL is a genuine MLB player id.
_ROW_SELECTOR = 'a[href*="/stories/"]'
_STORY_HREF = re.compile(r"/stories/.+-(\d+)$")

EXPECTED_DEPTH = 30

# How long to let a page settle. Generous because this runs twice a year and a
# retry costs more than a wait does.
_TIMEOUT_MS = 30_000


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def org_directory(season: int) -> dict[str, dict]:
    """
    mlb.com's org slug to the Stats API's club record.

    The slugs are read off the page's own dropdown rather than guessed, but the
    club identity behind each one comes from the API, so abbreviations and team
    ids are the same values the rest of the project uses.
    """
    teams = statsapi.get("teams", sportId=1, season=season).get("teams", [])
    return {_normalize(team.get("teamName", "")): team for team in teams}


def org_slugs(page) -> list[str]:
    """The thirty org slugs, taken from the page's own team dropdown."""
    slugs = page.evaluate(
        """() => {
            for (const select of document.querySelectorAll('select')) {
                const values = [...select.options]
                    .map(o => o.value)
                    .filter(Boolean);
                if (values.includes('mariners')) return values;
            }
            return [];
        }"""
    )
    if len(slugs) != EXPECTED_DEPTH:
        raise RuntimeError(
            f"Expected {EXPECTED_DEPTH} organizations in the team dropdown, "
            f"found {len(slugs)}. The page layout has probably changed."
        )
    return slugs


def _dismiss_consent(page) -> None:
    """
    Accept the cookie banner, which otherwise swallows the expand click.

    A fresh browser profile meets it on the first page load and never again,
    so this is a no-op for the remaining twenty-nine organizations.
    """
    accept = page.locator("#onetrust-accept-btn-handler")
    try:
        if accept.count() and accept.first.is_visible():
            accept.first.click(timeout=_TIMEOUT_MS)
            page.wait_for_selector(
                "#onetrust-consent-sdk", state="hidden", timeout=_TIMEOUT_MS
            )
    except Exception:
        # The banner is incidental. If it will not go quietly, take it out of
        # the way rather than lose the capture over it.
        page.evaluate("() => document.getElementById('onetrust-consent-sdk')?.remove()")


def _expand(page) -> None:
    """Click through to the full thirty, if the list is still showing five."""
    button = page.get_by_role("button", name="Show Full List")
    if button.count():
        button.first.click()
        page.wait_for_function(
            "({selector, depth}) =>"
            " document.querySelectorAll(selector).length >= depth",
            arg={"selector": _ROW_SELECTOR, "depth": EXPECTED_DEPTH},
            timeout=_TIMEOUT_MS,
        )


def ranked_ids(page, slug: str) -> list[int]:
    """The org's ranked player ids, in ranking order."""
    page.goto(PROSPECTS_URL.format(slug=slug), timeout=_TIMEOUT_MS)
    page.wait_for_selector(_ROW_SELECTOR, timeout=_TIMEOUT_MS)
    _dismiss_consent(page)
    _expand(page)

    hrefs = page.eval_on_selector_all(
        _ROW_SELECTOR, "rows => rows.map(row => row.getAttribute('href'))"
    )
    ids: list[int] = []
    for href in hrefs:
        match = _STORY_HREF.search(href or "")
        if match:
            player_id = int(match.group(1))
            # A page that repeats a player would otherwise shift every rank
            # below him by one.
            if player_id not in ids:
                ids.append(player_id)
    return ids


def _position(person: dict) -> str:
    """
    The position as the ranking lists write it.

    The API calls every pitcher "P"; the hand is what a reader actually wants,
    and is what the tracked list has always carried.
    """
    abbreviation = person.get("primaryPosition", {}).get("abbreviation", "")
    if abbreviation != "P":
        return abbreviation
    hand = person.get("pitchHand", {}).get("code", "")
    return f"{hand}HP" if hand in ("L", "R") else "P"


def _describe(player_ids: list[int]) -> dict[int, dict[str, str]]:
    """Name and position for a batch of ids, from the Stats API."""
    described = {}
    for person in statsapi.people(player_ids):
        described[person["id"]] = {
            "name": person.get("fullName", ""),
            "position": _position(person),
        }
    return described


def capture_org(page, slug: str, directory: dict[str, dict]) -> dict[str, Any]:
    ids = ranked_ids(page, slug)
    described = _describe(ids)
    team = directory.get(_normalize(slug), {})
    return {
        "slug": slug,
        "name": team.get("name", slug),
        "abbreviation": team.get("abbreviation", ""),
        "team_id": team.get("id"),
        "prospects": [
            {
                "rank": rank,
                "player_id": player_id,
                "name": described.get(player_id, {}).get("name", ""),
                "position": described.get(player_id, {}).get("position", ""),
            }
            for rank, player_id in enumerate(ids, start=1)
        ],
    }


def capture_all(season: int, slugs: list[str] | None = None) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "Capturing rankings needs Playwright, which the daily run does not:\n"
            "  pip install playwright && playwright install chromium"
        ) from exc

    directory = org_directory(season)
    orgs = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        wanted = slugs or org_slugs_from(page)
        for slug in wanted:
            print(f"  {slug}", file=sys.stderr, flush=True)
            orgs.append(capture_org(page, slug, directory))
        browser.close()

    return {
        "source": PROSPECTS_URL.format(slug="{org}"),
        "captured": date.today().isoformat(),
        "season": season,
        "orgs": orgs,
    }


def org_slugs_from(page) -> list[str]:
    """Load any one org page, purely to read the dropdown listing all of them."""
    page.goto(PROSPECTS_URL.format(slug="mariners"), timeout=_TIMEOUT_MS)
    page.wait_for_selector("select", timeout=_TIMEOUT_MS)
    return org_slugs(page)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="capture-rankings",
        description="Capture every organization's Pipeline top 30.",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=date.today().year,
        help="season the rankings belong to (default: this year)",
    )
    parser.add_argument(
        "--orgs",
        nargs="*",
        help="org slugs to capture (default: all thirty)",
    )
    parser.add_argument(
        "--output",
        help=f"where to write (default: config/{RANKINGS_FILE})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = capture_all(args.season, args.orgs)

    shallow = [
        org["slug"] for org in payload["orgs"] if len(org["prospects"]) < EXPECTED_DEPTH
    ]
    if shallow:
        print(
            f"Warning: fewer than {EXPECTED_DEPTH} ranked for {', '.join(shallow)}.",
            file=sys.stderr,
        )

    path = args.output or (bundled_config_dir() / RANKINGS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = sum(len(org["prospects"]) for org in payload["orgs"])
    print(f"Captured {total} prospects across {len(payload['orgs'])} orgs to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
