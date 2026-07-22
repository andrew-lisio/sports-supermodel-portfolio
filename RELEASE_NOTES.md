# V2.3.1 release notes

V2.3.1 is the final pre-V2.4 prediction-only release.

## Main change

The active engine no longer contains bankroll management, the Kelly criterion, stake recommendations, minimum-return rules, or exposure allocation. Live evaluation ends at confidence ranking, probability, expected score, fair odds, and market comparison.

## Included

- Seven required winner-model components
- Calibrated ensemble with frozen V1 anchor
- Two-sided Poisson expected-runs model
- 100,000-simulation defaults
- Official `gamePk` identity and doubleheader controls
- Immutable pregame snapshots
- Explicit last-game feature block
- Historical validation reports and cleaned daily outputs through July 22, 2026
- Installable CLI, tests, documentation, license, disclaimer, and GitHub templates

## Test status

21 tests pass in the release environment.

## V2.4 boundary

V2.4 development should occur on a separate branch and focus on richer lineup, starting-pitcher, bullpen, recent-form, weather, attribution, and calibration systems.
