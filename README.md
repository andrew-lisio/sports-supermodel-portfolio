# Sports SuperModel

> **V2.4 implementation status:** RC2 lives on `v2.4-live-freshness-fix`, with V2.3.3 still anchored on `main`. RC2 automatically refreshes official completed games through the prior day, fails closed rather than using stale history, and removes ensemble/consensus conflicts from the top-pick list. Promotion remains `PENDING` until prospective, CLV, integrity, provenance, calibration, and final-holdout gates pass.


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
8. Runs frozen V2.3.3 production and the exact V2.4 candidate as separately versioned seven-model tracks.
9. Runs the configured Monte Carlo score simulations and final probability draws for both tracks.
10. Keeps production rankings primary and attaches V2.4 shadow probabilities, disagreements, and candidate commit.
11. Compares model probabilities with no-vig and raw market-implied probabilities.
12. Writes CSV, JSON, optional two-leg production comparison, immutable inputs, and prospective evidence.

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
- Posted-lineup public season aggregates with explicit player coverage
- Recent reliever pitches/innings and bounded fatigue/availability proxies
- Public team pitching and fielding proxies
- Recent venue distance, time-zone movement, rest, and schedule-density travel proxy

### Provider-ready but not fully historically trained

The schema supports advanced pitcher, lineup, bullpen, injury, defense, weather, park, umpire, travel, and market fields. When point-in-time historical coverage is unavailable, those fields remain neutral and receive missingness indicators rather than fabricated values.

A live snapshot recording a lineup or weather condition does **not** automatically mean the current fitted probability has a validated numerical response to that field. See [docs/DATA_AND_SNAPSHOTS.md](docs/DATA_AND_SNAPSHOTS.md) and [docs/VALIDATION.md](docs/VALIDATION.md).

## Shared hosted storage

Local file mode remains the default. Platform Foundation Post7 also supports PostgreSQL for shared
structured state and S3-compatible storage for score draws, reports, and raw provider artifacts.
Install the storage dependencies and inspect configuration with:

```powershell
python -m pip install --upgrade -e ".[ui,dev,storage]"
sports-supermodel-storage status
```

After setting `SPORTS_SUPERMODEL_STORAGE_BACKEND=postgres` and `DATABASE_URL`, apply the idempotent
schema migrations with:

```powershell
sports-supermodel-storage migrate
```

Credentials are environment variables and must never be committed. Full configuration is documented
in [docs/SHARED_STORAGE.md](docs/SHARED_STORAGE.md).

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

The command opens the read-only site experience. Public-facing pages display the latest simulation snapshots already published by the backend; visiting or changing pages never trains models or launches Monte Carlo work. The browser exposes four initial views:

- **Today’s Slate** — the latest published V2.3.3 production snapshots for the selected date;
- **High Probability** — outcomes ranked by raw modeled hit probability, independent of price;
- **Best Value** — the complete Top 5 rebuilt from one global sportsbook selector;
- **Line Checker** — a custom moneyline, run line, game total, or team total evaluated against the latest saved simulation distribution, including fair odds and a conservative playable-through price.

Until the scheduled simulation publisher is connected, local developers may explicitly enable the temporary manual publisher before launching the app:

```powershell
$env:SPORTS_SUPERMODEL_ENABLE_MANUAL_RUN = "1"
sports-supermodel-ui
```

That adds an **Admin Run** page for local testing. It is hidden by default and is not part of the intended public user flow. Each completed admin or future scheduled run persists the full 100,000-draw away/home score distributions for both production and shadow tracks, together with authoritative blended moneyline probabilities and captured market quotes.

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
- persistent production and shadow simulation-manifest paths
- persistent canonical market-quote history
- push-aware fair odds, expected ROI, and playable-through prices for supported markets

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
├── runtime/                Incremental data, quote history, and compressed simulations
├── src/supermodel/         Installable Python package
│   ├── cli.py              Terminal interface
│   ├── web_app.py          Local browser interface
│   ├── odds_input.py       CSV/JSON/interactive input and validation
│   ├── workflow.py         Shared execution and persistent snapshot workflow
│   ├── market_store.py     Append-only canonical quote history
│   ├── platform_views.py   High Probability, Best Value, and Line Checker services
│   ├── simulation_store.py Compressed score-distribution snapshots
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

## Point-in-time starting-pitcher collection

The V2.4 final candidate freezes the exact public season-stat payload for each posted
probable starter before first pitch. The immutable snapshot is keyed by official `gamePk`,
side, and MLB person ID, and is bound into prospective prediction evidence.

```bash
sports-supermodel-starters audit
sports-supermodel-starters export
```

The export is a future-training dataset. Starter and other advanced context may influence
only the separately versioned adaptive V2.4 shadow overlay after its chronological
activation gate passes; they do not rewrite the frozen retrospective contract. See
`docs/V2_4_FINAL_CANDIDATE.md`.

## Known limitations

