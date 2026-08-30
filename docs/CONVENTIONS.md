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

The weights assume three completed seasons of history, which every component
has today: Triple-A tracking begins in 2023, so chase and exit speed have 2023
through 2025 behind them and get the full window like everything else.

That will not be true the season tracking reaches a new level, and the weights
are the wrong thing to worry about when it does. `blend` renormalises per
component over the seasons that actually carry it, so a component with one year
behind it is that year rather than that year dragged two-thirds of the way to
neutral by absent data. What renormalising cannot supply is reliability: a
one-season factor has `REGRESSION_PA` and nothing else, where a three-season one
has the averaging as a second defence. A newly tracked level will therefore
carry the noisiest factors in the table for its first two years, and there is
no way to shorten that except to wait.

## Batted-ball geometry

| Constant | Value | Where | What it does |
|---|---|---|---|
| `CENTER_BAND` | 15° | `pitch_data.py` | Half-width of the middle of the field, so pull, centre and opposite field are rough thirds |
| `PLATE_X`, `PLATE_Y` | 125, 205 | `pitch_data.py` | Home plate in the gameday coordinate frame, the origin every spray angle is measured from |
| Foul tip | counted as a whiff | `pitch_data.py` | Classification of a pitch the batter got a piece of but did not control |
| `HARD_HIT_MPH` | 95 | `pitch_data.py` | Exit velocity at or above which a batted ball is counted as hard hit |

`CENTER_BAND` quietly determines every pull rate in the digest and the pull
park factor besides. Thirty degrees splits the field into even thirds, which is
tidy but arbitrary: pulled contact is not distributed evenly across the field,
and the band that best separates a genuine pull hitter from an average one is
an empirical question nobody has asked here.

The origin it is measured from is no longer a convention. Triple-A records a
measured distance alongside the landing coordinates, and for well-struck fly
balls the two describe the same event, so the assumed plate position can be
checked against them: across 642 such balls the committed `(125, 205)` gives a
scale of 2.39 feet per unit with a dispersion of 0.2%, and the best-fitting
origin on a wide grid is `(126, 204)` at 0.1%. The frame is therefore correct to
within about two feet, and the resulting 41% pull, 35% centre, 24% opposite
matches published major-league distributions. This is confirmed at Triple-A
only; the lower levels record no distance to check themselves against.

The trajectory labels the ground-ball and air rates are built from are a scorer's
judgement, and Triple-A's launch angles are the measurement to test them against.
They agree on 87.9% of 4,385 batted balls, and the resulting air rate reads 57.6%
where the measurement says 56.1%. So the label is sound but reads slightly airy,
mostly through line drives that left the bat below ten degrees. Since the bias is
shared by everyone in a league, it moves a percentile far less than it moves a
rate.

`HARD_HIT_MPH` is Statcast's own threshold, taken as-is so the number means what
a reader expects it to. It is a major-league convention applied to a level whose
population hits softer, which will put more Triple-A hitters below it than the
threshold was drawn to separate.

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

## Where exit velocity should end up

Average exit velocity is the wrong summary of a hitter's contact quality, and is
used here because it is the one the current cache can produce. A mean is dragged
around by mishits, which say more about the pitch than the hitter; the top decile
of a hitter's batted balls describes what he is capable of when he connects, and
separates hitters more sharply and sooner. The same argument applies to a pitcher
from the other end, where it is the damage he allows at his worst.

Switching costs a cache change rather than a rewrite. Only a running sum and a
count are stored per player per game, which cannot produce any percentile.
Keeping a small histogram instead — batted balls counted into one-mile-per-hour
bins — supports the 90th percentile, the mean and the hard-hit rate together,
stays about as compact as the three numbers it replaces, and needs no second
pass over the season. Whichever summary is chosen, the park factor has to be
built from the same one, since a factor measured on means cannot adjust a decile.

## Toward projection

The digest measures what a prospect has done. Estimating what he will do is a
different problem, and enough of its inputs now exist to say what it would take
rather than only that it would be nice.

What is already here: an append-only store of every game log, league baselines
that make a rate comparable across levels, park factors per league-season, and
top-thirty rankings for all thirty organizations. That last piece is why the
same framework would extend to any club without new plumbing — the tracked list
is the only Mariners-specific thing in the project.

The binding constraint is labels, not features. A projection model learns from
prospects whose outcomes are known, which means cohorts old enough to have had
major-league careers. Triple-A tracking begins in 2023, so any model using exit
velocity or chase rate has three cohorts, none of whom have finished arriving.
A model trained on what the lower levels record — the batted-ball mix, the
plate skills, age relative to level — can reach back much further, and would
have to, which means the tracked measurements are the least usable inputs
despite being the best ones.

That suggests the honest first step is not a network but a store: keep the
season pools rather than caching them for a day, so the training set accumulates
from now on instead of being reconstructed later from an API that does not
promise to keep serving old seasons.

### What would have to be acquired

Three things, none of which exist here and all of which are reachable with the
client already in the repo — `sportId=1` returns major-league schedules and
season pools for seasons as old as 2015, checked rather than assumed.

**Major-league outcomes**, which are the labels: what the prospects of past
years actually became.

**A major-league run environment**, so those outcomes are comparable across
years and parks. This does not need componentising the way the minor-league
factors are. Components exist here because skills are reported individually and
each has to be adjusted against its own measurement; a label is a single number,
and a runs factor applied to hitting and pitching is enough.

**Past minor-league seasons**, which are the features. Season-level stats
backfill cheaply. The play-by-play behind the batted-ball and tracked skills
does not: it is one request per game, so a decade across the four full-season
levels is on the order of a hundred thousand requests against an unauthenticated
public API. Any model reaching back more than a few years is therefore trained
on season-feed inputs, whatever the recent cohorts have available.

### What it could not project

Hitting and pitching, and nothing else. Nothing in this data supports a
defensive measure: there is no fielding location, no route or reaction data, and
outs recorded by position say more about where a club put a player than about
how well he played there.

The consequence lands on the label rather than the feature list, which is the
easy mistake. A model trained to predict WAR would be asked to predict something
its inputs cannot see, and would learn to attribute defensive value to batting
lines. It would look accurate across a whole cohort and be wrong in a specific,
predictable direction: worst on exactly the glove-first shortstops and catchers
whose value is least visible in a slash line. The label therefore has to be an
offence-only measure — wRC+ for hitters, already computed here and already
adjusted for park and league, and a run-prevention figure for pitchers — and the
output has to be named for what it is.

Comparing across positions is still available, because a positional adjustment
is a scarcity term rather than a defensive valuation: it prices how hard the
position is to fill, and applies from the position a player occupies without any
claim about how well he plays it. A shortstop and a first baseman with identical
bats can therefore be ranked against each other. What stays invisible is the
variation within a position — this shortstop against that one — which is the
residual the data genuinely does not hold.

The adjustment does reintroduce a defensive judgement through the input, which
is worth being explicit about because it is quiet. Applying it to a prospect
means assuming the position he will occupy in the majors, and prospects sliding
down the defensive spectrum is among the most common developmental outcomes
there is. Taking the organization's current listing at face value would quietly
credit every shortstop with shortstop scarcity, including the ones who will not
be shortstops. The honest treatment is to carry that as an assumption stated
alongside the projection rather than as a number folded into it.

One more shape question follows from choosing wRC+: it is a rate, so a model
trained on it projects quality and says nothing about how much of it there will
be. Value needs playing time as well, which is a second and largely unrelated
problem — durability and opportunity rather than skill — and is better modelled
separately than smuggled into a rate.
