# Sports SuperModel — Canonical Generative Simulator Reproduction

**Date:** 2026-08-16  
**Purpose:** Recompute the generative-simulator evaluation from verifiable uploaded artifacts rather than relying on earlier conversational claims.  
**Production authority:** None. The production/local slate baseline remains V2.3.3 production + V2.4 RC2 shadow + incumbent Poisson score/simulation architecture until an implementation candidate is built, validated for live parity, tested, and explicitly promoted.

## 1. Reproducibility / source audit

### Runtime baseline
- Package found in uploaded runtime: `2.5.0.dev3+public.readiness.foundation`
- Runtime archive SHA-256: `0e99429fee7ade85718ee000cbfd8668f6f52fb797391bd39714dd855ad8d97c`
- The upload excludes `.git`, so the handoff's stated rollback commit cannot be independently verified with `git rev-parse` from this archive.
- Existing inning simulator is present in the runtime.
- No PA simulator implementation was present in the uploaded baseline; the PA evaluation code was built in a separate evaluation workspace and was not written into the baseline repository.
- Repository regression suite previously run against this uploaded baseline: **200 passed**.

### Uploaded Retrosheet inputs
| File | SHA-256 |
|---|---|
| `2024plays.zip` | `a3e8c08876ddf70e1ffb0b20486c2873cf4aae19e0acc8002096e9056107615b` |
| `2025plays.zip` | `ea7f4be3464825b332ed6f8c19e15310858458ea9eddf3e91a954e5b47f69d73` |
| `gl2024.zip` | `3089e0a895e70a6fd244d31fe822bc4d856d0987458e86b5acc5df1aa297d250` |
| `gl2025.zip` | `f8a36120bc5f6925ffc914f964167f745e61a3421be9318e2ee24a576392693a` |

Parsed source audit:
- 2024: **189,536** regular-season play rows, **2,429** games; **182,449** effective PA transitions.
- 2025: **189,939** regular-season play rows, **2,430** games; **182,926** effective PA transitions.
- Evaluation begins May 1 so March-April data provide pregame warmup state.
- 2024 development/evaluation games: **1,977**.
- 2025 locked out-of-year holdout games: **1,972**.

The effective PA-transition counts reproduce the earlier report's 182,449 / 182,926 figures. The raw play-row counts in the earlier report do **not** match the current official uploaded archives, so this reproduction uses the actual uploaded archive contents.

## 2. Leakage controls

The canonical evaluator reconstructs point-in-time state chronologically:
- captures every game's pregame snapshot before updating with that date's results;
- applies all same-date events only after all games for that date have been captured;
- uses actual historical starting lineups and starting pitchers from the play records;
- uses official game-log scores as outcome truth;
- uses prior batter, pitcher, bullpen and league event histories;
- uses prior starter workload histories;
- builds base/out transition distributions from historical plays strictly before the allowed cutoff;
- uses fixed seeds for reproducibility.

For 2025, PA transition mechanics are frozen from 2024 rather than learned from 2025 outcomes. PA player/pitcher event histories update chronologically as 2025 proceeds, which is information that would have been known before each target game.

## 3. PA simulator architecture

The PA simulator generates complete games plate appearance by plate appearance using empirical event categories:

`K`, `BB`, `HBP`, `1B`, `2B`, `3B`, `HR`, `REACH`, `OUT`

It maintains:
- inning / half-inning;
- outs;
- base state;
- batting order;
- starter versus bullpen state;
- starter workload;
- score;
- extra-inning automatic-runner state;
- walk-off termination.

Projected score, win probability, run-line/totals distributions and tail statistics are downstream outputs of simulated complete games. They are not upstream score anchors.

### Frozen PA parameters
Selected using 2024 only:
- batter empirical-prior strength: **60 PA**
- pitcher empirical-prior strength: **90 PA**
- bullpen empirical-prior strength: **240 PA**
- batter relative-rate exponent: **0.5**
- pitcher relative-rate exponent: **0.5**
- home non-out event multiplier: **1.04**
- global event multiplier: **1.00**

No 2025 outcome was used to select these parameters.

## 4. Benchmark design

The locked 2025 holdout compares three score/simulation architectures at **5,000 simulations per game** over all 1,972 games:

