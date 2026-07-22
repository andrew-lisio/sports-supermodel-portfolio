# V2.3.2 release notes

V2.3.2 is the open-input, prediction-only release prepared for GitHub publication.

## Main change

The project no longer depends on a private workflow where a user uploads sportsbook screenshots to a chat. Users can now provide two-way moneylines directly through:

- A local browser application
- Interactive terminal prompts
- CSV files
- JSON files
- The Python API

The project does not scrape screenshots, use OCR, request sportsbook credentials, or require a paid odds API.

## Input safeguards

- American and decimal prices are supported.
- Both sides of the market are required.
- Blank or disabled rows are skipped.
- Official MLB `gamePk` is attached by generated templates and the browser app.
- Ambiguous doubleheaders fail closed.
- Duplicate `gamePk` inputs are rejected.
- Accepted market inputs are preserved in timestamped local snapshots.

## Prediction engine

The predictive model remains the V2.3 engine:

- Seven required winner-model components
- Calibrated ensemble with frozen V1 anchor
- Two-sided Poisson expected-runs model
- 100,000-simulation defaults
- Official `gamePk` identity and doubleheader controls
- Immutable pregame snapshots
- Explicit last-game feature block

V2.3.2 improves usability and reproducibility; it does not claim a new predictive-performance gain over V2.3.

## Prediction-only boundary

The active package has no Kelly criterion, bankroll management, stake recommendation, minimum-return rule, or exposure allocation. It reports probability, confidence, expected score, fair odds, and market comparison only.

## Test status

29 tests pass in the release environment.

## V2.4 boundary

V2.4 development should occur on a separate branch and focus on richer lineup, starting-pitcher, bullpen, recent-form, weather, attribution, and calibration systems.
