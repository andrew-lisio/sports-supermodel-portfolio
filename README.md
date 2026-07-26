# Sports SuperModel

Sports SuperModel is an experimental, reproducible MLB game-prediction research project. It combines seven winner models, a calibrated ensemble, a separate Poisson score model, immutable pregame snapshots, and Monte Carlo simulation.

> **Current release: V2.3.3 — schedule-integrity hotfix for the open-input, prediction-only release.** Users no longer need to send sportsbook screenshots to another person. The repository includes a local browser interface, an interactive terminal workflow, and CSV/JSON import tools for entering two-way moneylines directly. Bankroll management, wager sizing, exposure limits, and the Kelly criterion are not part of the active engine.

## Important notice

This software is provided solely for **recreational, educational, statistical, and research use**. It is not financial, investment, legal, gambling, fiduciary, or other professional advice. It is not a sportsbook, does not place wagers, and does not guarantee accuracy, outcomes, or profit. Sports outcomes are uncertain, data may be incomplete or wrong, and model probabilities may be materially miscalibrated.

Anyone who chooses to gamble does so voluntarily and assumes the entire risk of loss. Users are responsible for legal-age requirements, local laws, taxes, sportsbook terms, and independent verification of every input. Read [DISCLAIMER.md](DISCLAIMER.md) before using, publishing, or distributing the project. No disclaimer can guarantee immunity from a lawsuit or regulatory inquiry; obtain jurisdiction-specific advice from a qualified attorney before marketing, monetizing, or operating the project for others.

## What changed in V2.3.3

V2.3.3 keeps the V2.3.2 open-input workflow and fixes a live MLB schedule edge case discovered during browser testing. Multi-day MLB schedule responses can repeat the same `gamePk` when a game is postponed, suspended, resumed, or rescheduled. The parser now reconciles repeated rows when the official away/home team IDs agree, uses the game-level `officialDate` when available, and still fails closed if the same `gamePk` is attached to different teams.

The open-input application introduced in V2.3.2 remains unchanged:

Users can now supply odds in four ways:

1. **Local browser app** — fetch the official slate, type odds into an editable table, and run the full model from a browser.
2. **Interactive terminal** — step through each official game and enter both sides of the moneyline.
3. **CSV file** — download or generate a slate template, fill the odds columns, and run it.
4. **JSON file** — submit the same structured input through JSON.

The input system:

- Accepts American or decimal odds.
- Converts all prices to canonical American odds internally.
- Uses official MLB `gamePk` values to distinguish doubleheaders.
- Allows users to skip games by leaving both odds cells blank or disabling a row.
- Rejects one-sided, malformed, duplicate, or ambiguous market inputs.
- Preserves the submitted market data as a timestamped reproducibility snapshot.
- Requires no sportsbook login, screenshot parsing, OCR, paid odds API, or API key.

## What the project does

The live pipeline:

1. Fetches the official MLB schedule for the selected date.
2. Captures probable pitchers, available starting lineups, venue, roof, weather, and game status.
3. Freezes schedule and pregame context into immutable timestamped snapshots.
4. Accepts user-entered two-way moneylines through the browser, terminal, CSV, or JSON.
5. Loads historical MLB team game logs.
6. Reconstructs canonical historical games and attaches official home/away identity when recoverable.
7. Builds pregame-only features without using information from the target game.
8. Fits seven winner-model components and a separate two-sided Poisson score model.
9. Runs the configured Monte Carlo score simulations and final probability draws.
10. Ranks games by confidence and model agreement.
11. Compares model probabilities with no-vig and raw market-implied probabilities.
12. Writes CSV, JSON, optional two-leg comparison, and immutable input artifacts.

The engine ends at prediction and market comparison. It does **not** recommend how much money to risk.

## Model stack

The active winner ensemble contains:

- Logistic regression
- Random forest
- Multilayer perceptron neural network
- Elo/Pythagorean baseline component
- XGBoost
- LightGBM
- CatBoost

Component weights are estimated from chronological calibration-slice Brier performance. Their weighted probability is calibrated and conservatively blended with the frozen V1 baseline. A separately trained two-sided Poisson model estimates expected runs for both teams. The live evaluator defaults to an 80/20 blend of the calibrated winner ensemble and score-model win probability.

For every evaluated game, the default run performs:

- **100,000 Poisson score simulations**
- **100,000 final Bernoulli probability draws**
- Optional **100,000-draw** two-leg top-pick comparisons under an explicit independence assumption