1. **Frozen Poisson regression benchmark** — Poisson run models trained on 2024 point-in-time features only, then frozen for 2025; score draws use the incumbent-style correlated scoring environment.
2. **Inning generative candidate** — inning scoring generated from point-in-time starter/bullpen/offense state.
3. **PA generative candidate** — complete PA-by-PA game simulation.

A separate 40-game sample was rerun at **100,000 complete PA simulations/game** to quantify Monte Carlo convergence.

## 5. Locked 2025 architecture results

| Engine | Winner acc. | Brier | Log loss | AUC | Team-run MAE | Total MAE | Run-diff MAE | Exact-score NLL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Frozen Poisson | 54.06% | 0.247568 | 0.688263 | 0.565856 | 2.5112 | **3.6095** | 3.5335 | 5.1637 |
| Inning | 53.70% | 0.251952 | 0.698752 | **0.572784** | 2.5485 | 3.6875 | 3.5434 | 5.0550 |
| **PA** | **54.46%** | **0.245055** | **0.683124** | 0.568484 | **2.5104** | 3.6097 | **3.5327** | **4.8337** |

Interpretation:
- PA is clearly superior to the inning candidate on proper scoring and score-distribution metrics.
- PA is directionally better than the stronger frozen Poisson benchmark on winner accuracy, Brier, log loss, team-run MAE, run-differential MAE and exact-score likelihood.
- PA and Poisson are essentially tied on total MAE.
- PA's exact-score NLL is about **6.4% lower** than Poisson's.

## 6. Paired bootstrap — locked 2025 holdout

20,000 paired bootstrap resamples were used.

### PA vs frozen Poisson
- Brier difference: **-0.002503**; 95% CI **[-0.005684, +0.000617]**.
- Log-loss difference: **-0.005119**; 95% CI **[-0.011714, +0.001353]**.
- Accuracy difference: **+0.406 percentage points**; 95% CI **[-2.028, +2.890] pp**.

**Conclusion:** PA is directionally better, but this single locked out-of-year holdout does **not** establish statistically significant superiority over the stronger Poisson regression benchmark on moneyline probability quality.

### PA vs inning
- Brier difference: **-0.006899**; 95% CI **[-0.011838, -0.001969]**.
- Log-loss difference: **-0.015633**; 95% CI **[-0.026860, -0.004622]**.
- Accuracy difference: **+0.757 pp**; accuracy CI crosses zero.

**Conclusion:** PA's proper-scoring advantage over inning is statistically supported.

### Inning vs frozen Poisson
- Brier difference: **+0.004399**; 95% CI **[+0.000764, +0.008091]**.
- Log-loss difference: **+0.010524**; 95% CI **[+0.002326, +0.018771]**.

**Conclusion:** the current inning candidate is worse than the stronger Poisson benchmark on probability quality and should not advance.

## 7. Calibration and score-distribution realism

### Expected calibration error (10 bins)
- **PA: 0.00982**
- Poisson: 0.04504
- Inning: 0.08688

### Mean total runs
- Actual: **8.943**
- PA: **8.775**
- Poisson: **8.830**
- Inning: **9.239**

### Tail-frequency absolute errors, percentage points
| Outcome | PA | Poisson | Inning |
|---|---:|---:|---:|
| Team shutout | **0.57** | 4.55 | 4.53 |
| Team 10+ runs | **2.25** | 5.03 | 4.10 |
| Game 15+ total | **1.83** | 4.65 | 2.53 |
| 5+ run blowout | **4.86** | 15.62 | 13.31 |
| One-run game | **0.42** | 4.11 | 4.47 |

This is the strongest evidence for the redesign. The PA simulator is far closer to actual MLB distribution tails while not sacrificing mean run-error performance.

### Extra innings
- Actual: **8.57%**
- PA: **10.11%**
- Inning: **12.90%**
- Final-score Poisson benchmark does not explicitly model extra innings.

PA is not perfect, but it is materially closer than the inning candidate and has an explicit baseball-game mechanism for extras.

## 8. Monte Carlo convergence

40 evenly spaced 2025 holdout games were compared at 5,000 versus 100,000 complete PA simulations/game:
- mean absolute win-probability difference: **0.486 pp**
- max difference: **1.420 pp**
- mean absolute team-score-mean difference: **0.0338 runs**
- max difference: **0.106 runs**

