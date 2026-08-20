# Sports SuperModel

**MLB probabilistic forecasting, game simulation, and sportsbook market analysis**

Sports SuperModel is a baseball analytics project that estimates game outcomes, simulates score distributions, and compares model probabilities with sportsbook prices. The current MLB system combines a seven-model winner ensemble with 100,000 simulated games per matchup and a newer plate-appearance generative simulator that builds games one batter at a time.

The project is designed to separate **prediction quality** from **market value**. A team can be likely to win without being a good value at the listed price.

## What the system does

- **Seven-model winner ensemble:** combines logistic regression, random forest, neural network, Elo/Pythagorean, XGBoost, LightGBM, and CatBoost.
- **100,000-game simulation layer:** produces win probabilities, projected scores, totals, team totals, run-line distributions, and score-tail outcomes.
- **Sportsbook price comparison:** converts model probabilities into fair odds and compares them with market prices.
- **Edge and expected return:** measures the gap between model probability and the sportsbook's break-even probability, estimates expected return at a given line, and calculates the worst price that still retains positive modeled value.
- **Plate-appearance simulation:** simulates complete games from batter/pitcher event probabilities rather than beginning with a predetermined final score.
- **Point-in-time validation:** historical predictions are built using only information that would have been available before each game.

## Market analysis

The market layer answers a different question from the prediction layer.

If the model estimates a team at 60% to win, its fair American price is about **-150**. A sportsbook line can then be evaluated against that estimate:

- **Break-even probability:** the win rate required by the listed sportsbook price.
- **Fair odds:** the price implied by the model's estimated probability.
- **Edge:** model win probability minus sportsbook break-even probability.
- **Expected return:** probability-weighted return at the listed price.
- **Playable-through price:** the worst line at which the model still estimates positive value.

This lets the system distinguish between a high-probability favorite and a genuinely favorable price. The engine analyzes prices; it does not place wagers or manage a bankroll.

## Current validation result

The canonical plate-appearance architecture test used 2024 as the development period and a locked **1,972-game 2025 holdout**.

| Engine | Winner accuracy | Brier score | Log loss |
| --- | ---: | ---: | ---: |
| Frozen Poisson | 54.06% | 0.247568 | 0.688263 |
| Inning generative | 53.70% | 0.251952 | 0.698752 |
| **PA generative** | **54.46%** | **0.245055** | **0.683124** |

The PA simulator's clearest improvement was in the realism of the full score distribution. On the same holdout, its calibration error and exact-score likelihood improved over the frozen Poisson benchmark, and shutouts, blowouts, high-scoring games, and one-run games were produced at rates closer to actual MLB outcomes.

The PA model remains a candidate rather than automatically replacing the current production path because the project requires new models to earn promotion through historical and prospective validation.

Full methodology: [`docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md`](docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md)

## How it works

```text
Official pregame MLB data
          |
          +-------------------------+
          |                         |
          v                         v
Point-in-time features       Game simulation
          |                  /             \
          v                 v               v
Seven-model ensemble   Poisson engine   PA simulator
          |                 |               |
          +-----------------+---------------+
                            |
                            v
                Win and score distributions
                            |
Sportsbook prices ----------+
                            |
                            v
          Fair odds, break-even probability,
          edge, expected return, price limits
```

The production and experimental paths are intentionally separated. New models can be evaluated without silently changing the live production model.

## Plate-appearance generative simulator

The PA simulator creates a baseball game from individual plate appearances. It samples events such as:

`K | BB | HBP | 1B | 2B | 3B | HR | REACH | OUT`

During each simulated game it tracks:

- inning and half-inning
- outs and occupied bases
- batting-order position
- starting-pitcher and bullpen phase
- pitcher workload
- score
- extra innings
- automatic runners
- walk-off endings

The packaged empirical prior was built from **182,449 effective 2024 plate-appearance transitions** across all 216 base/out/event states.

For live use, the PA path requires confirmed starting pitchers and complete nine-player batting orders. If those inputs are missing, it fails closed rather than labeling an incomplete simulation as full-parity output.

