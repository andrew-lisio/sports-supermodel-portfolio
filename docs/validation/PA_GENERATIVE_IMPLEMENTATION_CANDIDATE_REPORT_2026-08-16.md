# Sports SuperModel — PA Generative Implementation Candidate

> **2026-08-18 CI addendum:** The previously missing GitHub Actions log was subsequently supplied and diagnosed. Python 3.12 installation/compilation succeeded; the failed job stopped at the Ruff lint gate. The cumulative V2.6 bundle now includes the corresponding correctness/lint repair. See `docs/CI_RUFF_REPAIR_2026-08-18.md`. Statements below about the log still being unavailable describe the original Aug. 16 candidate state.


**Candidate package at initial implementation:** `2.5.0.dev4+pa.shadow.candidate`
**Package:** `2.6.0.dev1+pa.generative.integration`
**Simulator version:** `pa-generative-shadow-rc1`  
**Created from rollback package:** `2.5.0.dev3+public.readiness.foundation`  
**Production authority:** **NONE**  
**Default PA moneyline influence:** `0.20` (configurable, shadow only)  

## Governance

This candidate does not promote or replace V2.3.3 production, V2.4 RC2 shadow, or the incumbent Poisson production simulation path. It adds a third `pa_shadow` track for prospective operational testing. The repository archive used for development does not include `.git`, so the stated rollback commit cannot be independently resolved from this workspace.

## Historical evidence carried into implementation

The canonical point-in-time reproduction on the uploaded Retrosheet 2024/2025 corpus selected PA simulation over the inning candidate for score-distribution architecture. On the locked 1,972-game 2025 holdout (5,000 simulations/game):

| Engine | Accuracy | Brier | Log loss | Team-run MAE | Total MAE | Run-diff MAE |
|---|---:|---:|---:|---:|---:|---:|
| Frozen Poisson | 54.06% | 0.247568 | 0.688263 | 2.5112 | 3.6095 | 3.5335 |
| Inning | 53.70% | 0.251952 | 0.698752 | 2.5485 | 3.6875 | 3.5434 |
| PA | 54.46% | 0.245055 | 0.683124 | 2.5104 | 3.6097 | 3.5327 |

PA's probability-quality advantage over the strong Poisson benchmark was directionally favorable but not statistically decisive; PA's advantage over inning was statistically supported. PA materially improved historical score-tail realism. Therefore the candidate uses a conservative `20%` PA moneyline weight rather than claiming that the 70–80% historical weight region is proven optimal.

## Implemented candidate architecture

### PA game simulator

`src/supermodel/pa_simulator.py`

- Simulates complete games plate appearance by plate appearance.
- Does **not** accept a projected score or expected-runs target.
- Projected scores, win probability, totals, run lines, team totals, shutouts, blowouts, one-run games, and extra-inning rates are downstream outputs.
- Maintains inning/half, outs, base state, batting-order position, current pitcher phase, score, starter workload, extra innings, automatic runner, and walk-off termination.
- Uses fixed seeds for reproducibility.
- Uses empirical 2024 base/out transition distributions from the uploaded official historical corpus.
- `pa_prior_builder.py` reproducibly rebuilds the packaged prior from the uploaded Retrosheet ZIP; the regenerated payload matches the packaged JSON exactly.

### Historical PA prior artifact

`src/supermodel/resources/pa_priors_2024.json` and `src/supermodel/pa_prior_builder.py`

- Built from 182,449 effective 2024 regular-season PA transitions.
- Event order: `K, BB, HBP, 1B, 2B, 3B, HR, REACH, OUT`.
- Contains all 216 `(outs, base_mask, event)` transition states.
- Packaged into the wheel as package data.

### Live point-in-time adapter

`src/supermodel/pa_live.py`

Fail-closed requirements:

- official `game_pk`;
- confirmed starters;
- confirmed nine-player batting orders;
- immutable advanced pregame snapshot;
- immutable raw starter season snapshots;
- sufficient individual hitter coverage.

The adapter prefers active-roster **reliever-only** season pitching profiles for bullpen event rates. A team all-staff pitching profile remains an explicit partial-parity fallback.

Recent bullpen fatigue/closer-availability fields are captured by the live context pipeline but are **diagnostic only** in RC1. No fatigue event-rate adjustment is applied because the canonical historical PA experiment did not validate one. RC1 therefore explicitly records `BULLPEN_AVAILABILITY_DIAGNOSTIC_ONLY` rather than pretending full live parity.

### Live MLB capture additions

`src/supermodel/live_mlb.py`

