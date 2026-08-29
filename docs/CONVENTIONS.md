# Numbers chosen rather than measured

Most of what the digest reports is derived from the season it describes. League
run environments, wOBA scales, FIP constants and every percentile are computed
from the pool of players at that level, and change as the season does. Nothing
in this file applies to those.

This file is about the rest: the numbers that were picked. Some are conventions
inherited from published sabermetrics, where using the standard value matters
more than using a bespoke one. Some are thresholds that decide what is worth
putting in an email, which is a question of taste before it is a question of
data. All of them are stated here in one place, because a constant that lives
only at its call site is a constant nobody revisits.

Each is a candidate for being learned rather than chosen. The last section
orders them by how much the output would move.

## Inherited sabermetric constants

These come from published work and are deliberately not tuned. Departing from
them would make the numbers incomparable to every other source a reader might
check, which costs more than the precision it would buy.

| Constant | Value | What it does |
|---|---|---|
| `WOBA_WEIGHTS` | .69 walk, .72 HBP, .89 1B, 1.27 2B, 1.62 3B, 2.10 HR | Weighs each way of reaching base in raw wOBA |
| `RUN_VALUES` | .33 walk, .36 HBP, .47 1B, .78 2B, 1.09 3B, 1.40 HR, −.27 out | Linear weights behind wRC+ |
| FIP coefficients | 13 HR, 3 BB+HBP, −2 K | The published FIP formula |
| FIP constant fallback | 3.10 | Used only when a league reports no innings at all |
| Road-share halving | ½ | Pulls every park factor halfway to neutral before it touches a player's line |

Two of these deserve a closer look.

**The wOBA weights are harmless.** Only their ratios survive: the set is
rescaled per league-season so that league wOBA equals league OBP, which means
the absolute values wash out. Replacing them with minor-league weights would
change almost nothing.

**The run values are not harmless.** They are calibrated to major-league
scoring and applied to leagues that score differently, and they are the last
major-league assumption left in wRC+. Proper linear weights come from run
expectancy by base-out state, which needs the play-by-play this project already
caches. See the priority list below.

**The halving assumes half a player's games are on the road**, which is close
enough to true that the error is small, but it is a flat assumption applied to
every player regardless of his actual home-road split, which the game logs
already record.

## Sample floors

| Constant | Value | Where | What it does |
|---|---|---|---|
| `minimum_sample` | 50 | `config/settings.json` | Plate appearances, or batters faced, before a player gets a production figure, a slash line or any percentile |
| League pool floor | 20 | `baselines.py` | A league with fewer qualified players than this returns no percentile at all |

Below a floor a percentile is noise wearing the costume of insight, so some
floor has to exist. The specific values are round numbers.

The floor is one number covering six levels and both sides of the ball, which
is the least defensible thing about it. Fifty plate appearances says something
quite different about a Triple-A hitter than a Dominican Summer League one, and
different skills stabilise at very different rates: contact rate settles inside
a hundred plate appearances, while anything built on home runs takes most of a
season. A single floor is necessarily too strict for the fast-stabilising
metrics and too generous for the slow ones.

## Park factor construction

| Constant | Value | Where | What it does |
|---|---|---|---|
| `REGRESSION_PA` | 4,000 | `park_builder.py` | Shrinks a park's raw home-road ratio toward neutral by `sample / (sample + 4000)` |
| `SEASON_WEIGHTS` | 5, 3, 1 | `park.py` | Weighs the three most recent completed seasons when blending |
| Season window | 3 | `park.py` | How far back the blend reaches, implied by the weight tuple |
| `describe` threshold | 6% | `park.py` | How far from neutral a component must sit before `describe` calls a park notable, used for inspection rather than by the digest |

The first two scale every park adjustment in the system, and they are the
clearest supervised problem in the project. Both express the same instinct —
that one season of one park is a small sample and older seasons are less
relevant — but the strength of that shrinkage and the shape of that decay were
chosen to look sensible rather than fitted to anything.

The honest test is which values best predict a park's behaviour in a season
they were not built from. That is tractable, because per-season factors are
stored in `config/park_factors/` rather than only the blend.

## Batted-ball geometry

| Constant | Value | Where | What it does |
|---|---|---|---|
| `CENTER_BAND` | 15° | `pitch_data.py` | Half-width of the middle of the field, so pull, centre and opposite field are rough thirds |
| `PLATE_X`, `PLATE_Y` | 125, 205 | `pitch_data.py` | Home plate in the gameday coordinate frame, the origin every spray angle is measured from |
| Foul tip | counted as a whiff | `pitch_data.py` | Classification of a pitch the batter got a piece of but did not control |

