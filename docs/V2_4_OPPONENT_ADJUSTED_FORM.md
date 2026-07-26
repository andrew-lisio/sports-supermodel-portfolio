# V2.4 Opponent-Adjusted Recent Form

Phase 6A tests whether recent results become more predictive after accounting for the strength of the opponent at the time each game was played.

## Point-in-time construction

For every completed game, the engine captures the opponent's pregame smoothed win percentage, Pythagorean strength, runs scored per game, and runs allowed per game. It then records four centered residuals:

- adjusted win: result relative to opponent strength
- adjusted runs scored: actual runs minus the opponent's pregame runs-allowed expectation
- adjusted runs prevented: the opponent's pregame scoring expectation minus actual runs allowed
- adjusted run differential: the sum of the two run residuals

Positive values always indicate stronger performance. The run residuals are clipped to limit the influence of a single extreme game.

The opponent snapshot is taken before the current day's games and state updates occur only after the full date is processed. This preserves the same-day leakage protection used by the existing feature builder.

## Experiment

Run:

```bash
sports-supermodel-optimize-opponent-form
```

The experiment compares the frozen V2.4 alpha-0.25 contract with several adjusted-window combinations on identical chronological development games. The final holdout remains locked. Generated outputs are written to `reports/v2_4_opponent_form/`.

Opponent adjustment is not enabled in the active V2.4 candidate unless one of the adjusted contracts clears the predefined Brier, log-loss, accuracy, AUC, and calibration thresholds.
