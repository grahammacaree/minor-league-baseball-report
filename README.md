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
| `mlb.com/prospects/mariners` | The Pipeline top 30 ranking (server-rendered HTML) |
| `statsapi.mlb.com` game logs | Per-player daily lines, at whatever level they're playing |
| `statsapi.mlb.com` transactions | Roster moves and injury placements |

Game logs are fetched per player rather than per affiliate, so a midseason promotion
needs no configuration change.

## Setup

```bash
pip install -r requirements.txt
cp config/user.example.json ~/.config/mlb-report/user.json
```

Edit `~/.config/mlb-report/user.json` to set the digest recipients. SMTP credentials go in
`~/.config/mlb-report/.env`, which is never committed. Override the config location with
`MLB_REPORT_CONFIG_HOME`.

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