`CENTER_BAND` quietly determines every pull rate in the digest and the pull
park factor besides. Thirty degrees splits the field into even thirds, which is
tidy but arbitrary: pulled contact is not distributed evenly across the field,
and the band that best separates a genuine pull hitter from an average one is
an empirical question nobody has asked here.

The plate coordinates were checked against fielder positions rather than taken
on faith, but they are one pair of numbers for every venue, and the feed's
coordinate frame is not guaranteed identical everywhere.

## What counts as worth reporting

Everything in this section is editorial. There is no correct value, only a
digest that is too long or too short.

| Setting | Value | What it does |
|---|---|---|
| `depth.watchlist` | 10 | Ranks reported unconditionally, with season context |
| `hits` | 2 | Hits before a non-watchlist line is worth showing |
| `extra_base_hits` | 2 | Same, for extra-base hits |
| `home_runs` | 1 | Any home run qualifies |
| `rbi` | 3 | Runs batted in before an otherwise ordinary line qualifies |
| `stolen_bases` | 2 | Steals before a line qualifies |
| `strikeouts_pitched` | 6 | Strikeouts in an outing before it qualifies |
| `scoreless_innings_relief` | 2 | Scoreless relief innings before an outing qualifies |
| `min_scoreless_outings` | 3 | Consecutive scoreless outings before a streak is reported |
| `min_hit_streak` | 5 | Games with a hit before a streak is reported |
| `rolling_windows_days` | 7, 15 | The two windows hot and cold form are measured over |
| `min_rolling_plate_appearances` | 15 | Sample before a rolling split is reported at all |
| `min_rolling_ops` | 0.90 | OPS at or above which a hitter is hot |
| `max_rolling_ops` | 0.55 | OPS at or below which a hitter is cold |
| `moves_lookback_days` | 2 | How far back transactions are read for the digest |

These are absolute counting-stat cutoffs applied identically at every level,
with no league or park context. Two hits is two hits whether they came in the
Pacific Coast League or the Florida State League, and .900 OPS is a different
achievement in each. The section as a whole is asking "was this surprising?"
and answering it with a fixed number, which is exactly the kind of question a
model answers better than a threshold.

The tracked list's own depth is not a choice at all. Thirty is how many players
MLB Pipeline ranks per organization, so it is a fact about the source rather
than a setting.

## Operational

None of these change a reported number. They are recorded so that nothing in
the codebase is unaccounted for.

| Constant | Value | What it does |
|---|---|---|
| Play-by-play workers | 6 | Concurrent requests during a backfill, kept modest against an unauthenticated public API |
| Backfill checkpoint | 500 games | How often a long gather writes its cache |
| Gathered levels | Triple-A, Double-A, High-A, Single-A | Which levels the daily top-up covers, the complex and Dominican leagues costing thousands of games for skills no ranked prospect is judged on |
| HTTP timeout, retries, backoff | 20s, 3 attempts, exponential | Behaviour against a flaky public endpoint |
| Leaderboard page size | 1,000 | Pagination |
| Capture timeout | 30s | How long the ranking scrape waits for a page, generous because it runs twice a year |
| Expected list depth | 30 | Sanity check that a scraped page actually loaded |
| Ranking staleness dates | 31 March, 31 July | When the digest starts warning that Pipeline has probably refreshed |
| Transaction scan start | 1 January | How far back a season's moves are read |

## Where a model would earn its keep

Ordered by how much the output would move.

1. **`REGRESSION_PA` and `SEASON_WEIGHTS`.** They scale every park adjustment,
   the training data is already on disk as per-season factors, and the target
   is unambiguous: predict a park's next-season behaviour. This is a fitted
   two-parameter problem, not a research project.

2. **`RUN_VALUES`.** Deriving league-specific linear weights from base-out run
   expectancy would remove the last major-league assumption in wRC+. The
   play-by-play needed is already cached; what is missing is the run
   expectancy table, which is a season's worth of aggregation per league.

3. **The sample floors.** One number for six levels and both sides of the ball
   is unlikely to be right anywhere. The principled version is per-metric and
   per-level, set where a rate's split-half correlation says it has stabilised
   — measurable directly from the store, which accumulates every game log.

4. **The notability and form thresholds.** These want replacing wholesale
   rather than tuning: the question is how unusual a line was for that player
   in that league, which is a distribution the baselines already compute. A
   learned surprise measure would also fix the level-blindness for free.

5. **`CENTER_BAND`.** It determines every pull rate and the pull park factor
   from a single angle chosen for tidiness. The spray data to fit it properly
   is already gathered.

Two questions here are not about constants at all, and are open in a stronger
sense. The rookie and complex leagues have no park factors, because a shared
back-field is not really a park and the schedules are too short to measure one.
And altitude moves called strikes for reasons nobody has explained, which is
worth understanding before the called-strike factor carries much weight.