This independently reproduces the earlier report's basic convergence claim closely enough to justify the 5,000/game full architecture screen. Running all 1,972 holdout games at 100,000 would greatly increase compute while being unlikely to change the statistical conclusion, which is dominated by game-sample uncertainty rather than Monte Carlo noise.

## 9. Seven-model ensemble integration

The actual repository `V2Ensemble` architecture was used to reconstruct out-of-year historical seven-model probabilities rather than replacing it with a homemade proxy.

### Frozen 2025 seven-model reconstruction
- Accuracy: **54.51%**
- Brier: **0.245747**
- Log loss: **0.684580**
- AUC: **0.576014**

Canonical fitted model weights:
- Logistic: 0.13665
- Random Forest: 0.14866
- Neural Network: 0.15137
- Elo/Pyth: 0.13338
- XGBoost: 0.14317
- LightGBM: 0.14099
- CatBoost: 0.14579
- V1 anchor weight: 0.25

### Weight selection without 2025 tuning
2024 monthly out-of-fold seven-model predictions were blended with 2024 PA probabilities over 0-100% PA weight in 5-point increments.

2024 development proper-scoring optimum: **80% PA / 20% seven-model**.
- Brier: 0.245091
- Log loss: 0.683263
- Accuracy: 55.49%

This was frozen before examining its 2025 holdout result.

### 2025 locked results for selected blends
| System | Brier | Log loss | Accuracy | ECE |
|---|---:|---:|---:|---:|
| Seven-model only | 0.245747 | 0.684580 | 54.51% | 0.01210 |
| 20% PA | 0.245306 | 0.683684 | 54.31% | **0.00984** |
| **80% PA (2024-frozen)** | **0.244891** | **0.682804** | **55.02%** | 0.01443 |
| Current-style 20% Poisson | 0.245325 | 0.683698 | **55.02%** | 0.01356 |
| Raw PA | 0.245055 | 0.683124 | 54.41% | 0.01033 |

The post-hoc 2025 Brier minimum is around 70% PA, but **that is not a valid promotion weight because it was observed on the holdout**. The preregistered/frozen development choice is 80%.

### Bootstrap of PA blend versus incumbents
**80% PA vs seven-model alone**
- Brier: -0.000856; 95% CI [-0.002372, +0.000640]
- Log loss: -0.001776; 95% CI [-0.004810, +0.001344]
- Accuracy: +0.507 pp; CI crosses zero

**80% PA vs current-style 20% Poisson blend**
- Brier: -0.000434; 95% CI [-0.001922, +0.001087]
- Log loss: -0.000894; 95% CI [-0.003895, +0.002098]
- Accuracy: 0.000 pp; CI crosses zero

**20% PA vs 20% Poisson**
- Brier: -0.000019; 95% CI [-0.000646, +0.000613]
- Log loss: -0.000014; 95% CI [-0.001317, +0.001255]
- Accuracy: -0.710 pp; CI [-2.028, +0.609] pp

**Conclusion:** the PA simulator is a better score-generation architecture, but the historical evidence does **not** prove a particular PA moneyline blend is superior to the incumbent Poisson blend. The 70-80% region has favorable point estimates but should not be declared the production-optimal weight.

## 10. Conflict-veto ablation

Using the existing basic gate concept (final-side probability >=53%, component support >=4/7):

### 20% PA blend
- No score veto: 806 picks; 40.87% coverage; **59.80% accuracy**.
- 0.20-run score veto: 796 picks; 40.37% coverage; **59.80% accuracy**.
- The veto rejected 10 bets that were themselves **60.0% correct**.

### 80% PA blend
- No score veto: 903 picks; 45.79% coverage; **57.92% accuracy**.
- 0.20 / 0.50 / 1.00-run projected-score vetoes rejected **zero** additional games.

**Conclusion:** the fixed projected-score hard veto has no demonstrated value once PA probability is already part of the blend. Simulator/ensemble disagreement should remain visible as a diagnostic, but the old fixed 0.20-run rule should not be duplicated as an automatic PASS in a PA-based design unless future evidence shows value.

The 80% PA blend also increases coverage while lowering gated accuracy relative to the conservative 20% PA blend. That is a second reason not to choose 80% merely because it minimizes aggregate Brier score.

