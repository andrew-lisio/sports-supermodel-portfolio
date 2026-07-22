# Changelog

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
