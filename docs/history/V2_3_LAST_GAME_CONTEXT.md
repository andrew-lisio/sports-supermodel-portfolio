# V2.3 Explicit Last-Game Context

V2.3 adds an explicit feature block for the immediately preceding completed game.
The former pipeline already included the previous result inside rolling 5/10/20 and
exponentially weighted form, but that diluted a one-game event. The new block lets
all fitted models learn a separate response to the latest result without manually
forcing a bounce-back or momentum assumption.

## Added pregame fields

- Result, runs scored, runs allowed and run differential
- Total runs and absolute margin
- Home/away status
- Opponent pregame smoothed win rate and Pythagorean strength
- Scored/allowed shutout indicators
- Blowout win/loss indicators (six-run margin)

All fields are updated only after the prior date is complete, preserving the existing
same-day leakage guard. They are incorporated into both the seven-component winner
ensemble and trained Poisson expected-runs models.

## Same-sample chronological comparison

On 1,101 out-of-fold games using the same reconstruction and schedule attachment:

| Version | Accuracy | Brier | Log loss | AUC |
|---|---:|---:|---:|---:|
| V2.2.2 | 55.68% | 0.24807 | 0.68944 | 0.56319 |
| V2.3 last-game block | 54.68% | 0.24779 | 0.68887 | 0.56480 |

The last-game block improved probability calibration (Brier/log loss) and ranking
(AUC), but reduced 0.50-threshold accuracy in this limited sample. It therefore remains
experimental and does not replace V1 or the V2.2.2 rollback artifact.
