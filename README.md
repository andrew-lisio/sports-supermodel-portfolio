# Sports SuperModel

> **Development branch target:** `v2.6-pa-generative-integration`  
> **Package:** `2.6.0.dev1+pa.generative.integration`  
> **Production authority:** V2.3.3 remains production; V2.4 RC2 and the PA simulator remain shadow-only until explicit promotion.

Sports SuperModel is an end-to-end **MLB probabilistic forecasting, simulation, and market-analysis platform**. It combines a seven-model winner ensemble, chronological calibration, immutable point-in-time data capture, Monte Carlo simulation, automatic settlement/performance reporting, and a dormant hosted-application foundation.

The newest development track adds a **generative plate-appearance (PA) simulator** that builds complete baseball games from statistically estimated PA outcomes instead of drawing final scores around a predetermined expected score. Projected score, totals, run lines, team totals, shutout/blowout probabilities, and extra-inning rates are downstream outputs of the simulated games.

## Why this project is technically interesting

- **Seven-model ensemble:** logistic regression, random forest, neural network, Elo/Pythagorean, XGBoost, LightGBM, and CatBoost.
- **Point-in-time discipline:** historical and live features are frozen before first pitch; missing information fails closed or remains explicitly neutral rather than using hindsight.
- **Generative baseball simulation:** complete PA-by-PA games with inning/outs/base state, batting order, starter workload, bullpen phase, extra innings, automatic runners, and walk-offs.
- **Probability quality over headline accuracy:** Brier score, log loss, calibration, chronological holdouts, and tail-distribution realism are first-class validation targets.
- **Market comparison:** converts model probabilities into fair prices and compares them with user-supplied sportsbook lines without stake sizing or bankroll automation.
- **Production engineering:** immutable snapshots, reproducible artifacts, settlement/CLV reporting, optional PostgreSQL/S3 storage, separated services, and a dormant public deployment framework.

## Current architecture and governance

```text
Official/pregame MLB data + historical point-in-time state
                    │
                    ├── Seven-model winner ensemble
                    │       └── V2.3.3 production / V2.4 RC2 shadow
                    │
                    └── Simulation layer
                            ├── Incumbent Poisson engine (production)
                            └── PA generative RC1 (shadow candidate)
                                      │
                                      ├── win probability
                                      ├── projected score
                                      ├── totals / team totals
                                      ├── run-line distributions
                                      └── tail probabilities
```

The PA simulator is **implemented but not silently promoted**. Historical evidence supports it as the preferred score-distribution architecture, while its optimal moneyline influence remains intentionally conservative and configurable. Production behavior stays unchanged until fresh live-parity and prospective operational gates pass.

## Historical PA validation snapshot

Canonical testing used a **locked 1,972-game 2025 holdout** after development on 2024 point-in-time data. Each game used only information available before that game.

| Engine | Winner accuracy | Brier ↓ | Log loss ↓ | Team-run MAE ↓ | Total MAE ↓ | Run-diff MAE ↓ |
|---|---:|---:|---:|---:|---:|---:|
| Frozen Poisson | 54.06% | 0.247568 | 0.688263 | 2.5112 | **3.6095** | 3.5335 |
| Inning generative | 53.70% | 0.251952 | 0.698752 | 2.5485 | 3.6875 | 3.5434 |
| **PA generative** | **54.46%** | **0.245055** | **0.683124** | **2.5104** | 3.6097 | **3.5327** |

The largest PA gain was **distribution realism**, not a claim that mean final scores became easy to predict. On the same holdout, PA reduced absolute error versus actual MLB frequencies for shutouts, 10+ run team games, 15+ run games, 5+ run blowouts, and one-run games by large margins relative to the incumbent Poisson engine. Ten-bin calibration error was **0.0098 for PA vs. 0.0450 for Poisson**.

See [`docs/PA_GENERATIVE_SIMULATOR.md`](docs/PA_GENERATIVE_SIMULATOR.md) and [`docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md`](docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md) for architecture, methodology, limitations, and promotion rules.

## Important notice

