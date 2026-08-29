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

Play-by-play adds two things the season feed has no equivalent for: the split of
a strikeout into whiffs and called strikes, and where a batted ball landed. It
costs one request per game, so it is gathered offline rather than in the daily
run.

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

Five rates a side, each shown as the observed number followed by its percentile
rank within the player's own league, so the same rank means the same thing at
every level.

| | Hitters | Pitchers |
|---|---|---|
| Bat-to-ball | `Contact%` | `Whiff%` |
| Damage | `HR/FB` | `HR/FB↓` |
| Ball in the air | `Air%` | `GB%` |
| Direction | `Pull%` | `Pull%↓` |
| Plate discipline | `BB%` | `BB%↓` |

The two sides mirror each other deliberately. The same events describe both
participants, and a reader who has learned to read one column can read the
other.

Rates are named for what they measure rather than for the virtue they imply —
`Whiff%` rather than "swing-and-miss ability" — because a reader can check a
named rate anywhere else and cannot check a grade. The naming has to be exact
to be worth anything: `Whiff%` here is whiffs per swing, around 35%, and
calling it `SwStr%` would promise the per-pitch version at around 11%.

A long bar always means good, which for a pitcher means several rates are
inverted: allowing few home runs per fly ball is the achievement, not allowing
many. Inversion is marked in the name with `↓`, so nothing is quietly reversed
behind the reader's back.

Two of these have no good end at all. Pull rate describes an approach rather
than ranking it, and air rate is a style before it is a skill. They are ranked
in the direction that conventionally flatters — pulling and lifting for a
hitter, the reverse for a pitcher — and the rate itself is printed beside the
bar precisely so a reader who disagrees with that framing can ignore it and
read the number.

### Power, as three rates

Isolated power answers how much damage a hitter did, which the slash line beside
it already carries. These answer how he did it:

| Rate | Numerator | Denominator |
|------|-----------|-------------|
| HR/FB | home runs (season feed) | fly balls (play-by-play) |
| Air | batted balls not on the ground | batted balls |
| Pull | batted balls to the pull side | batted balls with a landing spot |

Air and pull describe the approach, HR/FB whether it is backed by damage, and a
hitter can be loud in one and quiet in another. Keeping them apart is the point:
a hitter who lifts and pulls constantly without clearing fences is a different
player from one who does neither and still runs a high HR/FB, and a single power
grade would report them as the same.

HR/FB is the one rate here built from two sources, so it is only honest where a
level's play-by-play has been gathered in full — a season gathered partway
through would divide a full season's home runs by a partial count of fly balls
and overstate every hitter at that level. Coverage is checked before it is
trusted; at the time of writing all four full-season levels are complete for
2026.

The counts are also matched to the **stint** they were earned in rather than
pooled across the season. A player promoted in July has one row per level, each
carrying that level's home run total, so pooling his batted balls would divide
one level's damage by two levels' chances at it. This showed up plainly: a
Triple-A hitter slugging .550 was ranking 46th in HR/FB because his Double-A fly
balls were padding the denominator, and he moved to 93rd once the two were
separated. Ratios of two play-by-play counts, such as air and pull, survived the
pooling unharmed, since both halves were inflated equally.

### Where ground balls and spray come from

Batted-ball tendencies are reported as bars alongside the other skills rather
than on a line of their own, and each appears once: a hitter's ground-ball rate
is exactly one minus the air rate beside it, so showing both would be the same
number told twice and backwards.

Ground-ball rate is taken from play-by-play even though `seasonAdvanced` carries
its own ground-ball counts, hits included, which sum exactly to `ballsInPlay`
for 1,484 of 1,504 hitters checked. The reason is consistency rather than
correctness: the ground-ball park factor these rates are divided by is built
from play-by-play trajectories, and a rate measured one way cannot be adjusted
by a factor measured another.

Pull rate has no season-stat equivalent at any level. Spray direction is
computed from the batted ball's landing coordinates as an angle off home plate,
with the middle 30 degrees counted as centre and the rest split by the batter's
handedness — the same ball down the left-field line is pulled by a right-hander
and served the other way by a left-hander. The coordinate frame was checked
against the fielder credited with each ball: third base averages −29 degrees,
centre field +2, first base +41, which is the field in order. Roughly 100% of
batted balls carry a usable location.

Percentiles appear only once a player clears the sample floor in
`config/settings.json` (50 plate appearances or batters faced). Below that a
percentile is noise presented as insight, so no skill line is produced at all.

### Park adjustment, and the trap in it

Skills are park-adjusted, each against the component it belongs to — contact and
whiffs against the whiff factor, HR/FB against home runs, discipline and command
against walks, ground balls and pull against their own factors. Air is adjusted
against the ground-ball factor, since it is one minus that rate. Contact and air
are both inverted first, because a park that inflates whiffs deflates contact
and one that inflates grounders deflates the air rate.

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

### Why bat-to-ball skill is adjusted by whiffs, not strikeouts

A strikeout is two different park effects wearing one number, and across parks
they are **unrelated to each other**: the whiff factor and the called-strike
factor correlate +0.04. Spread across Double-A parks in 2025:

| factor | spread (max − min) |
|---|---|
| strikeout | 0.163 |
| whiff | 0.113 |
| called strike | 0.057 |

Adjusting a contact rate by the strikeout factor therefore over-corrects by
roughly 44%, importing zone variation into a bat-to-ball measure. Amarillo is
the clearest case: it suppresses strikeouts 6.7% while being neutral on whiffs
(0.991), so a strikeout-based adjustment would credit a hitter there for
beating a park that never challenged his contact.

So contact and whiff percentiles are adjusted by the whiff factor. Every rate is
adjusted by the park's measured effect on that same rate rather than on a proxy
for it.

