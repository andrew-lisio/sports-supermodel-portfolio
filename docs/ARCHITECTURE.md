# Architecture

## Core flow

```text
historical team logs
        |
        v
canonical game reconstruction ---- official schedule/gamePk attachment
        |
        v
pregame feature replay
        |
        +-----------------------------+
        |                             |
        v                             v
seven-model winner ensemble     two-sided Poisson score model
        |                             |
        +-------------+---------------+
                      v
             calibrated 80/20 blend
                      |
                      v
        Monte Carlo final probability draws
                      |
                      v
 confidence rank + fair odds + market comparison
```

## Package modules

- `mlb_v2.py`: historical state, feature replay, model construction, calibration, walk-forward evaluation, Poisson scoring.
- `live_mlb.py`: no-key MLB client, pregame capture, context parsing, live slate evaluation, report writing.
- `game_registry.py`: official `gamePk` identity, schedule parsing, doubleheader handling, immutable snapshot storage.
- `providers.py`: pregame context contract and provider pipeline.
- `market.py`: odds conversion and market-probability helpers. It contains no bankroll or staking logic.
- `feedback.py`: prospective-result feedback utilities.
- `inning_simulator.py`: lower-level inning simulation experiments retained for development.
- `cli.py`: installable command-line workflow.

## Ensemble construction

The seven component models are trained on chronological pregame features. A later chronological slice is reserved for component weighting and calibration. Component weights are based on Brier score, after which a logistic calibrator maps the weighted output. A frozen V1 probability is retained as a conservative prior anchor with its weight selected on the calibration slice.

## Simulation

The Poisson model estimates expected runs for canonical Team A and Team B. Runs are simulated separately and tied regulation outcomes are resolved within the simulation helper. The score-model win probability is blended with the winner ensemble, then a final Bernoulli Monte Carlo draw produces the published probability.

The final draw is intentionally explicit so report manifests can state exactly how many simulations were executed.

## Data-integrity controls

- Pregame features are generated before state updates for the target game.
- Immutable snapshots reject content changes at an existing timestamped path.
- Post-start captures cannot be written as valid pregame snapshots.
- Official `gamePk` is used for exact game identity.
- Historical doubleheaders that cannot be disambiguated are excluded.
- Missing advanced fields are paired with missingness signals.

## Prediction-only boundary

V2.3.1 ends at probabilities, expected scores, confidence rankings, fair odds, and market differences. It intentionally has no bankroll object, staking module, wager-size output, exposure cap, or Kelly calculation.