## 11. Comparison with the earlier historical report

The independent rerun **reproduces the broad architecture story but not every strength-of-evidence claim**.

Reproduced:
- revised PA is materially better than the earlier/inning approach;
- PA produces dramatically more realistic score tails than Poisson;
- PA has excellent calibration;
- PA convergence at 100k is stable relative to the lower-count screen;
- 20% PA and 20% Poisson blends are essentially tied;
- the fixed projected-score veto adds no demonstrated value.

Not reproduced at the same confidence level:
- the old report described PA as decisively superior to current Poisson on Brier/log loss. Against this reproduction's stronger, leakage-safe frozen Poisson regression benchmark, PA's point estimates are better but the 95% paired-bootstrap intervals narrowly cross zero.
- the old report's raw play-row counts differ from the uploaded official archives, although its effective PA-transition counts match exactly.

This distinction is important: the new evidence supports the PA score engine, but it does not justify overstating certainty about moneyline blending.

## 12. Canonical decision

### Architecture decision: **PROMOTE PA TO IMPLEMENTATION CANDIDATE**
The PA simulator has earned advancement as the preferred **score-generation / derivative-market simulation architecture** because:
1. it significantly beats the inning candidate on Brier and log loss;
2. it is directionally better than the frozen Poisson benchmark on probability quality;
3. it is essentially tied with Poisson on mean score error;
4. it is dramatically better on score-distribution tails and exact-score likelihood;
5. it makes projected score correctly downstream of complete simulated games;
6. its lower-count historical screen is validated by 100k convergence testing.

### Inning candidate: **REJECT**
The current inning candidate is significantly worse than the frozen Poisson benchmark on Brier and log loss and materially worse than PA.

### Moneyline integration: **INCONCLUSIVE / KEEP AUTHORITY CONSERVATIVE**
Do **not** promote 70%, 80%, 20%, or any other PA moneyline weight as proven optimal.
- 80% PA was the 2024 development optimum and held up directionally in 2025, but it was not significantly better than the incumbent 20% Poisson blend.
- 20% PA is nearly indistinguishable from 20% Poisson on proper scoring and has a worse raw-accuracy point estimate.
- A PA implementation candidate should therefore separate the strong score/derivative architecture decision from the unresolved moneyline-authority decision.

### Fixed projected-score hard veto: **REJECT FOR PA DESIGN**
Retain simulator disagreement as a visible diagnostic; do not automatically PASS solely because PA projected-score direction disagrees by a fixed 0.20 runs.

### Production decision: **NO PRODUCTION CHANGE YET**
The repository/local rollback remains in force. The next stage is to build the cumulative implementation candidate, verify live-data parity and regression tests, then run PA in shadow/diagnostic authority before any explicit production promotion.

## 13. What should be in the eventual cumulative patch

Only after implementation work is authorized, the cumulative candidate should:
1. add the PA complete-game simulator;
2. preserve all seven canonical winner models;
3. make projected score downstream of 100,000 complete PA games;
4. derive totals, run lines, team totals and tail diagnostics from the PA distribution;
5. keep PA moneyline authority configurable/conservative rather than hard-coding 70-80% as truth;
6. remove the fixed 0.20-run score hard veto from automatic PA-based abstention while retaining diagnostic disagreement;
7. preserve provenance / point-in-time validation tooling and reproducibility tests;
8. preserve the rollback marker/public-readiness foundation;
9. include any legitimate Python 3.12 GitHub Actions repair **only after the actual failed workflow log is inspected**.

## 14. Remaining evidence / operational gates

The core historical architecture test is complete enough to choose the implementation candidate. Remaining gates are different from architecture selection:
- live feature/data parity between retrospective PA inputs and the live publishing pipeline;
- regression/performance tests in the cumulative candidate;
- prospective shadow sanity check after implementation;
- decision on conservative moneyline authority / blend weight;
- unresolved GitHub Actions Python 3.12 log diagnosis.

A third historical season could narrow the PA-vs-Poisson moneyline confidence interval, but it is **not necessary to establish that PA is the superior score-distribution architecture**. It would be useful only if the goal is to make a stronger statistical claim about PA's incremental moneyline-probability value.