- Batch current-season pitcher-stat collection for active roster pitchers.
- Active pitcher identification from official roster payloads.
- Reliever classification from season games/starts.
- Immutable raw-source persistence for active rosters and reliever-only season profiles.
- Existing recent bullpen usage, fatigue, and closer-availability capture remains intact.
- No new PA input is allowed to alter V2.3.3 or V2.4 RC2 production/shadow probabilities.

### Selection-policy behavior

`src/supermodel/selection_policy.py`

- Existing production score-conflict veto remains enabled by default.
- PA shadow disables the fixed projected-score veto because the historical ablation found that it removed coverage without improving accuracy.
- PA score disagreement remains visible as an auditable diagnostic.

### Workflow integration

`src/supermodel/workflow.py`

- Optional third model track: `pa_shadow`.
- Distinct PA CSV/JSON artifacts.
- Distinct simulation snapshots and manifests.
- `production_authority=false` is persisted in candidate metadata.
- PA simulation draws are persisted separately from production and V2.4 RC2.

### CLI

`src/supermodel/cli.py`

New opt-in switches:

- `--pa-shadow`
- `--pa-shadow-weight`
- `--pa-shadow-simulations`

The default CLI path remains unchanged unless `--pa-shadow` is explicitly supplied.

## Verification performed

### Repository regression

- Python compileall: **PASS**
- Pytest: **211 collected / 211 passed**
- Ruff: **not run** because Ruff is not installed in the active environment; no lint-pass claim is made.

### Wheel/package gate

Built and installed successfully:

` sports_supermodel-2.5.0.dev4+pa.shadow.candidate-py3-none-any.whl `

SHA-256:

`ef4e744e54adfd4021f128ecceb239cb13d8c31ff3565912cea0d0e8371bf6c2`

Installed-wheel smoke checks verified:

- candidate package version;
- `pa_live` / `pa_simulator` imports;
- packaged historical prior resource;
- event-probability normalization;
- all 216 transition keys.

### Frozen real pregame snapshot integration

A real immutable pregame snapshot for gamePk `824403` (NYM @ CLE, 2026-08-04) was rerun through RC1 at 100,000 simulations:

- parity: `PARTIAL_PARITY` because the old frozen snapshot predates reliever-only capture and therefore uses both all-staff bullpen fallbacks;
- away win probability: `0.45939`;
- mean simulated score: `NYM 4.37382 – CLE 4.52777`;
- extra-inning probability: `0.09994`;
- elapsed: `6.71 seconds`;
- maximum RSS: `304,988 KB`.

The performance result indicates that 100,000 PA simulations/game is operationally feasible for local shadow runs, though a full 15-game serial slate is roughly a ~100-second class workload on this environment.

A separate end-to-end candidate evaluation on that same frozen game fit the actual seven-model ensemble, blended the conservative 20% PA probability, and ran 100,000 PA games. It produced a non-authoritative `CLE` pick at `0.571212` blended probability, raw PA away probability `0.45864`, PA mean score `NYM 4.36537 – CLE 4.52503`, and correctly returned `PASS` because the seven-model component overlap with the blended pick was only `2/7`. This verifies that the candidate does not bypass the existing component-consensus gate.

## Deliberately not implemented / not promoted

1. **No production promotion.** V2.3.3 + V2.4 RC2 + incumbent Poisson remain authoritative.
2. **No 70–80% PA moneyline authority.** Historical point estimates favored high PA weights, but the improvement over the current Poisson blend was not statistically decisive.
3. **No direct weather/park PA event adjustment.** The prior historical environmental layer did not earn inclusion.
4. **No unvalidated bullpen-fatigue event-rate adjustment.** Availability is captured and exposed, but RC1 does not invent an effect size.
5. **No fixed 0.20-run PA score veto.** Score disagreement is diagnostic only.
6. **No public publisher auto-enable.** The dormant public platform remains unchanged.
7. **No GitHub Actions repair.** The existing Python 3.12 failure still requires the actual failed workflow log.

## Remaining promotion gates

1. Perform a **fresh network-backed pregame capture** with confirmed lineups using the new active-roster reliever profile path.
2. Run PA shadow at 100,000 simulations/game beside unchanged production on fresh slates and verify artifact/persistence behavior.
3. Settle games prospectively as an operational sanity check; this is not intended to replace the completed historical architecture backtest.
4. Decide whether bullpen availability deserves a direct PA adjustment only after a point-in-time historical ablation validates a specific method.
5. Inspect and repair the Python 3.12 CI failure from real logs, then rerun the full matrix.
6. Explicitly approve promotion before replacing the Poisson score-distribution engine or changing production moneyline influence.

## Current decision

**Implementation candidate: PASS**  
**Production promotion: NOT YET**
