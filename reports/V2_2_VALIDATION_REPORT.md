# V2.2 operational validation report

## Executed checks

- Historical feature rows were rebuilt with home/away identity for 1,477 reconstructed
  games through July 19, 2026.
- Two rows could not be matched to the static schedule and retained explicit missingness.
- Five chronological walk-forward windows produced 1,109 out-of-fold predictions.
- The seven-component V2 winner ensemble was blended at the pre-existing 80/20 ratio
  with a newly trained two-sided Poisson expected-runs model.
- The score component used 10,000 simulations per out-of-fold game.
- A 15-game operational smoke test used 100,000 score simulations and 100,000 final
  Bernoulli draws per game.
- The repository test suite passed 25 tests.

## Aggregate walk-forward results

| Model | Accuracy | Brier | Log loss | AUC |
|---|---:|---:|---:|---:|
| Frozen V1 baseline | 0.5428 | 0.2560 | 0.7080 | 0.5601 |
| V2 winner ensemble with home/away | 0.5365 | 0.2502 | 0.6937 | 0.5464 |
| V2.2 80/20 winner + trained score blend | **0.5582** | **0.2485** | **0.6902** | **0.5611** |

V2.2 clears the model-quality portions of the current merge gate on this walk-forward
set: more than 1,000 games, improved Brier score, improved log loss, improved accuracy,
and AUC not worse than V1.

## Remaining production gate

V2.2 is still not merged to `main`. The repository has not accumulated the required 500
market-tracked bets with closing-line-value evidence. Confirmed lineup, injury, bullpen,
weather and advanced Statcast fields also lack sufficient point-in-time historical
coverage to be represented as validated trained inputs.

## Schedule provenance limitation

The executed validation used a publicly downloadable 2026 original-schedule CSV to
recover home/away identity because the execution container could not make outbound MLB
Stats API calls. The operational command itself fetches and freezes MLB Stats API
schedule payloads. Original schedules can differ from later postponements or rescheduled
games, so the validation home/away mapping is provisional even though only two rows were
unmatched.
