# V2 validation and retrospective replay

## Decision

**Keep V1 as production and keep V2 on `v2-development`; do not merge yet.**

V2 improves probability calibration but does not demonstrate a statistically clear gain in binary winner accuracy, and its aggregate AUC is lower. The branch therefore fails the current merge gate even though the July 17–19 replay is encouraging.

## What was actually tested

- 1,477 reconstructed 2026 games from public team game logs.
- Leakage-controlled features: every game is predicted using only information available before its date.
- Five expanding walk-forward validation windows totaling **1,109 unseen games**.
- Seven fitted components: logistic regression, random forest, neural network, XGBoost, LightGBM, CatBoost and Elo/Pythagorean.
- Chronological calibration and a V1 prior anchor selected only on each fold's pre-validation calibration slice.
- 100,000 Monte Carlo trials for each unambiguous July 17–19 replay game.

## Walk-forward results

| Metric | V1-style validation baseline | V2 | V2 change |
|---|---:|---:|---:|
| Accuracy | 54.28% | 54.46% | +0.18 pp |
| Brier score | 0.25595 | 0.24953 | -0.00642 |
| Log loss | 0.70803 | 0.69243 | -0.01561 |
| ROC AUC | 0.56007 | 0.55075 | -0.00932 |

Paired bootstrap results:

- Accuracy difference 95% CI: **-1.35 to 1.62 percentage points**.
- Brier difference 95% CI: **-0.01151 to -0.00140**; negative favors V2.
- Log-loss difference 95% CI: **-0.02688 to -0.00436**; negative favors V2.
- McNemar exact p-value for winner accuracy: **0.905**.

Interpretation: V2's probabilities are meaningfully less overconfident, but the winner-pick gain is too small to distinguish from noise.

## July 17–19 V2 replay

The replay excludes every affected **doubleheader matchup**, not merely Game 2, because the downloaded team logs do not preserve a game identifier and cannot reliably distinguish the games.

| Date | Correct | Replayed games | Accuracy |
|---|---:|---:|---:|
| 2026-07-17 | 8 | 12 | 66.67% |
| 2026-07-18 | 5 | 13 | 38.46% |
| 2026-07-19 | 12 | 14 | 85.71% |
| **Total** | **25** | **39** | **64.10%** |

## Direct comparison with the recorded V1 chat picks

Only games with both a valid recorded V1 pick and an unambiguous V2 replay are included.

- V1: **17/35 (48.57%)**
- V2: **24/35 (68.57%)**
- Picks changed: **13**
- Changed picks improved the result: **10**
- Changed picks worsened the result: **3**

This comparison is retrospective, small, and concentrated in three days. It is useful as a regression check, not proof of a durable betting edge.

## Data and implementation limits

The complete V2 feature contract includes advanced pitcher quality, pitch trends, lineup quality and platoons, injury WAR, bullpen availability, umpire effects, weather and air density, park factors, travel, fielding, catching, baserunning and market movement. Those interfaces and missingness flags are implemented.

However, the replay data set contains only team game results, starter names and limited run information. The advanced point-in-time features were therefore neutral in this test. They must be populated from timestamped pregame snapshots before their incremental value can honestly be measured. No historical values were backfilled using information that would not have been available at prediction time.

## Next merge test

V2 should be reevaluated after accumulating at least 500 timestamped predictions with:

- official `gamePk` schedule locking,
- confirmed pregame lineups and injuries,
- Statcast/pitcher and bullpen snapshots,
- opening/current/closing prices,
- closing-line value and calibration tracking.
