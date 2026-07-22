# Architecture

## End-to-end flow

```text
                           user chooses date
                                  |
                                  v
                    official MLB schedule capture
                                  |
          +-----------------------+-----------------------+
          |                                               |
          v                                               v
 immutable schedule/pregame snapshots          editable official-slate table
                                                          |
                                      browser / terminal / CSV / JSON
                                                          |
                                                          v
                                          validated two-way moneylines
                                                          |
                                              immutable market snapshot
                                                          |
                                                          v
historical team logs                                     match by gamePk
        |                                                 |
        v                                                 |
canonical game reconstruction ---- official schedule/home-away attachment
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
                      |
                      v
          CSV / JSON / optional comparison report
```

## Package modules

- `mlb_v2.py`: historical state, feature replay, model construction, calibration, walk-forward evaluation, and Poisson scoring.
- `live_mlb.py`: no-key MLB client, pregame capture, context parsing, live slate evaluation, and report writing.
- `odds_input.py`: user-input contract, American/decimal parsing, CSV/JSON loading, official-slate template generation, and terminal prompts.
- `workflow.py`: shared end-to-end orchestration used by both user interfaces.
- `web_app.py`: local Streamlit browser interface.
- `cli.py`: installable terminal interface.
- `game_registry.py`: official `gamePk` identity, schedule parsing, doubleheader handling, and immutable snapshot storage.
- `providers.py`: pregame context contract and provider pipeline.
- `market.py`: odds conversion and market-probability helpers. It contains no bankroll or staking logic.
- `feedback.py`: prospective-result feedback utilities.
- `inning_simulator.py`: lower-level inning-simulation experiments retained for development.

## Interface separation

The browser and terminal interfaces do not contain separate model implementations. Both call the same workflow functions:

1. `capture_official_slate`
2. `moneylines_from_records`, `load_moneylines`, or `collect_moneylines_interactively`
3. `evaluate_captured_slate`

This prevents the browser application from drifting away from the command-line model.

## Market-input boundary

The project deliberately separates public game context from user-supplied market prices.

- Public MLB data is captured under schedule and pregame snapshot kinds.
- User-entered odds are stored under `market_input` snapshots.
- No sportsbook credentials are requested.
- The engine does not scrape screenshots or use OCR.
- Incomplete two-way markets are rejected.
- `gamePk` is preferred over team/date matching.
- Ambiguous doubleheaders fail closed.

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
- User inputs with duplicate `gamePk` values are rejected.
- Doubleheaders without `gamePk` are rejected as ambiguous.
- Missing advanced fields are paired with missingness signals.

## Prediction-only boundary

V2.3.3 ends at probabilities, expected scores, confidence rankings, fair odds, and market differences. It intentionally has no bankroll object, staking module, wager-size output, exposure cap, or Kelly calculation.
