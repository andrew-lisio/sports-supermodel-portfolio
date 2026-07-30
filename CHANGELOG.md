## 2.4.0.rc2.post1

- Keep the RC2 automatic completed-game refresh and fail-closed stale-data protection unchanged.
- Version the conflict filter as a provisional recommendation gate rather than a second prediction model.
- Record production and shadow raw picks, filter statuses, exact triggers, component consensus, and projected-score direction in prospective evidence.
- Add `sports-supermodel-conflicts` to grade helpful passes, false passes, accepted-pick accuracy, coverage, and trigger-level results.
- Keep the filter thresholds unchanged until a larger prospective cohort supports retuning.

## 2.4.0.rc2

- Automatically backfill official completed MLB games through the day before every slate.
- Persist refreshed results in a local runtime cache and record freshness metadata in evidence.
- Fail closed on API refresh failure or unresolved prior-date games instead of using stale history.
- Preserve raw ensemble predictions while excluding component/score conflicts and low-confidence rows from top picks.
- Add `sports-supermodel-history` preflight command.

# Changelog

## Unreleased — Local interface redesign

- Replaced the raw editable odds table with automatic official-slate loading and matchup cards.
- Added visible pregame/locked status, simplified controls, and an app-style confidence board.
- Shows V2.3.3 production and V2.4 RC1 shadow probabilities, seven-model overlap, disagreement, and simulated score together.
- Moved full tables, feature sensitivity, downloads, and artifact paths behind an advanced section.
- Removed technical runtime-path controls from the normal interface.
- Separated the frozen predictive model commit from later UI-only repository commits so prospective cohorts remain tied to `c09db37`.

## 2.4.0.rc1 — Final code-complete candidate

- Squashed the complete V2.4 implementation above the protected `ceda10d` rollback point.
- Runs frozen V2.3.3 as production and the exact V2.4 candidate as a parallel shadow track.
- Records both prediction tracks, the candidate Git commit, immutable inputs, closing lines, and outcomes in the prospective evidence ledger.
- Added point-in-time public lineup aggregates, recent bullpen workload, team pitching/fielding proxies, weather/roof/wind normalization, and travel/time-zone context.
- Added a bounded adaptive V2.4 shadow overlay that activates only after chronological Brier/log-loss gates pass; otherwise the base candidate probability is preserved.
- Added browser and CLI production-versus-shadow reporting.
- Preserved fail-closed behavior for unavailable Statcast, injury, advanced defense, catcher, and umpire sources.
- V2.4 remains `PENDING`; code completion does not bypass the 500-game prospective, CLV, integrity, provenance, or final-holdout gates.


## 2.4.0.dev11 — Consolidated accelerated candidate

- Consolidated the accelerated execution, prospective evidence, and point-in-time starter work onto one cumulative candidate branch.
- Set the promotion-gate candidate branch to `v2.4-accelerated-integration`.
- Preserved `v2.4-development` as the rollback point and left `main` unchanged.
- Retained the locked final holdout and `PENDING` promotion status until prospective evidence gates pass.
- No predictive feature, calibration, or seven-model ensemble behavior changed from `2.4.0.dev10`.



## 2.4.0.dev10

- Added immutable point-in-time starting-pitcher snapshots keyed by official `gamePk`, side, and MLB person ID.
- Corrected baseball innings parsing so `.1` and `.2` represent one and two outs.
- Added normalized starter collection fields and raw-payload SHA-256 preservation.
- Added starter-change detection, integrity auditing, and latest-pregame training-row export.
- Bound starter snapshots into prospective prediction evidence and expanded provenance checks.
- Preserved the existing predictive feature contract; Phase 7 makes no new accuracy claim.


## 2.4.0.dev9

- Added a hash-chained, append-only prospective evidence ledger keyed by official `gamePk`.
- Live workflow predictions now preserve snapshot hashes and point-in-time provenance.
- Added separate closing-line and outcome events plus an evidence audit CLI.
- Wired structured evidence reports into V2.4 promotion gates while preserving `PENDING`
  status during prospective accumulation.
- Ignored generated validation variants such as `reports/v2_4_validation_final/`.

## V2.3.3 — schedule-integrity hotfix

- Reconciles repeated MLB schedule rows for the same `gamePk` when away/home team IDs agree.
- Uses the game-level `officialDate` instead of the surrounding date bucket when available.
- Preserves richer probable-pitcher and venue metadata while preferring the most advanced game status.
- Continues to reject a repeated `gamePk` if it points to different away/home teams.
- Fixes live evaluations that previously failed with `Conflicting records for gamePk=...` on postponed, suspended, resumed, or rescheduled games.
- Active test suite: 31 passing tests.

## V2.3.2 — open-input application release

- Added a local Streamlit browser interface with an editable official-slate odds table.
- Added interactive terminal moneyline entry.
- Added CSV and JSON market-input support.
- Added American and decimal odds parsing with strict validation.
- Added official-slate template generation with `gamePk`, game number, starters, lineup status, and weather context.
- Added shared workflow orchestration so the browser, terminal, files, and Python API run the same model engine.
- Added fail-closed doubleheader matching and duplicate market-input rejection.
- Added immutable user-market snapshots for reproducibility.
- Added user-input, web-app, privacy, deployment, and GitHub documentation.
- Preserved the prediction-only boundary: no Kelly criterion, bankroll, stake sizing, or exposure logic is active.
- Active test suite: 29 passing tests.