- Historical team logs do not contain every advanced point-in-time input supported by the schema.
- Starter features still include team-result proxies and are not a complete pitch-level projection system.
- Public lineup, bullpen, weather, fielding, and travel context is captured prospectively, but its adaptive numerical influence remains self-gated until chronological evidence passes.
- Complete Statcast pitch quality, projected injury WAR, FRV/OAA, catcher framing, and umpire factors still require trustworthy point-in-time providers.
- Public feeds can be incomplete, delayed, revised, unavailable, or subject to provider terms.
- The project does not fetch sportsbook prices automatically; users must enter or import a lawful source of two-way odds.
- Original schedules may differ from later postponements or rescheduled games.
- Two-leg comparisons assume independent game outcomes.
- Probabilities can be miscalibrated, especially in small samples or regime changes.
- Market prices can move immediately after entry.
- A local browser interface is not the same as a hardened production web service. Do not expose it publicly without authentication, security, privacy, and legal review.

## V2.4 release-candidate boundary

The final candidate implements the repository-side V2.4 roadmap in one squashed commit:
accelerated seven-model execution, selected recent-form behavior, attribution, immutable
prospective evidence, starter and advanced point-in-time collection, production/shadow
dual execution, and a fail-closed prospective adaptive overlay. See
[docs/V2_4_FINAL_CANDIDATE.md](docs/V2_4_FINAL_CANDIDATE.md).

Unavailable point-in-time sources—such as complete Statcast pitch-quality history, projected
injury WAR, FRV/OAA, catcher framing, and umpire factors—remain provider-ready and neutral
rather than being fabricated. V2.4 cannot replace stable V2.3.3 until its prospective and
locked-holdout promotion gates pass.

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

The current frozen V2.4 candidate is `phase3_full_alpha_025`: 3/5/10/20-game windows, momentum and previous-game context enabled, and EWM alpha `0.25`. V2.3.3 remains separately reconstructed with alpha `0.18` during matched validation. See `docs/V2_4_SELECTED_RECENT_FORM.md`.


### V2.4 opponent-adjusted recent-form ablation

Run the point-in-time opponent-strength adjustment experiment with:

```bash
sports-supermodel-optimize-opponent-form
```

This compares the frozen V2.4 alpha-0.25 contract against several opponent-adjusted rolling-window variants on the same chronological development games. The final holdout remains locked, and opponent adjustment is not activated unless it clears the configured probability-quality and regression gates. See `docs/V2_4_OPPONENT_ADJUSTED_FORM.md`.

### V2.4 accelerated integration

The final `v2.4-final-candidate` branch includes CPU-budgeted parallel execution for the
complete seven-model ensemble, matched validation, and candidate experiments. It preserves
the frozen feature contracts and locked holdout. See `docs/V2_4_FINAL_CANDIDATE.md` and
inspect the runtime model registry with:

```bash
sports-supermodel-registry
```

Audit the append-only prospective evidence ledger:

```powershell
sports-supermodel-evidence audit
```

Audit whether the provisional conflict gate is improving the surfaced recommendation set
without hiding the raw predictions:

```powershell
sports-supermodel-conflicts
```

The conflict audit reports helpful passes, false passes, accepted-pick accuracy, coverage,
and performance by exact trigger. It does not automatically retune thresholds. See
`docs/V2_4_CONFLICT_FILTER_AUDIT.md`.

Audit which captured live features actually have prediction authority:

```powershell
sports-supermodel-features audit
```

The audit distinguishes historically trained signal, direct bounded score proxies,
prospective adaptive-only context, and capture-only evidence fields. See
`docs/FEATURE_AUTHORITY_AUDIT.md`.

Build the leakage-safe historical starter/bullpen context dataset for RC3 development:

```powershell
sports-supermodel-pitching backfill --start-date 2026-03-25 --end-date 2026-07-28
sports-supermodel-pitching audit
```

The generated pitching dataset is development input only until matched chronological
validation clears an activation gate; RC2 probabilities remain unchanged by merely
creating the file.

See `docs/V2_4_PHASE6B_EVIDENCE_PIPELINE.md` for closing-line, outcome, provenance, and
validation-gate workflows.

### V2.4 production/shadow and adaptive status

A normal live run keeps V2.3.3 in the primary output columns and adds V2.4 fields with a
`shadow_` prefix. Inspect the self-gated prospective overlay with:

```bash
sports-supermodel-adaptive show
```

The overlay cannot alter V2.4 until enough graded prospective games exist and its
chronological activation test passes. No background predictions occur while the program is
not running.

## Platform foundation (development)

The `v2.4-platform-foundation` branch adds backend services for the planned public site:
canonical multi-book markets, custom-line pricing, playable-through prices, persistent simulation
distributions, High Probability rankings, Best Value rankings, and a unified supported-data
refresh command.

```powershell
sports-supermodel-refresh --date 2026-07-31
```

The refresh command currently updates completed-game history and point-in-time pitching context.
Lineup/roster, weather, and licensed sportsbook provider slots remain explicitly unconfigured and
are reported as `PENDING_PROVIDER`; the program does not claim to refresh them yet.

The backend publication worker is separate from the public website:

```powershell
sports-supermodel-publish --date 2026-07-31
```

It captures the official pregame slate, detects which baseball inputs materially changed, and runs
the canonical production/shadow simulations only for those games. It does not persist synthetic
prices or betting evidence. Re-running it with unchanged inputs returns `SKIPPED_UNCHANGED`, while
sportsbook-only price movement is handled by the pricing layer without another simulation.