## Feature system

### Populated historical features

- Smoothed season winning percentage
- Pythagorean strength
- Runs scored and allowed per game
- Run differential
- Rolling 5-, 10-, and 20-game form
- Exponentially weighted offense, run prevention, and results
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

### Captured live context

- Official game identity and doubleheader number
- Scheduled start time and venue
- Probable starting pitchers
- Season pitcher ERA, WHIP, innings, FIP proxy, and K-minus-BB proxy when available
- Available official batting orders
- Lineup-confirmation status
- Temperature, condition, wind description, and roof status when supplied by the public feed

### Provider-ready but not fully historically trained

The schema supports advanced pitcher, lineup, bullpen, injury, defense, weather, park, umpire, travel, and market fields. When point-in-time historical coverage is unavailable, those fields remain neutral and receive missingness indicators rather than fabricated values.

A live snapshot recording a lineup or weather condition does **not** automatically mean the current fitted probability has a validated numerical response to that field. See [docs/DATA_AND_SNAPSHOTS.md](docs/DATA_AND_SNAPSHOTS.md) and [docs/VALIDATION.md](docs/VALIDATION.md).

## Quick start: local browser app

### Windows PowerShell

```powershell
cd sports-supermodel
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[ui,dev]"
sports-supermodel-ui
```

### macOS or Linux

```bash
cd sports-supermodel
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[ui,dev]"
sports-supermodel-ui
```

The command opens a local Streamlit page. In the browser:

1. Choose the slate date.
2. Click **Fetch official MLB slate**.
3. Enter both moneyline prices in the editable table.
4. Uncheck or leave both odds cells blank for games you want to skip.
5. Acknowledge the recreational-use notice.
6. Click **Run every model and simulate the slate**.
7. Review the confidence-first rankings and download CSV/JSON results.

Alternative launch command:

```bash
streamlit run app.py
```

The browser app runs locally on the user's computer. It does not require a hosted server, sportsbook account, or screenshot upload. Network access is still required for current public MLB data.

## Quick start: interactive terminal

Install the base project:

```powershell
python -m pip install -e ".[dev]"
```

Then run:

```powershell
sports-supermodel --date 2026-07-22 --interactive --simulations 100000
```

The program displays each official game and probable starters. Enter both sides of the moneyline, or press Enter at the away prompt to skip that game.

Decimal-odds entry:

```powershell
sports-supermodel --date 2026-07-22 --interactive --odds-format decimal
```

## Quick start: generated CSV or JSON template

Generate a blank official-slate template:

```powershell
sports-supermodel `
  --date 2026-07-22 `
  --template user_inputs\moneylines_2026-07-22.csv
```

Fill the `away_odds` and `home_odds` columns, then run:

```powershell
sports-supermodel `
  --date 2026-07-22 `
  --odds user_inputs\moneylines_2026-07-22.csv `
  --simulations 100000 `
  --top-n 5
```

The same workflow supports JSON:

```powershell
sports-supermodel `
  --date 2026-07-22 `
  --template user_inputs\moneylines_2026-07-22.json

sports-supermodel `
  --date 2026-07-22 `
  --odds user_inputs\moneylines_2026-07-22.json
```

See [docs/USER_INPUTS.md](docs/USER_INPUTS.md) for the complete schema and examples.

## Input file format

Minimal CSV:

```csv
game_date,game_pk,away_team,home_team,away_odds,home_odds,odds_format
2026-07-22,123456,ATH,AZ,111,-151,american
2026-07-22,123457,CIN,SEA,2.34,1.57,decimal
```

Minimal JSON:

```json
{
  "moneylines": [
    {
      "game_date": "2026-07-22",
      "game_pk": 123456,
      "away_team": "ATH",
      "home_team": "AZ",
      "away_odds": 111,
      "home_odds": -151,
      "odds_format": "american"
    }
  ]
}
```

Rules:

- `game_date`, `away_team`, `home_team`, `away_odds`, and `home_odds` are required for an included row.
- `game_pk` is strongly recommended and required for unambiguous doubleheaders.
- Both sides must be entered because no-vig market probabilities require a complete two-way line.
- A row with both odds blank is skipped.
- `include=false` or `enabled=false` skips a row.
- American input accepts `+125`, `-145`, `100`, `EVEN`, `EV`, or `PK`.
- Decimal input must be greater than 1.0.
- Extra template columns such as starters, weather, and game time are preserved for user reference and ignored by the market parser.

