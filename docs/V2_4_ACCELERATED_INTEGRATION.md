# V2.4 Accelerated Integration

This branch integrates CPU-budgeted parallel execution without changing the frozen
V2.4 feature contract, the seven model definitions, chronological cutoffs, calibration
procedure, selection thresholds, or locked holdout policy.

## What is accelerated

- The seven independent winner-model components fit and predict concurrently.
- Matched V2.3.3 baseline and V2.4 candidate fits may run concurrently per fold.
- Recent-form and opponent-adjusted-form candidate experiments may evaluate two
  candidates concurrently.
- Native estimator thread counts remain bounded to prevent nested oversubscription.

The canonical model order is registered in `supermodel.model_registry`:

1. Logistic Regression
2. Random Forest
3. Neural Network
4. Elo / Pythagorean
5. XGBoost
6. LightGBM
7. CatBoost

The runtime fails closed when any component is missing, unexpected, or reordered.
Inspect the active registry with:

```bash
sports-supermodel-registry
```

## Execution profiles

`config/execution.yaml` contains:

- `accelerated`: CPU-aware model, comparison, and candidate parallelism;
- `serial`: one worker at every level for equivalence checks and debugging.

Validation example:

```bash
sports-supermodel-validate --profile accelerated
```

Serial equivalence check:

```bash
sports-supermodel-validate --profile serial --bootstrap-iterations 200
```

A total worker budget can be imposed with `--workers N`. Worker allocation is written
into generated report metadata.

## Release constraints

This integration does not promote V2.4. The final holdout remains locked during
ordinary development, and all prospective, point-in-time provenance, schedule
integrity, leakage, closing-line, calibration, and regression gates remain required.
The active branch is `v2.4-accelerated-integration`; `v2.4-development` remains the
rollback point and `main` remains the V2.3.3 production baseline.