## V2.3.1 — prediction-only GitHub release

- Removed the staking module from the active package.
- Removed bankroll configuration, Kelly calculations, stake recommendations, exposure caps, and all wager-sizing columns from live evaluation.
- Preserved probability, confidence, expected-score, fair-odds, no-vig, and market-edge analysis.
- Added an installable command-line interface and Python package metadata.
- Added a comprehensive README, architecture/data/validation/upload guides, MIT license, responsible-use disclaimer, contribution guidance, security policy, issue templates, and CI workflow.
- Preserved historical V1–V2.3 documentation, reports, snapshots, and daily run examples for auditability. Historical files may describe retired sizing experiments but are not active engine behavior.
- Added the July 22 preserved live reports.
- Active test suite: 21 passing tests.

## V2.2 minimum-bet correction

- Corrected the sportsbook rule from a $20 minimum profit to a $20 minimum wager.
- Replaced the default fixed overlap probability haircut with the raw model probability;
  Half Kelly is now the default risk reduction.
- Retained the overlap haircut only as an explicit experimental option.
- Added backward-compatible report aliases and a deprecated CLI alias for older artifacts.
- Added staking tests covering negative-odds bets whose $20 stake returns less than $20.

## V2.2 operational

- Added free MLB Stats API schedule and live-feed client with immutable capture.
- Added official historical schedule backfill for a trained home/away feature and
  fail-closed exclusion of ambiguous doubleheaders.
- Added official probable-pitcher, lineup, weather and season pitcher-stat parsing.
- Added leakage-safe future matchup feature construction.
- Added confidence-first live slate evaluation with 100,000 simulations.
- Added V1-style overlap, fair-odds, simulated-score and edge output fields.
- Kept pick ranking independent from Kelly and price filtering.
- Added explicit bankroll `alpha`, credit and open-exposure handling.
- Added optional two-leg parlay evaluation with an explicit independence assumption.
- Added a daily CLI and 9 new operational tests.
- Executed a 1,109-game chronological validation of the fixed 80/20 winner/Poisson
  blend; it improved accuracy, Brier, log loss and AUC versus the frozen V1 baseline.

## V2 development candidate

- Added leakage-controlled feature generation.
- Added seven fitted model components and chronological stacking/calibration.
- Added advanced point-in-time feature provider contract and missingness tracking.
- Added schedule-lock, feedback/CLV ledger, and inning-level simulator modules.
- Added five-fold expanding walk-forward trials and 100,000-trial historical replays.
- Added V1 versus V2 comparison reports.

## V1

- Frozen prior chat-resident model specification and recorded historical picks.

## V2.1 point-in-time data

- Added canonical official-game records keyed by MLB `gamePk`.
- Added immutable schedule and pregame snapshot storage.
- Added exact schedule-snapshot enrichment and doubleheader ambiguity rejection.
- Added the original executable staking layer; its minimum-profit interpretation was corrected on the later `v2.2-minimum-bet` branch.
- Repaired the repository test that depended on a machine-specific data path.

## V2.2 minimum-return adaptive-Kelly correction

- Corrected the private-book rule: when a wager would otherwise pay less than $20 total,
  the stake must be raised so the total return (stake plus net profit) is at least $20.
  This is neither a $20 minimum stake nor a $20 minimum profit.
- Added `minimum_stake_for_total_return`; examples: +150 requires $8.00, -150 requires
  $12.00, and -200 requires $13.34 to return at least $20.
- Kept the model probability unhaircut by default and retained confidence ranking before
  all staking decisions.
- Added adaptive fractional Kelly: 0.75 Kelly for top-five, 6/7-or-better picks with at
  least a two-point edge; 0.50 Kelly otherwise.
- Added a transparent high-confidence floor override capped at 1.75x Full Kelly and 12%
  of bankroll. This is intentionally labeled as a hybrid exception rather than pure Kelly.
- Added a 30% total slate-exposure cap allocated in confidence order.
- Added tests for minimum-return arithmetic, negative-odds favorites, the bounded override,
  and the corrected pass conditions.

## V2.3 experimental — explicit last-game context
- Added leakage-safe previous-game score, result, margin, shutout, blowout, location and opponent-strength features.
- Added last-game fields to live evaluation artifacts for auditability.
- Re-evaluated the July 21 slate with data through July 20.
- Chronological same-sample validation improved Brier/log loss/AUC but reduced raw accuracy; V2.3 remains experimental.

## 2.4.0.dev8 - Accelerated integration

- Added a canonical, fail-closed seven-model registry.
- Added CPU-aware accelerated and serial execution profiles.
- Parallelized independent ensemble components, matched baseline/candidate fits, and
  bounded candidate experiments without changing prediction contracts.
- Added execution metadata and serial-equivalence tests.

## 2.4.0.dev4+platform.foundation.1

- Added a canonical sportsbook/custom-line quote schema for MLB moneylines, run lines,
  game totals, and team totals.
- Added push-aware fair odds, expected ROI, and conservative playable-through prices.
- Added persistent compressed simulation snapshots so odds changes can be repriced without
  rerunning 100,000 simulations.
- Added price-independent High Probability and global-sportsbook Best Value ranking services.
- Added `sports-supermodel-refresh` for automatic completed-history and cached pitching-context
  refresh through the day before a slate.
- Preserved V2.3.3 production and V2.4 RC2 predictive identities; the rejected RC3 pitching
  feature experiment remains inactive.
