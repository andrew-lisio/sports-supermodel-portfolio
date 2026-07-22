# Sports SuperModel

An experimental, reproducible MLB game-prediction research project that combines seven winner models, a calibrated ensemble, a Poisson score model, immutable pregame snapshots, and Monte Carlo simulation.

> **Current release: V2.3.1 — prediction only.** Bankroll management, wager sizing, stake recommendations, and the Kelly criterion have been removed from the active engine. The project reports probabilities, confidence rankings, expected scores, fair odds, and model-versus-market differences only.

## Important notice

This software is provided for **recreational, educational, and research use only**. It is not financial, investment, legal, gambling, or professional advice; it does not guarantee outcomes; and it is not a sportsbook or wagering service. Sports outcomes are uncertain, models can be wrong, data can be delayed or inaccurate, and anyone who chooses to gamble assumes the entire risk of loss.

Use is limited to people who are legally permitted to access gambling-related information in their jurisdiction and who satisfy the applicable legal age requirement. Review [DISCLAIMER.md](DISCLAIMER.md) before using or distributing the project. The disclaimer and license are risk-management documents, not a guarantee against legal claims; obtain advice from a qualified attorney for jurisdiction-specific protection.

## What the project does

The pipeline:

1. Loads historical MLB team game logs.
2. Reconstructs canonical games and attaches official home/away identity when available.
3. Builds pregame-only features without using information from the target game.
4. Captures public MLB schedule, probable-pitcher, lineup, venue, and weather context into timestamped immutable snapshots.
5. Fits seven winner-model components and a separate Poisson expected-runs model.
6. Runs Monte Carlo score simulations and final probability draws.
7. Ranks every game by model confidence and agreement.
8. Compares the model probability with manually entered market prices.
9. Writes reproducible CSV and JSON artifacts.

The engine intentionally **does not** tell a user how much to wager.

## Model stack

The active winner ensemble contains:

- Logistic regression
- Random forest
- Multilayer perceptron neural network
- Elo/Pythagorean baseline component
- XGBoost
- LightGBM
- CatBoost

Component weights are derived from chronological calibration-slice Brier performance. Their combined probability is calibrated and conservatively blended with the frozen V1 baseline. A separately trained two-sided Poisson model estimates expected runs for both teams. By default, the live evaluator blends the calibrated winner ensemble and score model at an 80/20 ratio.

For each game, the default execution performs:

- **100,000 score simulations**
- **100,000 final Bernoulli probability draws**
- Optional 100,000-draw two-leg top-pick parlay comparisons under an explicitly stated independence assumption

## Feature system

### Populated historical features

- Smoothed season winning percentage
- Pythagorean strength
- Runs scored and allowed per game
- Run differential
- Rolling 5-, 10-, and 20-game form
- Exponentially weighted offense, prevention, and results
- Rest days
- Schedule density over the prior 3 and 7 days
- Starter team-result and recent-runs-allowed proxies
- Official home/away identity when recoverable
- Explicit immediately preceding game context:
  - result
  - runs scored and allowed
  - run differential
  - total runs and absolute margin
  - previous home/away status
  - previous opponent strength
  - shutout indicators
  - blowout win/loss indicators

### Provider-ready but not fully historically trained

The schema supports advanced pitcher, lineup, bullpen, injury, defense, weather, park, umpire, travel, and market fields. When point-in-time historical coverage is unavailable, these fields remain neutral and receive missingness indicators rather than fabricated values.

This distinction matters: a live snapshot may record a lineup or weather condition, but that does not automatically mean the current fitted probability has a validated numerical response to that field.

## Outputs

A live evaluation includes fields such as:

- `pick` and `pick_probability`
- away/home probabilities
- confidence rank
- number of model components agreeing with the pick
- expected away and home runs
- score-simulation win probability
- no-vig market probability
- break-even probability
- edge versus no-vig and raw break-even probabilities
- model-implied fair American odds
- lineup-confirmation flag
- previous-game context
- each model component's team-oriented probability

No active output contains bankroll, stake, exposure, or Kelly fields.

## Repository layout

```text
.
├── config/                 Feature registry and validation gates
├── data/                   Historical team logs and source notes
├── docs/                   Architecture, usage, validation, upload guide, history
├── examples/               Example odds input and historical run scripts
├── reports/                Validation and preserved historical/live outputs
├── scripts/                Command wrappers and validation utilities
├── snapshots/              Immutable public and private-input snapshots
├── src/supermodel/         Installable Python package
├── tests/                  Offline automated tests
├── DISCLAIMER.md           Gambling/recreational-use legal notice
├── LICENSE                 MIT open-source license
└── pyproject.toml          Package and tool configuration
```

## Requirements

- Python 3.11 or newer
- Internet access for live MLB capture
- A manually prepared two-way moneyline CSV

The historical tests and frozen-snapshot tests run without live network access.

## Installation

### Windows PowerShell

```powershell
# 1. Enter the project directory
cd sports-supermodel

# 2. Create a virtual environment
py -3.11 -m venv .venv

# 3. Activate it
.\.venv\Scripts\Activate.ps1

# 4. Upgrade packaging tools
python -m pip install --upgrade pip setuptools wheel

# 5. Install the project and development tools
python -m pip install -e ".[dev]"
```