More detail: [`docs/PA_GENERATIVE_SIMULATOR.md`](docs/PA_GENERATIVE_SIMULATOR.md)

## Seven-model winner stack

The active winner ensemble contains:

1. Logistic regression
2. Random forest
3. Neural network
4. Elo/Pythagorean model
5. XGBoost
6. LightGBM
7. CatBoost

Component probabilities are retained so agreement and disagreement between models can be inspected instead of exposing only one final number.

## Validation approach

Sports predictions are easy to overfit, so the project uses chronological and point-in-time testing rather than relying on random train/test splits.

Key controls include:

- features are computed before the target game updates historical state;
- same-day results are prevented from leaking into earlier predictions;
- locked out-of-year holdouts are used for major architecture tests;
- missing historical inputs remain neutral when their point-in-time provenance cannot be verified;
- model identities, seeds, inputs, and validation artifacts are recorded;
- conflict filters can abstain instead of forcing a recommendation;
- experimental models remain separate from production until promotion criteria are met.

See [`docs/VALIDATION.md`](docs/VALIDATION.md) and [`docs/FEATURE_AUTHORITY_AUDIT.md`](docs/FEATURE_AUTHORITY_AUDIT.md).

## Current model tracks

| Track | Role | Production authority |
| --- | --- | --- |
| V2.3.3 | Current winner-model production path | Yes |
| V2.4 RC2 | Winner-model shadow candidate | No |
| Poisson simulator | Current score-distribution engine | Yes |
| PA generative RC1 | Generative simulation candidate | No |

The current development package is `2.6.0.dev1+pa.generative.integration`.

## Repository structure

```text
src/supermodel/          Core models, simulation, market pricing, storage, API, and CLI logic
tests/                   Unit and regression tests
config/                  Model, feature, validation, and execution configuration
docs/                    Current architecture, data, validation, and operations documentation
docs/validation/         Canonical PA validation reports and artifacts
examples/                Example market-input formats
data/                    Public data policy and derived artifacts
deploy/                  Hosted-service and deployment foundation
.github/workflows/       Continuous integration
```

Private sportsbook screenshots, account-specific information, and private runtime data are not stored in this repository.

## Quick start

Python 3.11 or 3.12 is recommended.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[ui,dev]"
python -m compileall -q src app.py tests
python -m ruff check .
python -m pytest
```

macOS / Linux:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[ui,dev]'
python -m compileall -q src app.py tests
python -m ruff check .
python -m pytest
```

The test suite uses controlled fixtures and does not require private season-history data.

A full live slate run additionally requires historical inputs and current pregame MLB data, which are not bundled with the repository.

## Main entry points

```text
sports-supermodel            Main slate evaluation CLI
sports-supermodel-ui         Streamlit interface
sports-supermodel-history    Historical data freshness workflow
sports-supermodel-registry   Model/version registry inspection
sports-supermodel-evidence   Validation evidence utilities
sports-supermodel-publish    Publication workflow
sports-supermodel-settle     Result settlement
```

## Data and attribution

Historical plate-appearance and game-state research used Retrosheet data.

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.

Additional third-party source information is documented in [`NOTICE.md`](NOTICE.md) and [`docs/THIRD_PARTY_DATA.md`](docs/THIRD_PARTY_DATA.md).

## Development and attribution

Created and maintained by **Andrew Lisio**. I used **ChatGPT** throughout development as a coding and debugging copilot. I set the project goals, decided what to test, reviewed the results, and made the final modeling and product decisions.

## Roadmap

The long-term goal is to expand the SuperModel beyond MLB to additional sports and release a consumer-facing application that can present high-probability predictions, market value, and custom-line analysis in one interface.

## Responsible use

This project is for statistical, educational, and research purposes. It does not guarantee outcomes or profit, and all model probabilities can be wrong or miscalibrated.

See [`DISCLAIMER.md`](DISCLAIMER.md).

## Source-use terms

This repository is source-available, not open source. No open-source license is granted. Review [`COPYRIGHT.md`](COPYRIGHT.md) before copying or reusing project code. GitHub's platform terms still apply to public repositories.