This software is provided solely for **recreational, educational, statistical, and research use**. It is not financial, investment, legal, gambling, fiduciary, or other professional advice. It is not a sportsbook, does not place wagers, and does not guarantee accuracy, outcomes, or profit. Sports outcomes are uncertain, data may be incomplete or wrong, and model probabilities may be materially miscalibrated.

Anyone who chooses to gamble does so voluntarily and assumes the entire risk of loss. Users are responsible for legal-age requirements, local laws, taxes, sportsbook terms, and independent verification of every input. Read [DISCLAIMER.md](DISCLAIMER.md) before using, publishing, or distributing the project. No disclaimer can guarantee immunity from a lawsuit or regulatory inquiry; obtain jurisdiction-specific advice from a qualified attorney before marketing, monetizing, or operating the project for others.

## What changed in the V2.6 PA integration candidate

This branch is a **single cumulative development milestone** above the preserved public-readiness rollback baseline. It adds the historically validated PA simulator as a third, non-authoritative shadow track while preserving the existing production and V2.4 RC2 paths.

Key additions:

- Complete PA-by-PA generative simulator with no predetermined projected-score input.
- Reproducible 2024 empirical PA/base-out prior builder and packaged prior artifact.
- Fail-closed live PA adapter requiring official game identity, confirmed starters, confirmed nine-player lineups, immutable advanced pregame state, and sufficient hitter coverage.
- Active-roster reliever-only season-profile capture for bullpen event rates, with explicit all-staff fallback labeling.
- Shadow-only CLI flags: `--pa-shadow`, `--pa-shadow-weight`, and `--pa-shadow-simulations`.
- Separate PA CSV/JSON/simulation artifacts with `production_authority=false` persisted in metadata.
- Historical validation documentation and regression coverage for PA simulation, prior generation, live adaptation, and selection-policy behavior.
- Existing fixed projected-score conflict logic remains unchanged for production but is disabled for PA shadow because historical ablation did not show benefit from double-counting the PA score direction.

The candidate does **not** claim that 70–80% PA moneyline influence is proven optimal. The default PA moneyline weight remains a conservative **20% in shadow only** while live parity and prospective sanity checks continue.

## What the project does

The live pipeline:

1. Fetches the official MLB slate and captures game identity, probable pitchers, lineups, venue/roof/weather, roster state, and other available pregame context.
2. Freezes source payloads and normalized pregame context into immutable, timestamped snapshots.
3. Accepts user-entered two-way moneylines through the browser, terminal, CSV, or JSON; the input line is preserved separately from baseball context.
4. Refreshes completed MLB history through the prior day and fails closed rather than silently using stale history.
5. Builds pregame-only features and runs the seven-model V2.3.3 production track and V2.4 RC2 shadow track separately.
6. Runs the incumbent production score simulator and, when explicitly enabled, the PA generative shadow simulator.
7. Derives probabilities, projected scores, market distributions, fair prices, overlap/disagreement diagnostics, and abstention reasons.
8. Persists prediction artifacts, simulation draws, manifests, market snapshots, provenance, and prospective evidence.
9. Supports automatic settlement, CLV/performance reporting, candidate promotion gates, and read-only publication workflows.
10. Keeps production authority explicit: experimental shadow outputs cannot silently alter production recommendations.

The engine ends at prediction, simulation, and market comparison. It does **not** place wagers, size stakes, manage bankrolls, or guarantee profitability.

## Model stack

### Winner ensemble

The active seven-model winner ensemble contains:

- Logistic regression
- Random forest
- Multilayer perceptron neural network
- Elo/Pythagorean baseline component
- XGBoost
- LightGBM
- CatBoost

Component probabilities are combined and calibrated using chronological validation logic. V2.3.3 remains the production identity; V2.4 RC2 is a separately versioned shadow candidate.

### Simulation engines

**Production:** a separately trained two-sided Poisson score model estimates expected runs and generates score distributions. The existing live evaluator retains its incumbent ensemble/score blend until a replacement is explicitly promoted.

**PA generative shadow:** `pa-generative-shadow-rc1` simulates complete games plate appearance by plate appearance. It maintains inning/half, outs, base state, batting-order position, pitcher phase/workload, score, extras, automatic runner, and walk-off state. It does **not** accept expected final runs as an anchor; score and market distributions emerge from the simulated games.

