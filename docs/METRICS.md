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

### Park adjustment, and the trap in it

Skills are park-adjusted, each against the component it belongs to — contact
and whiffs against the strikeout factor, power against extra-base hits,
discipline and command against walks. Contact is inverted first, since a park
that inflates strikeouts deflates contact.

**The entire league pool is re-ranked on adjusted values.** Adjusting one
player and looking him up in an unadjusted distribution would double-count,
crediting him for his park while his peers are still measured with theirs baked
in. A test pins this: two identical players in identical parks must land on the
same percentile no matter how extreme the park.

Because factors are normalized to a league mean of 1.0, the distribution itself
barely moves — Texas League strikeout rate at the 50th percentile shifts by
0.001 — so what changes is rank order, not scale. The effect is largest in the
crowded middle of a distribution and smallest at the tails, where a genuine
outlier has nobody to trade places with. A 40.5% strikeout rate is the 99th
percentile in the Texas League before and after adjustment, even though
Dickey-Stephens inflates strikeouts.

### Whiff rate is not park-independent

Contact and whiff rates are adjusted rather than treated as clean skill
measures, because parks visibly move them. Altitude predicts the strikeout
factor in two independent leagues:

| League (2025) | correlation(altitude, K factor) | parks |
|---|---|---|
| Triple-A | −0.66 | 10 |
| Double-A | −0.64 | 10 |

Thinner air flattens breaking balls, so high-altitude parks suppress
strikeouts: El Paso at 3,740 feet sits at 0.921 and Reno at 0.937, against
Sacramento at sea level at 1.100. Variation altitude cannot explain — Corpus
Christi is 30 feet up at 1.055 — is consistent with backdrop and sightline
effects.

The honest limitation: what is measured is **strikeouts**, which bundle
swinging strikes with called strikes and hitter approach. Game logs carry no
swing data, so a true swinging-strike factor would need play-by-play from the
game feed, roughly 1,800 games per league-season.

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

### What the comparison isolates

The only question worth asking of a park factor is what differs between the
numerator and the denominator. It should be the park and nothing else.

So a park's factor comes from **the home club's own games, both sides of the
ball, at home against on the road**. That club's hitters face a roughly random
draw of league pitching whether home or away, and its pitchers face a roughly
random draw of league hitting either way. The club's roster therefore sits on
both sides of the ratio and cancels.

Two alternatives fail this test, and the failure is measurable rather than
theoretical. Pooling every club's offence at a park, or using only visiting
offence, puts visiting hitters against the home staff in the numerator but not
in the denominator — so a strong home rotation reads as a pitcher-friendly
park.

`scripts/validate-park-factors` measures the leakage by correlating each park's
strikeout factor against the home staff's strikeout rate *in road games*, which
the park cannot legitimately influence:

| construction | Double-A | Triple-A |
|---|---|---|
| home club, both sides (used) | −0.26 | −0.21 |
| pooled offence | +0.20 | +0.21 |
| visiting offence only | +0.52 | +0.36 |

Year-over-year agreement is a poor tiebreaker and is reported with a warning: a
contaminated estimator inherits the stability of whatever contaminates it, and
pitching staffs persist across seasons. On runs the clean construction matches
the pooled one anyway (+0.70 against +0.69).

The residual −0.26 cannot be leakage, since the home staff is structurally
absent from the comparison. The likely explanation is roster construction —
organizations in strikeout-suppressing parks tending to carry higher-strikeout
arms — which would be a real correlation rather than a measurement artifact.

### Steps

1. The schedule feed maps every completed `gamePk` to its home club.
2. Each club's `stats=gameLog` gives its per-game offensive line. Joining on
   `gamePk` recovers the opposing line, so both sides of every game are counted.
3. For each club and component, compare its home games against its road games.
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
pitchers at 1.297 runs and 1.598 home runs. Dickey-Stephens Park in Arkansas is
the most suppressive at 0.820 runs and 0.682 home runs, with San Antonio beside
it. These match the parks' reputations without any of that being asserted
anywhere in the code.

Rebuild after a season ends, and check the construction still isolates the
park:

```bash
./scripts/build-park-factors --season 2026
./scripts/validate-park-factors --sport 12 --seasons 2025 2026
```

### Open questions

The 5-3-1 weights are a convention, not a fitted result, and so is the 4,000 PA
regression constant. Both are candidates for validation: the honest test is
which values best predict a park's next-season behavior, which becomes a
tractable supervised problem now that several seasons of per-season factors are
stored in `config/park_factors/`.

A swinging-strike factor built from play-by-play would separate whiffs from
called strikes, which the strikeout factor currently conflates. That is the
single largest improvement available to the contact and command percentiles.

The same applies to `RUN_VALUES`. Proper linear weights are derived from run
expectancy by base-out state, which needs play-by-play data. Deriving
league-specific weights would remove the last major-league assumption in wRC+.