## Outputs

A live evaluation includes fields such as:

- `pick` and `pick_probability`
- away/home probabilities
- confidence rank
- model agreement count
- expected away and home runs
- score-simulation win probability
- no-vig market probability
- raw break-even probability
- edge versus no-vig and raw break-even probabilities
- model-implied fair American odds
- lineup-confirmation flag
- previous-game context
- each component model's team-oriented probability
- simulation count

No active output contains bankroll, stake, exposure, or Kelly fields.

## Repository layout

```text
.
├── .github/                CI workflow and contribution templates
├── config/                 Feature registry and validation gates
├── data/                   Historical team logs and source notes
├── docs/                   Architecture, inputs, validation, GitHub guide, history
├── examples/               Example CSV/JSON inputs and historical run scripts
├── reports/                Preserved validation and historical/live outputs
├── scripts/                Command wrappers and validation utilities
├── snapshots/              Immutable schedule, pregame, and market-input snapshots
├── src/supermodel/         Installable Python package
│   ├── cli.py              Terminal interface
│   ├── web_app.py          Local browser interface
│   ├── odds_input.py       CSV/JSON/interactive input and validation
│   ├── workflow.py         Shared end-to-end execution workflow
│   ├── live_mlb.py         Live capture and prediction evaluation
│   └── mlb_v2.py           Historical features and model stack
├── tests/                  Offline automated tests
├── app.py                  Streamlit entry point
├── DISCLAIMER.md           Recreational-use and gambling-risk notice
├── LICENSE                 MIT open-source license
└── pyproject.toml          Package, dependency, and command configuration
```

## Requirements

- Python 3.11 or newer
- Internet access for current public MLB capture
- Historical data under the configured `data` directory
- User-entered two-way moneylines
- Streamlit only when using the optional browser app

The historical and frozen-snapshot tests run without live network access.

## Installation details

Base CLI and model engine:

```bash
python -m pip install -e .
```

Browser interface:

```bash
python -m pip install -e ".[ui]"
```

Development tools:

```bash
python -m pip install -e ".[dev]"
```

Everything used by contributors:

```bash
python -m pip install -e ".[ui,dev]"
```

The seven-model release expects XGBoost, LightGBM, and CatBoost to install successfully. Do not silently describe a run as seven-model execution if a dependency was unavailable.

## CLI reference

```text
--date YYYY-MM-DD              Required slate date
--odds PATH                    Completed CSV or JSON input
--interactive                  Enter lines in the terminal
--template PATH                Generate blank official-slate CSV/JSON and exit
--odds-format FORMAT           american or decimal
--data-dir PATH                Historical team-log directory
--snapshot-dir PATH            Immutable artifact directory
--output-dir PATH              Evaluation report directory
--simulations INTEGER          Default 100000
--top-n INTEGER                Number of picks marked as top picks
--home-field-logit-adjustment  Experimental; keep at zero unless validated
--skip-parlays                 Skip optional two-leg comparison output
```

Exactly one of `--odds`, `--interactive`, or `--template` is required.

## Python API example

```python
from supermodel import (
    capture_official_slate,
    evaluate_captured_slate,
    moneylines_from_records,
)

captured = capture_official_slate(
    game_date="2026-07-22",
    snapshot_dir="runtime/snapshots",
)

moneylines = moneylines_from_records([
    {
        "game_date": "2026-07-22",
        "game_pk": captured.contexts[0].game_pk,
        "away_team": captured.contexts[0].away_team,
        "home_team": captured.contexts[0].home_team,
        "away_odds": "+111",
        "home_odds": "-151",
        "odds_format": "american",
    }
])

result = evaluate_captured_slate(
    captured_slate=captured,
    moneylines=moneylines,
    simulations=100_000,
)

print(result.evaluation[[
    "confidence_rank",
    "pick",
    "pick_probability",
    "model_overlap",
    "fair_odds",
]])
```

## Testing

```bash
pytest
```

The V2.3.3 release contains **31 passing tests** covering:

- Historical data construction
- Official game identity
- Doubleheader disambiguation
- Immutable schedule and pregame snapshots
- Post-start integrity checks
- Lineup, weather, and pitcher-stat parsing
- Score simulation behavior
- Confidence-first ranking
- Absence of active staking outputs
- American and decimal input parsing
- CSV and JSON input
- Blank-row skipping and incomplete-line rejection
- Official-slate template construction
- `gamePk`-based market matching