The default live run still uses **100,000 simulations per game/track** where enabled. PA shadow has zero production authority and a configurable, conservative 20% moneyline blend for operational testing.

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

## Dormant public-deployment framework

The repository includes framework for a future hosted website, but it is deliberately inactive by
default. No public service starts unless the user later enables the explicit deployment gate.
Local commands and the private/local slate workflow remain unchanged.

```powershell
sports-supermodel-public status
sports-supermodel-public plan
sports-supermodel-public readiness
```

See [docs/PUBLIC_READINESS_FOUNDATION.md](docs/PUBLIC_READINESS_FOUNDATION.md).

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
python -m compileall -q src app.py tests
python -m ruff check .
python -m pytest
python -m build
```

The V2.6 PA integration candidate currently contains **211 passing repository tests** in the verified local candidate environment. Coverage includes the original data/model/workflow suite plus PA-specific tests for:

- PA event-probability normalization and complete-game state transitions
- Empirical prior reconstruction and package-resource integrity
- Starter/lineup fail-closed requirements
- Reliever-only bullpen-profile capture and explicit fallback behavior
- PA shadow selection-policy behavior
- Simulation persistence and non-authoritative metadata
- Existing V2.3.3/V2.4 production-shadow regression behavior

The previously unresolved GitHub Actions failure has now been diagnosed from the original workflow log: Python 3.12 installation and compilation succeeded, and the job failed at the Ruff lint gate rather than from a Python 3.12 model/runtime incompatibility. V2.6 includes the corresponding correctness cleanup, a reproducible pinned Ruff gate, and non-fail-fast 3.11/3.12 matrix execution. Remote CI still must be rerun after this branch is pushed before a green-workflow claim is made. See [`docs/CI_RUFF_REPAIR_2026-08-18.md`](docs/CI_RUFF_REPAIR_2026-08-18.md).

## Validation status

The project remains experimental and intentionally separates **historical evidence**, **shadow candidates**, and **production authority**.

### PA simulator architecture decision

The canonical 2024-development / locked-2025-holdout reproduction selected the PA simulator over the inning-level candidate for score-distribution architecture. PA materially improved calibration and tail realism while maintaining comparable mean-score error. PA-vs-Poisson probability-quality point estimates were favorable but not statistically decisive enough to justify aggressive moneyline authority.

Therefore:

- **PA score-distribution architecture:** implementation candidate **PASS**
- **Inning simulator:** **REJECTED** as the primary replacement candidate
- **PA moneyline weight:** **INCONCLUSIVE / conservative shadow-only setting**
- **V2.3.3 production:** unchanged
- **V2.4 RC2:** shadow only
- **Poisson production simulator:** unchanged until explicit promotion

These results do not demonstrate profitability and are not a promise of future performance.

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

- Historical team logs do not contain every advanced point-in-time input supported by the live schema.
- PA RC1 requires confirmed lineups/starters and sufficient individual-player coverage; it fails closed rather than inventing missing hitter inputs.
- Recent bullpen fatigue and closer-availability fields are captured but remain diagnostic-only for PA RC1 because no historical effect-size adjustment has yet earned inclusion.
- PA historically improved full score-distribution realism, but exact final-score prediction remains inherently noisy; the displayed projected score is a simulation mean, not a literal exact-score claim.
- The historically favored 70–80% PA moneyline-weight region was not statistically decisive against the incumbent Poisson blend; production authority therefore remains conservative and unchanged.
- Complete Statcast pitch quality, projected injury WAR, FRV/OAA, catcher framing, and umpire factors still require trustworthy point-in-time providers before they can become validated predictive inputs.
- Public feeds can be incomplete, delayed, revised, unavailable, or subject to provider terms.
- Private-book or unsupported prices require user input or an authorized odds provider; no line is fabricated when a provider fails.
- Market prices can move immediately after entry.
- A local browser interface is not the same as a hardened production web service. The hosted framework remains dormant until explicitly enabled and reviewed.

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
