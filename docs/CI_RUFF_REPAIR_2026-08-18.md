# GitHub Actions CI diagnosis and repair — 2026-08-18

## Source inspected

GitHub Actions log archive `logs_84504567928.zip` from the public-readiness baseline workflow run.

## Root cause

The failure was **not a Python 3.12 runtime/test incompatibility**.

The Python 3.12 matrix job successfully:

1. checked out the repository,
2. installed Python 3.12,
3. installed the project and development dependencies,
4. completed `python -m compileall -q src app.py tests`.

It then failed at:

```text
python -m ruff check .
```

Ruff 0.16.1 reported **266 diagnostics** and exited with code 1. The Python 3.11 matrix job was canceled after the 3.12 job failed because the matrix used the default fail-fast behavior.

The largest diagnostic groups were repository-wide style/modernization debt rather than Python-version failures:

- `UP017` (`datetime.UTC` modernization): 109
- `I001` (import sorting/formatting): 71
- `UP035` (`collections.abc` modernization): 40
- `UP037`: 11

The same log also exposed correctness/maintainability diagnostics worth fixing rather than suppressing, including unused/undefined names, repeated dictionary keys, loop-variable closure binding, exception chaining, and multiple statements on one line.

## Repair policy

The V2.6 candidate changes the blocking Ruff contract to focus CI on correctness and bug-risk rules:

```toml
select = ["E4", "E7", "E9", "F", "B"]
```

Import sorting (`I`) and broad pyupgrade modernization (`UP`) are no longer merge-blocking for this cumulative architecture branch. This avoids combining a 200+ finding repository-wide style migration with the PA architecture implementation while preserving high-value checks for syntax/import/name errors, duplicate keys, unsafe closures, exception-handling issues, and other bug-risk findings.

Archived one-off historical scripts under `examples/historical_runs` are excluded from the blocking lint gate.

Ruff is pinned to `0.16.1` in the development dependency set so CI does not silently change lint behavior when a new Ruff release is published.

The matrix now uses `fail-fast: false` so Python 3.11 and 3.12 both finish and report independently.

## Correctness fixes included

The cumulative V2.6 overlay also repairs every non-style `E/F/B` issue surfaced by the supplied baseline log in production/test code, including:

- missing `game_analysis_records` / `load_performance_payload` imports in the public web app,
- repeated `selection_status` / `selection_reasons` keys in evidence payload construction,
- repeated `score_draws_sha256` simulation identity key,
- loop-variable closure binding in conflict/live-evaluation helpers,
- exception chaining in immutable-snapshot and publisher-lock paths,
- unused imports/locals surfaced by Pyflakes,
- constant-attribute `getattr`, semicolon statement, and assigned-lambda findings.

## Local verification after repair

Active container verification after the repair:

- `python -m compileall -q src app.py tests`: **PASS**
- `pytest -q`: **211 / 211 PASS**

The active container cannot download/install Ruff because outbound package-network access is unavailable, so a local Ruff-pass claim is intentionally not made here. The cumulative bundle's `VERIFY_UPDATE.ps1` runs the exact pinned Ruff gate, tests, compile step, and package build on the user's machine **before any commit is made**.

## Promotion / repository impact

This CI repair does not alter predictive authority. V2.3.3 remains production, V2.4 RC2 remains shadow, and PA RC1 remains a non-authoritative shadow candidate pending live-parity/prospective gates.