That principle also decided what *not* to do with the called-strike factor.
Adjusting walk rates by it is tempting, since a generous zone should mean fewer
walks, and the correlation does run in that direction — but weakly and
inconsistently: −0.08 in Triple-A, −0.37 in High-A, −0.33 in Single-A. The walk
factor measures the park's effect on walks directly, so substituting a weak
correlate for it would trade signal for noise. The called-strike factor is
computed and stored, because it is what explains the gap between strikeouts and
whiffs, but it adjusts nothing on its own.

Pitchers are ranked on their actual whiff rate rather than strikeout rate for
the same reason. Both are available per player from `seasonAdvanced`, and they
correlate +0.78 — close, but not the same skill.

### What altitude does, and does not, explain

Altitude is the obvious candidate for a physical explanation of the strikeout
factor, and it does correlate with it at −0.58. But the effect runs almost
entirely through called strikes, at −0.57, and barely through swings and misses
at −0.31. Amarillo, the highest park in Double-A, is neutral on whiffs.

The tidy story — thinner air flattens breaking balls, so hitters miss less —
therefore does not survive the split. Umpire zone behaviour and hitter approach
in a park that rewards contact are both plausible alternatives, and neither is
tested here.

This does not weaken the case for adjusting whiff rate, which varies across
parks by 11% whatever the cause. It is a reason to trust the measured factor
over the mechanism it seems to imply.

## Age relative to level

Reported next to the numbers and deliberately never inside them. A 20-year-old
posting a league-average line in Double-A is the signal; folding age into wRC+
would hide it. League average age is computed from the same qualified pool.

Written as three quantities rather than a sentence — `AA Arkansas, 20yo, TEX -4`
— which reads as where he is, how old he is, and how that age sits against the
league. Negative is young for the level, the direction that flatters a prospect.
A player whose season is blended across two leagues has both named here, so
`SOU/TEX` is the signal that the ranks beneath it are a mixture.

## Levels and stints

A player who changes level mid-season gets one leaderboard row per stint. The
level of his most recent game decides which is current, because someone
promoted in August may still have most of his season's plate appearances below.
Every level he has left is reported underneath, largest sample first: the stint
behind him is often the better evidence, and the change is usually the most
interesting thing about the line.

Stints are named by club as well as level, because the level alone stops
identifying one as soon as a player is traded without moving up.

### A trade within a level

This is the awkward case. A player traded from one Double-A club to another has
his line pooled by the leaderboards into a single row credited to whichever
club he finished with, and the two halves cannot be separated: the play-by-play
counts behind the skill bars are gathered per level, not per club.

So the line is left whole and the yardstick is blended instead. His parks are
averaged by how much of the season each accounts for, geometrically, since
these are multipliers. His leagues are averaged the same way: the constants
behind wRC+ and FIP- are averaged directly, and his percentile is computed in
each league he played in and those ranks averaged. That last part is the
faithful reading — it says he was in the sixtieth percentile of one league for
half a season and the seventieth of the other for the rest, which is what
happened.

Both leagues are named where the league normally is, so a header reading
`SOU/TEX` is the signal that the comparison beneath it is a mixture. Boston
Smith in 2026 is the worked example: 97 plate appearances at Birmingham in the
Southern League and 89 at Arkansas in the Texas League, worth 197 wRC+ measured
against one, 202 against the other, and 200 blended.

The splits are fetched per player, so only players known to have changed
organization this season are asked about — one request each, and none at all in
the ordinary year.

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

### Components, and where each comes from

Six come from game logs, which every season has: runs, strikeouts, walks, home
runs, hits in play, extra-base hits.

Four more — **whiffs**, **called strikes**, **ground balls** and **pull** — need
pitch-level detail, which only play-by-play carries. That means one request per
game, so they are gathered separately, cached per game and resumable. A season
is roughly 8,000 games across the four full-season levels, about 20 minutes of
fetching. Seasons without a play-by-play pass simply lack those components, and
the blend treats them as neutral.

Each of the four is regressed against its own denominator rather than a shared
game count — swings, taken pitches, batted balls and located batted balls
respectively. A park sees an order of magnitude fewer batted balls than pitches,
and treating the two as equally well measured would leave the spray and
trajectory factors noisier than they appear.

The same play-by-play pass also produces per-player batted-ball totals, which is
where the air, pull and ground-ball rates in the skills section come from, along
with the fly balls under HR/FB. Unlike the
park factors, that half is needed for the **current** season, so the season in
progress is topped up incrementally: `gather` skips games already cached, which
during the season is a few hundred new games a day rather than a full backfill.

None of this touches the daily digest, which only reads the committed factors.

The digest does make one small play-by-play request per outing, to put a whiff
count beside the strikeouts on a pitching line. It is bounded by how many
tracked pitchers threw yesterday — a handful of games, not a season — and a game
that cannot be read simply reports strikeouts alone. Strikeouts describe how an
outing ended, which depends on the hitters and the umpire; whiffs describe how
the stuff played. They come apart often enough to be worth both: in one Double-A
game checked while building this, a reliever recorded a strikeout on zero
whiffs, and another drew eleven whiffs for eight strikeouts.

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

The rookie and complex leagues have no park factors. A shared back-field is not
really a park, and the schedules are too short to measure one.

Why altitude moves called strikes is unexplained, and worth understanding
before leaning on the called-strike factor too heavily.

The 5-3-1 season weights and the 4,000 PA regression constant are conventions
rather than fitted results, as are the sample floors, the notability
thresholds, and the linear weights behind wRC+. All of them are collected in
[CONVENTIONS.md](CONVENTIONS.md), with what it would take to learn each one
instead.