### macOS or Linux

```bash
cd sports-supermodel
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

Optional gradient-boosting libraries are included in the default dependencies. If one cannot be installed on a platform, review the error rather than silently assuming all seven components executed.

## Prepare the odds file

Copy the template:

```powershell
Copy-Item examples\manual_moneylines.example.csv examples\manual_moneylines.csv
```

Required columns:

```csv
game_date,away_team,home_team,away_odds,home_odds,game_pk
2026-07-22,ATH,AZ,111,-151,
2026-07-22,CIN,SEA,134,-174,
```

Use MLB abbreviations consistently. `game_pk` is optional for ordinary single games but strongly recommended for doubleheaders and rescheduled games.

## Run a live slate

```powershell
sports-supermodel `
  --date 2026-07-22 `
  --odds examples\manual_moneylines.csv `
  --simulations 100000 `
  --top-n 5
```

Equivalent module command:

```powershell
python -m supermodel --date 2026-07-22 --odds examples\manual_moneylines.csv
```

Artifacts are written to `reports/live/` by default. Public schedule and pregame responses are frozen under `snapshots/` before evaluation.

Useful options:

```text
--data-dir PATH
--snapshot-dir PATH
--output-dir PATH
--simulations INTEGER
--top-n INTEGER
--home-field-logit-adjustment FLOAT
--skip-parlays
```

Keep `--home-field-logit-adjustment` at zero unless a nonzero value has been independently validated.

## Python API example

```python
from supermodel.live_mlb import LiveEvaluationConfig, evaluate_live_slate

results = evaluate_live_slate(
    historical_features=historical_features,
    future_features=future_features,
    moneylines=moneylines,
    config=LiveEvaluationConfig(simulations=100_000, top_n=5),
)

print(results[[
    "confidence_rank",
    "pick",
    "pick_probability",
    "model_overlap",
    "fair_odds",
]])
```

## Testing

```powershell
pytest
```

The V2.3.1 release contains **21 passing tests** covering data construction, official game identity, doubleheaders, immutable snapshots, pregame integrity, lineup/weather parsing, pitcher-stat parsing, simulation behavior, confidence ranking, and the absence of active staking outputs.

## Validation status

V2 remains experimental. On the preserved 1,101-game chronological comparison, the explicit-last-game V2.3 feature set produced:

| Metric | V2.3 |
|---|---:|
| Accuracy | 54.68% |
| Brier score | 0.24779 |
| Log loss | 0.68887 |
| AUC | 0.56480 |

Calibration and ranking improved slightly relative to the same-sample V2.2.2 baseline, while threshold accuracy declined. These results do not demonstrate profitability and are not a promise of future performance. See [docs/VALIDATION.md](docs/VALIDATION.md) and the files under `reports/`.

## Data integrity principles

- Official MLB `gamePk` is the canonical identifier whenever available.
- Doubleheaders are not merged into one invented game.
- Ambiguous historical rows are excluded rather than assigned falsely.
- Pregame snapshots are immutable and timestamped.
- Captures made after scheduled start cannot be represented as valid pregame snapshots.
- Missing historical advanced data remains missing/neutral rather than being backfilled with hindsight.
- Model confidence is computed independently of price.

## Known limitations

- Historical team logs do not contain every advanced point-in-time input supported by the schema.
- Starter features still include team-result proxies and are not a complete pitch-level projection system.
- Bullpen availability, individual batter projections, breaking injuries, weather, and roof decisions are not yet fully trained numerical inputs.
- Original schedules may differ from later postponements or rescheduled games.
- Two-leg parlay evaluation assumes independent game outcomes.
- Probabilities can be miscalibrated, especially in small samples or regime changes.
- Market prices can move after a snapshot.

## Roadmap toward V2.4

Planned work includes:

- 1/3/5/10-game recent-form engine with learned decay
- Individual confirmed-lineup projections
- Pitcher-specific FIP/xFIP/SIERA/xERA and pitch-quality model
- Bullpen availability and leverage-usage model
- Weather, park, roof, travel, defense, and injury integration
- Category-level prediction attribution
- Improved calibration and prospective tracking
- Learned ensemble weighting under strict walk-forward validation

V2.4 will remain separate until it passes the repository's validation and data-integrity gates.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). New model features should include:

- point-in-time provenance
- missingness behavior
- leakage tests
- chronological validation
- updated documentation

## Security and data issues

For vulnerabilities or accidental exposure of private information, follow [SECURITY.md](SECURITY.md). Do not commit credentials, account details, or private sportsbook information. Before publishing, complete [docs/PUBLIC_RELEASE_CHECKLIST.md](docs/PUBLIC_RELEASE_CHECKLIST.md).

## License

Released under the [MIT License](LICENSE). The license includes an “AS IS” warranty disclaimer and limitation of liability. The additional recreational-use and gambling-risk notice is in [DISCLAIMER.md](DISCLAIMER.md).

## Responsible use

Never treat a model probability as certainty. Do not chase losses, borrow to gamble, or wager money needed for living expenses. Set limits in advance and stop when gambling is no longer recreational. In the United States, the National Problem Gambling Helpline is available by call or text at **1-800-MY-RESET**. Outside the United States, use an appropriate local support service.
