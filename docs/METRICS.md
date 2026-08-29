# Metrics

Every number in the digest, where it comes from, and what it assumes. Formulas
live in [`sabermetrics.py`](../src/mlb_report/sabermetrics.py); league context is
built in [`baselines.py`](../src/mlb_report/baselines.py).

## What the data can and cannot support

There is no Statcast in the minor leagues. No exit velocity, no launch angle, no
bat speed. Anything describing contact quality here is inferred from the
batted-ball mix and isolated power, and should be read as evidence rather than
measurement.

What the API does provide, via `stats=seasonAdvanced` (verified populated for
every affiliate level): swings, swinging strikes, balls in play, and hits and
outs broken out by trajectory (line, fly, ground, pop).

## League context

Baselines are computed per **league**, not per level. Double-A is not one run
environment: the Texas League and the Eastern League differ enough that a
shared baseline would import park and league effects into every comparison.
Observed 2026 run environments range from about 0.135 runs per plate appearance
in the International League to 0.144 in the Midwest League.

The pool comes from `/stats?stats=season|seasonAdvanced&group=...&sportId=N&playerPool=All`,
which returns every player at a level along with his league. The two feeds are
joined per player: counting stats come from the standard feed, swings and
batted-ball detail only exist on the advanced one.

## Production

### wOBA

Event weights are conventional (`WOBA_WEIGHTS`), but their absolute values do
not matter because the whole set is rescaled per league-season so that league
wOBA equals league OBP. Only the ratios between events carry meaning.

### wRC+

```
wRAA/PA   = linear weights runs / PA
wRC+      = 100 * ((wRAA/PA - lgwRAA/PA) + lgR/PA) / (PF * lgR/PA)
```

`lgR/PA` is measured directly from league runs scored. The linear weights in
`RUN_VALUES` are calibrated to major-league scoring, which leaves a systematic
offset when applied to a minor league; subtracting the league's own average
wRAA removes it. That subtraction is what guarantees a league-average line
indexes to exactly 100 at every level.

**Verification:** the median wRC+ among qualified regulars is 103 in the
International League, 102 in the Pacific Coast League, and 100 in the Texas
League. Regulars sitting a shade above 100 is expected, since the full pool
includes short call-ups and position players who are not regulars.

### FIP and FIP-

```
FIP  = (13*HR + 3*(BB+HBP) - 2*K) / IP + cFIP
FIP- = 100 * FIP / (PF * lgFIP)
```

`cFIP` is solved per league-season so that league FIP equals league ERA, so it
carries no imported assumption. Lower FIP- is better.

## Skills

Reported as percentile ranks within the player's own league, so the same number
means the same thing at every level.

| Skill | Hitters | Pitchers |
|-------|---------|----------|
| Contact | swings that make contact | strikeout rate |
| Power / damage | isolated power | ground-ball rate |
| Discipline / command | walk rate | walk rate, inverted |

Walk rate is inverted for pitchers, so a low rate ranks high.

Percentiles appear only once a player clears the sample floor in
`config/settings.json` (50 plate appearances or batters faced). Below that a
percentile is noise presented as insight, so no skill line is produced at all.

## Age relative to level

Reported next to the numbers and deliberately never inside them. A 20-year-old
posting a league-average line in Double-A is the signal; folding age into wRC+
would hide it. League average age is computed from the same qualified pool.

## Levels and stints

A player who changes level mid-season gets one leaderboard row per stint. The
level of his most recent game decides which is current, because someone
promoted in August may still have most of his season's plate appearances below.
The previous stint is reported underneath, since the change is usually the most
interesting thing about the line.

## Park factors

Computed per component, not just for runs. A park that suppresses strikeouts
is saying something different from one that suppresses home runs, and a
prospect's contact rate deserves the same context as his slugging.

Construction, per league-season, in
[`park_builder.py`](../src/mlb_report/park_builder.py):

1. The schedule feed maps every completed `gamePk` to its home club, which
   identifies the park.
2. Each club's `stats=gameLog` gives its per-game offensive line. Joining on
   `gamePk` recovers both sides of every game, so each park's totals pool both
   offences rather than only the home team's.
3. For each park and component, compare the pooled rate there against the rate
   the same clubs produced everywhere else.
4. Regress toward 1.0 by sample size: `1 + (raw - 1) * PA/(PA + 4000)`.
5. Normalize within the league so the mean is 1.0, which is what makes 1.0 mean
   "neutral for this league".

Hits in play are rated per ball in play; everything else per plate appearance.
Otherwise a park that changes the strikeout rate would move the hits-in-play
factor for the wrong reason.

Blended across the three most recent completed seasons:

```
PF = (5*PF[y-1] + 3*PF[y-2] + 1*PF[y-3]) / 9
```

Weights are renormalized over whatever seasons exist, so a park with only one
year of history is not dragged toward 1.0 by missing data.

Applied to a player's line, the runs factor is halved toward neutral —
`(PF + 1) / 2` — because roughly half his games are on the road.

**Verification (2025 Double-A):** Amarillo, at 3,600 feet, comes out hardest on
pitchers at 1.238 runs and 1.584 home runs. Dickey-Stephens Park in Arkansas is
the most suppressive at 0.867 runs and 0.700 home runs, with San Antonio beside
it; Reading's bandbox reads 1.232 for home runs. These match the parks'
reputations without any of that being asserted anywhere in the code.

The contact signal is there too: Amarillo suppresses strikeouts (0.924) while
Binghamton inflates them (1.112).

Rebuild after a season ends:

```bash
./scripts/build-park-factors --season 2026
```

### Open questions

The 5-3-1 weights are a convention, not a fitted result, and so is the 4,000 PA
regression constant. Both are candidates for validation: the honest test is
which values best predict a park's next-season behavior, which becomes a
tractable supervised problem now that several seasons of per-season factors are
stored in `config/park_factors/`.

Component factors beyond runs are computed and committed but not yet applied to
the skill percentiles. Adjusting a contact rate for park is a more speculative
step than adjusting run production, and is worth doing deliberately.

The same applies to `RUN_VALUES`. Proper linear weights are derived from run
expectancy by base-out state, which needs play-by-play data. Deriving
league-specific weights would remove the last major-league assumption in wRC+.
