# PA Generative Simulator

## Status

- Candidate package: `2.6.0.dev1+pa.generative.integration`
- Target branch: `v2.6-pa-generative-integration`
- Simulator identity: `pa-generative-shadow-rc1`
- Production authority: **none**
- Default moneyline influence: **20% in PA shadow only**

V2.3.3 remains the production winner model, V2.4 RC2 remains a separate shadow track, and the incumbent Poisson score engine remains authoritative until explicit promotion.

## Motivation

The incumbent score path predicts expected runs first and then samples scores around those expectations. That architecture can estimate ordinary mean scoring reasonably well, but historical testing showed that it compresses important baseball tails such as shutouts, blowouts, and very high-scoring games.

The PA candidate reverses that dependency:

```text
pregame point-in-time data
        ↓
plate-appearance event probabilities
        ↓
complete simulated baseball games
        ↓
final score distributions
        ↓
win probability / projected score / totals / run lines / team totals
```

The projected score is therefore a downstream summary of simulated games rather than an input that anchors those games.

## Game state

Each simulated game tracks:

- inning and half-inning
- outs
- occupied bases
- batting-order position
- current starter/bullpen phase
- starter workload
- score
- extra innings and automatic runner
- walk-off termination

PA outcomes use the event order:

`K`, `BB`, `HBP`, `1B`, `2B`, `3B`, `HR`, `REACH`, `OUT`

The packaged empirical prior was reproducibly built from **182,449 effective 2024 regular-season PA transitions** and contains all **216** `(outs, base_state, event)` transition states.

## Live fail-closed requirements

PA RC1 requires:

- official MLB `gamePk`
- confirmed starting pitchers
- confirmed nine-player batting orders
- immutable pregame snapshot
- immutable starter season profiles
- sufficient individual hitter coverage

The live adapter prefers active-roster reliever-only season pitching profiles. A team all-staff profile can be used only as an explicitly labeled partial-parity fallback.

Recent bullpen workload, fatigue, and closer availability are captured and exposed for diagnostics, but RC1 does **not** modify PA event probabilities from those fields because a point-in-time historical ablation has not yet validated an effect size.

## Historical evidence

The canonical reproduction developed the PA model on 2024 data and evaluated it on a locked **1,972-game 2025 holdout**.

| Engine | Accuracy | Brier | Log loss | Team-run MAE | Total MAE | Run-diff MAE |
|---|---:|---:|---:|---:|---:|---:|
| Frozen Poisson | 54.06% | 0.247568 | 0.688263 | 2.5112 | **3.6095** | 3.5335 |
| Inning | 53.70% | 0.251952 | 0.698752 | 2.5485 | 3.6875 | 3.5434 |
| **PA** | **54.46%** | **0.245055** | **0.683124** | **2.5104** | 3.6097 | **3.5327** |

PA's advantage over inning on Brier/log loss was statistically supported. PA's point estimates also beat the stronger Poisson benchmark, but the paired confidence intervals narrowly crossed zero. The most decisive improvement was full score-distribution realism.

Ten-bin expected calibration error:

- PA: **0.00982**
- Poisson: 0.04504
- Inning: 0.08688

Absolute historical frequency error (percentage points):

| Outcome | PA | Poisson |
|---|---:|---:|
| Shutouts | **0.57** | 4.55 |
| Team 10+ runs | **2.25** | 5.03 |
| Game 15+ total | **1.83** | 4.65 |
| 5+ run blowouts | **4.86** | 15.62 |
| One-run games | **0.42** | 4.11 |

See `docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md` for the full methodology and bootstrap results.

## Moneyline integration

The seven-model ensemble is not replaced by PA simulation. Historical weight tests found promising high-PA blends, but improvements over the incumbent 20% Poisson blend were not statistically decisive on the locked holdout.

Therefore RC1 defaults to a conservative configurable **20% PA influence in shadow only**. No 70–80% production-weight claim is made.

## Conflict policy

Production retains its existing score-conflict behavior. PA shadow does not apply the fixed 0.20-run projected-score veto because historical ablation found that it removed coverage without improving accuracy. PA/ensemble score disagreement is still persisted and displayed as a diagnostic.

## Running the PA shadow track

```bash
sports-supermodel \
  --date YYYY-MM-DD \
  --interactive \
  --simulations 100000 \
  --pa-shadow \
  --pa-shadow-simulations 100000 \
  --pa-shadow-weight 0.20
```

The PA track writes separate artifacts and persists `production_authority=false` in candidate metadata.

## Promotion gates

PA can replace the incumbent score-distribution engine only after:

1. fresh network-backed pregame capture verifies confirmed lineup/starter/reliever ingestion;
2. full-slate 100,000-simulation shadow execution verifies runtime and persistence;
3. prospective settlements confirm operational integrity;
4. the repository CI matrix passes;
5. any direct bullpen-availability adjustment earns its own historical validation;
6. promotion is explicitly approved.

Historical validation supports continuing implementation. It does **not** authorize an automatic production promotion.
