# Sports SuperModel

**MLB probabilistic forecasting, generative simulation, and market-analysis platform**

Sports SuperModel is an end-to-end baseball analytics system that combines a seven-model winner ensemble, chronological validation, immutable point-in-time data capture, Monte Carlo simulation, and a plate-appearance (PA) generative game simulator. The project is built around a strict separation between **production**, **shadow**, and **experimental** model authority so new ideas can be tested without silently changing live behavior.

> **Current development package:** `2.6.0.dev1+pa.generative.integration`  
> **Production authority:** V2.3.3  
> **Shadow tracks:** V2.4 RC2 + PA generative RC1  
> **Default live simulation scale:** 100,000 simulated games per enabled track

## Technical highlights

- **Seven-model winner ensemble:** logistic regression, random forest, multilayer perceptron, Elo/Pythagorean, XGBoost, LightGBM, and CatBoost.
- **Generative baseball simulation:** complete PA-by-PA games with batting order, outs, base state, starter workload, bullpen phase, extra innings, automatic runners, and walk-offs.
- **Point-in-time validation:** historical features are constructed using only information available before each game; chronological and out-of-year holdouts are preferred over random train/test splits.
- **Probability-quality evaluation:** Brier score, log loss, calibration, accuracy, run-distribution error, and tail behavior are tracked separately.
- **Immutable evidence:** pregame schedule/context snapshots, model identities, seeds, inputs, and output manifests are designed for reproducibility and later settlement.
- **Market comparison:** model probabilities are converted into fair American odds and compared with user-entered market prices; the active engine does not size wagers or manage bankrolls.
- **Production engineering:** CLI + Streamlit entry points, optional API/service separation, PostgreSQL/S3-ready storage abstractions, scheduled publication infrastructure, Docker support, tests, and GitHub Actions.

## Architecture

```text
Official / approved pregame data
            │
            ├── Point-in-time feature pipeline
            │         │
            │         └── Seven-model winner ensemble
            │                 ├── V2.3.3 production
            │                 └── V2.4 RC2 shadow
            │
            └── Simulation layer
                      ├── Poisson score engine (production)
                      └── PA generative RC1 (shadow)
                                │
                                ├── win probability
                                ├── projected score
                                ├── totals / team totals
                                ├── run-line distributions
                                ├── shutout / blowout tails
                                └── extra-inning probability
```

