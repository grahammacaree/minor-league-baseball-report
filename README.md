# minor-league-baseball-report

A daily email digest of the Seattle Mariners farm system, built around the MLB Pipeline
top 30 prospect list.

No game recaps, no LLM-written narrative. Just the prospects.

## What the email contains

**Played yesterday.** Every top-ten prospect's line, including an explicit "did not
play" so absences are visible, plus anyone from 11–30 who cleared a threshold worth
an email. Grouped by level, since a level is a difficulty and the reader is comparing
within one. Where everyone at a level faced the same club, the opponent moves up to
the heading rather than repeating down the section.

**Top ten season lines.** The season so far, with each player ranked against his own
league on five skills, and every level he has left this year listed beneath. Hot and
cold form is marked in place with an arrow rather than given its own section.

**Moves and injuries**, and, when there are any, players who have just joined the
organization or left it.

Names link to the player's page. Positions lead, so the shape of the system is
readable at a glance.

## What it is trying to be

A prospect's raw line is close to meaningless on its own. Half of a good batting
average can be the park, and half of what looks like a breakout can be a level that
scores more runs than the one below it. So every rate here is placed in a context
before it is reported:

- **Against his league, not his level.** The Texas League and the Eastern League are
  both Double-A and are not the same run environment.
- **Against his park, per component.** A park that suppresses home runs is saying
  something different from one that suppresses strikeouts, and a prospect's contact
  rate deserves the same correction as his slugging.
- **Against his age.** A twenty-year-old holding his own in Double-A is the entire
  story, so age sits beside the line rather than being folded into it.

The reasoning behind each number is in [docs/METRICS.md](docs/METRICS.md), and the
numbers that were chosen rather than measured are collected in
[docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## Data sources

Everything comes from public MLB endpoints, unauthenticated and free:

| Source | Used for |
|--------|----------|
| `config/prospects.json` | The Pipeline top 30 ranking |
| `config/prospect_rankings.json` | Every organization's top 30, for player ids and for spotting acquisitions |
| `config/park_factors/` | Per-component park effects, built offline and committed |
| `statsapi.mlb.com` leaderboards | League baselines, and each player's season by level |
| `statsapi.mlb.com` game logs | Per-player daily lines, at whatever level they're playing |
| `statsapi.mlb.com` play-by-play | Whiffs, ground balls and spray, which no season feed reports |
| `statsapi.mlb.com` transactions | Roster moves, injuries, and who has entered or left the system |
| `statsapi.mlb.com` rosters | Resolving any prospect the rankings did not name an id for |

Game logs are fetched per player rather than per affiliate, so a midseason promotion
needs no configuration change.

The daily run is deliberately cheap. Play-by-play costs a request per game, so the
season-scale gathering behind park factors happens offline, and the daily job asks
only about yesterday's outings.

## Keeping the list honest

A committed ranking describes the system on the day it was captured, and the system
does not hold still. Two things are read from the transaction feed to keep it current
between captures:

- A prospect **traded away** stops being tracked, rather than being reported on all
  season for another organization's farm.
- A prospect **traded in** starts being followed the day he arrives, if any
  organization had him in its top thirty. This is why every club's list is captured,
  not just the Mariners': it is the test for whether an acquisition is worth
  following.

A player traded within a level is the awkward case, since the leaderboards pool his
season into a single row under his new club and the halves cannot be separated. His
park and league are blended by how much of the season each accounts for instead, and
the header names both leagues so the mixture is visible.

## Maintaining the ranking

`mlb.com/prospects/mariners` only serves the top five to non-browser clients — the rest
of the list appears only after a click. It cannot be fetched with a plain HTTP request,
so the rankings are captured with a browser and committed.

MLB Pipeline reworks the org lists twice a season, in the spring and again after the
trade deadline. When a refresh is due, the digest says so.

```bash
scripts/capture-rankings
```

That walks all thirty organizations and writes `config/prospect_rankings.json`, reading
only an ordered list of player ids off each page; names and positions come from the Stats
API. A scheduled workflow runs the same job after each Pipeline update and opens a pull
request with the result.

Those ids are worth more than the rankings themselves. They are read off the same pages
the tracked list comes from, so they resolve prospects the Mariners list names without
an id — usually recent draftees with no roster entry yet — without a roster scan.

Playwright is needed for that capture alone. The daily digest uses the standard library
only, so the job that actually sends mail has no install step beyond Python.

## Setup

```bash
pip install -r requirements.txt
mkdir -p ~/.config/mlb-report
cp config/user.example.json ~/.config/mlb-report/user.json
cp config/env.example ~/.config/mlb-report/.env && chmod 600 ~/.config/mlb-report/.env
```

`user.json` holds the recipient list; `.env` holds SMTP credentials. Neither is committed,
and the split means adding someone to the digest never touches secrets. In CI the SMTP
values come from environment variables instead, which take precedence over the file.
Override the config location with `MLB_REPORT_CONFIG_HOME`.

Set `send_when_quiet` to `false` in `user.json` to skip the email on nights when nothing
cleared the bar.

## Usage

```bash
./scripts/run              # build and send today's digest
./scripts/run --dry-run    # print the digest to stdout instead of emailing
```

## Development

```bash
ruff check .
pytest
```

Every fetched game log is appended to a local newline-delimited JSON store, so the
dataset accumulates over the season and is available for later analysis independent of
the daily email path.