## Validation status

V2 remains experimental. On the preserved 1,101-game chronological comparison, the explicit-last-game V2.3 feature set produced:

| Metric | V2.3 |
|---|---:|
| Accuracy | 54.68% |
| Brier score | 0.24779 |
| Log loss | 0.68887 |
| AUC | 0.56480 |

V2.3.3 contains a schedule-integrity hotfix and retains the V2.3.2 input workflow; it does not claim a new predictive-performance improvement over the same V2.3 model. These results do not demonstrate profitability and are not a promise of future performance.

## Data-integrity principles

- Official MLB `gamePk` is the canonical identifier whenever available.
- Doubleheaders are not merged into one invented game.
- Ambiguous historical or user-input rows fail closed.
- Pregame snapshots are immutable and timestamped.
- Captures made after a scheduled start cannot be represented as valid pregame snapshots.
- Missing historical advanced data remains missing or neutral rather than being filled with hindsight.
- Model confidence is computed independently of price.
- User-entered odds are preserved separately from public MLB context.
- No screenshot OCR is required or used by the application.

## Known limitations

- Historical team logs do not contain every advanced point-in-time input supported by the schema.
- Starter features still include team-result proxies and are not a complete pitch-level projection system.
- Bullpen availability, individual batter projections, breaking injuries, weather, and roof decisions are not yet fully trained numerical inputs.
- Public feeds can be incomplete, delayed, revised, unavailable, or subject to provider terms.
- The project does not fetch sportsbook prices automatically; users must enter or import a lawful source of two-way odds.
- Original schedules may differ from later postponements or rescheduled games.
- Two-leg comparisons assume independent game outcomes.
- Probabilities can be miscalibrated, especially in small samples or regime changes.
- Market prices can move immediately after entry.
- A local browser interface is not the same as a hardened production web service. Do not expose it publicly without authentication, security, privacy, and legal review.

## Roadmap toward V2.4

Planned work includes:

- Walk-forward decay selection for the 1/3/5/10-game recent-form engine (multi-horizon features are now implemented on the V2.4 branch)
- Individual confirmed-lineup projections
- Pitcher-specific FIP/xFIP/SIERA/xERA and pitch-quality model
- Bullpen availability and leverage-usage model
- Weather, park, roof, travel, defense, and injury integration
- Category-level prediction attribution
- Improved calibration and prospective tracking
- Learned ensemble weighting under strict walk-forward validation

V2.4 should be developed on a separate branch and should not replace the stable V2.3.3 input release until it passes the repository's validation and data-integrity gates.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). New features should include:

- Point-in-time provenance
- Missingness behavior
- Leakage tests
- Chronological validation
- Input validation
- Updated documentation

## Security and privacy

The application does not need sportsbook credentials. Do not enter or commit account names, balances, cookies, tokens, passwords, private URLs, or personally identifying information. Generated user-input files and local market snapshots should be reviewed before committing.

For vulnerabilities or accidental exposure of private information, follow [SECURITY.md](SECURITY.md). Complete [docs/PUBLIC_RELEASE_CHECKLIST.md](docs/PUBLIC_RELEASE_CHECKLIST.md) before making the repository public.

## License

Released under the [MIT License](LICENSE). The license includes an “AS IS” warranty disclaimer and limitation of liability. The additional recreational-use and gambling-risk notice is in [DISCLAIMER.md](DISCLAIMER.md).

## Responsible use

Never treat a model probability as certainty. Do not chase losses, borrow to gamble, or risk money needed for essential expenses. In the United States, the National Problem Gambling Helpline can be reached by calling or texting **1-800-MY-RESET**. Users elsewhere should use an appropriate local support or self-exclusion service.

## V2.4 validation command

The V2.4 development branch includes a matched chronological comparison against the
frozen V2.3.3 feature contract:

```bash
sports-supermodel-validate
```

The ordinary command evaluates only development folds. The final holdout remains locked
unless `--unlock-holdout` is supplied after the candidate configuration is frozen. Reports
are written to `reports/v2_4_validation/`. See
`docs/V2_4_VALIDATION_FRAMEWORK.md` for methodology and promotion gates.

### V2.4 recent-form optimization

Run the leakage-safe recent-form ablation and exponential-decay comparison with:

```bash
sports-supermodel-optimize-form
```

The optimizer keeps the final holdout locked and writes generated evidence to `reports/v2_4_recent_form/`.