The PA simulator is intentionally **downstream-first**: it does not receive a predetermined final-score prediction and then add random noise around it. Game state evolves one plate appearance at a time, and the final score emerges from the completed simulations.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/PA_GENERATIVE_SIMULATOR.md`](docs/PA_GENERATIVE_SIMULATOR.md).

## Historical PA validation

The canonical PA architecture test used 2024 as the development period and a **locked 1,972-game 2025 holdout**. Same-date state was captured before that date's results were applied.

| Engine | Winner accuracy | Brier ↓ | Log loss ↓ | Team-run MAE ↓ | Total MAE ↓ | Run-diff MAE ↓ |
|---|---:|---:|---:|---:|---:|---:|
| Frozen Poisson | 54.06% | 0.247568 | 0.688263 | 2.5112 | **3.6095** | 3.5335 |
| Inning generative | 53.70% | 0.251952 | 0.698752 | 2.5485 | 3.6875 | 3.5434 |
| **PA generative** | **54.46%** | **0.245055** | **0.683124** | **2.5104** | 3.6097 | **3.5327** |

The strongest PA improvement was distribution realism rather than a claim that exact baseball scores became easy to forecast. On the same holdout:

- 10-bin ECE: **0.0098 PA vs. 0.0450 Poisson**
- Exact-score negative log likelihood: **4.8337 PA vs. 5.1637 Poisson**
- Shutout, 10+ team-run, 15+ game-run, 5+ run blowout, and one-run frequencies were all materially closer to actual MLB frequencies than the frozen Poisson benchmark.

The paired PA-vs-Poisson Brier/log-loss confidence intervals narrowly crossed zero, so the repository **does not claim statistically proven superiority for standalone moneyline probability**. The PA architecture is promoted to implementation candidate because its game-state mechanics and distributional realism were stronger; production moneyline authority remains unchanged.

Full methodology: [`docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md`](docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md).

## PA generative simulator

Each plate appearance samples from an estimated event distribution over:

```text
K | BB | HBP | 1B | 2B | 3B | HR | REACH | OUT
```

The simulator maintains:

- inning and half-inning
- outs and occupied bases
- batting-order position
- starter / bullpen phase
- pitcher workload state
- score and walk-off state
- extra innings and automatic runner behavior

The packaged empirical prior was built from **182,449 effective 2024 PA transitions across 216 base/out states**. Fixed random seeds and explicit simulator metadata make runs reproducible.

The live PA adapter fails closed when required pregame inputs are missing. Confirmed starters and complete nine-player lineups are required before the candidate is allowed to run with full parity labeling.

## Winner-model stack

The active winner ensemble contains:

1. Logistic regression
2. Random forest
3. Neural network
4. Elo/Pythagorean component
5. XGBoost
6. LightGBM
7. CatBoost

The system persists component-level probabilities so overlap and disagreement can be inspected rather than exposing only a single opaque probability.

## Validation principles

Sports SuperModel uses several rules intended to reduce hindsight and leakage:

- features for a game are computed before that game's result updates historical state;
- same-day results are not allowed to leak into earlier same-date predictions;
- chronological development/holdout splits are preferred;
- experimental features remain neutral when point-in-time provenance is unavailable;
- model identity, source cutoffs, seeds, and artifacts are persisted;
- conflict filters abstain rather than flipping a model pick to the opponent;
- shadow models cannot silently replace production authority.

See [`docs/VALIDATION.md`](docs/VALIDATION.md) and [`docs/FEATURE_AUTHORITY_AUDIT.md`](docs/FEATURE_AUTHORITY_AUDIT.md).

## Repository layout

```text
src/supermodel/          Core models, live pipeline, simulation, storage, API and CLI logic
tests/                   Unit / regression tests
config/                  Validation, evidence, feature and execution configuration
docs/                    Architecture, validation, data and operational documentation
docs/validation/         Canonical PA validation artifacts and reports
docs/history/            Archived engineering history
reports/                 Shareable historical validation summaries
examples/                Sanitized example market-input formats
data/                    Public data policy only; private/copied season caches are excluded
deploy/                  Dormant deployment/service scripts
.github/workflows/       Python 3.11 / 3.12 CI
```

Private sportsbook screenshots, account metadata, user balances/credit, generated live recommendations, and copied third-party season caches are intentionally excluded from the public portfolio snapshot.

## Quick start: tests and code review

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

The test suite uses controlled fixtures and does not require the private season-history cache.

## Live/local execution

The full live workflow requires an approved historical input directory plus current pregame data. Private development data is deliberately not bundled in this portfolio repository.

Useful entry points include:

```text
sports-supermodel               Main slate evaluation CLI
sports-supermodel-ui            Streamlit interface
sports-supermodel-history       Historical freshness workflow
sports-supermodel-registry      Model/version registry inspection
sports-supermodel-evidence      Prospective evidence utilities
sports-supermodel-publish       Publication workflow
sports-supermodel-settle        Result settlement
sports-supermodel-public        Dormant public-readiness controls
```

Run any command with `--help` for its current interface.

## Production / shadow governance

| Track | Role | Production authority |
|---|---|---|
| V2.3.3 | Current winner-model production path | **Yes** |
| V2.4 RC2 | Candidate winner-model shadow | No |
| Poisson simulator | Incumbent score-distribution engine | **Yes** |
| PA generative RC1 | Generative simulation candidate | No |

The default PA moneyline blend remains conservative and configurable in shadow. A historical development optimum at a much larger PA weight was **not** treated as sufficient evidence for production promotion because the locked-holdout improvement versus the incumbent blend was statistically inconclusive.

## Public deployment foundation

The repository contains a dormant hosted-application foundation for separated web/API, odds ingestion, publication, settlement, shared storage, backup/restore, and health/readiness workflows. These components are intentionally disabled by default and are not evidence that a public production service is currently running.

See [`docs/PUBLIC_READINESS_FOUNDATION.md`](docs/PUBLIC_READINESS_FOUNDATION.md).

## Data, privacy, and attribution

This portfolio snapshot is code-first:

- private market screenshots and account metadata are not included;
- runtime/user-entered market files are ignored;
- copied season datasets with unverified redistribution permission are not bundled;
- the PA prior is a derived statistical artifact built from historical play-by-play;
- raw provider captures belong in local/runtime storage rather than public Git history.

Third-party source policy and attribution are documented in [`NOTICE.md`](NOTICE.md) and [`docs/THIRD_PARTY_DATA.md`](docs/THIRD_PARTY_DATA.md).


## Development and attribution

Created and maintained by **Andrew Lisio**. The project was developed through an AI-assisted engineering workflow: historical commits attributed to OpenAI reflect AI-assisted implementation work, while system architecture, modeling direction, validation criteria, integration decisions, testing, and production/shadow governance were directed and reviewed by the project maintainer.

## Responsible use

This project is for statistical, educational, research, and portfolio purposes. It is not a sportsbook, does not place wagers, and does not guarantee accuracy, outcomes, or profit. Sports outcomes are uncertain and all model outputs can be wrong or miscalibrated.

See [`DISCLAIMER.md`](DISCLAIMER.md).

## Source-use terms

This public portfolio is **source-available, not open source**. No open-source license is granted. Review [`COPYRIGHT.md`](COPYRIGHT.md) before copying or reusing project code. GitHub's platform terms still apply to public repositories.

## Documentation

Start with:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/PA_GENERATIVE_SIMULATOR.md`](docs/PA_GENERATIVE_SIMULATOR.md)
- [`docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md`](docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md)
- [`docs/VALIDATION.md`](docs/VALIDATION.md)
- [`docs/DATA_AND_SNAPSHOTS.md`](docs/DATA_AND_SNAPSHOTS.md)
- [`docs/PUBLIC_RELEASE_CHECKLIST.md`](docs/PUBLIC_RELEASE_CHECKLIST.md)

Historical development reports remain available under `docs/history/` so the root stays focused on the current architecture.

## Data Attribution

Historical plate-appearance and game-state research used Retrosheet data.

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.

Additional third-party information is documented in [NOTICE.md](NOTICE.md).
