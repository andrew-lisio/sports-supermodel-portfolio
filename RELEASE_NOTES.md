# V2.3.3 release notes

V2.3.3 is a schedule-integrity hotfix for the open-input, prediction-only application.

## Fixed

The MLB schedule API can return the same official `gamePk` more than once in a multi-day response when a game is postponed, suspended, resumed, or rescheduled. V2.3.2 compared every mutable schedule field and stopped the evaluation when repeated rows differed. V2.3.3 now:

- Uses the game-level `officialDate` when it is available.
- Reconciles repeated rows when the official away and home team IDs match.
- Prefers the most advanced and information-rich representation.
- Retains missing probable-pitcher or venue details from the richer duplicate row.
- Still fails closed when one `gamePk` is attached to different teams.

## Unchanged

- Browser, terminal, CSV, JSON, and Python input methods
- Seven required winner-model components
- Calibrated ensemble and two-sided Poisson model
- 100,000-simulation defaults
- Immutable pregame snapshots and post-start protection
- Prediction-only boundary with no Kelly, bankroll, stake sizing, or exposure logic

## Test status

31 tests pass in the release environment.

## Predictive-performance claim

This hotfix changes schedule parsing and reliability only. It does not claim an improvement in predictive accuracy or profitability.
