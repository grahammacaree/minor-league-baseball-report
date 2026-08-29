# minor-league-baseball-report

A daily email digest of the Seattle Mariners farm system, built around the MLB Pipeline
top 30 prospect list.

The digest covers:

- **Watchlist (top 10)** — every prospect's line from yesterday, including explicit
  "did not play" so absences are visible.
- **Notable performances (11–30)** — threshold-driven highlights rather than full box scores.
- **Trends and streaks** — hit streaks, rolling 7/15-day splits, scoreless-outing runs.
- **Moves and injuries** — promotions, demotions, IL placements and activations.

No game recaps, no LLM-written narrative. Just the prospects.

## Data sources

Everything comes from public MLB endpoints, unauthenticated and free:

| Source | Used for |
|--------|----------|
| `config/prospects.json` | The Pipeline top 30 ranking |
| `config/prospect_rankings.json` | Every organization's top 30, for spotting acquisitions |
| `statsapi.mlb.com` rosters | Resolving prospect names to MLB player ids |
| `statsapi.mlb.com` game logs | Per-player daily lines, at whatever level they're playing |
| `statsapi.mlb.com` transactions | Roster moves and injury placements |

Game logs are fetched per player rather than per affiliate, so a midseason promotion
needs no configuration change.

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
