# V2.4 Phase 4 Validation Framework

Phase 4 replaces ad hoc validation commands with one matched, chronological comparison
between the frozen V2.3.3 predictive contract and the active V2.4 candidate.

## Matched baseline

V2.4 Phases 1 and 2 changed organization and reporting without changing predictions.
Phase 3 added the first predictive inputs: three-game form and three-versus-ten-game
momentum. The validation framework recreates V2.3.3 by removing only those Phase 3
fields before fitting the baseline model. Both versions therefore use:

- the same games and outcomes;
- the same chronological training cutoffs;
- the same seven model classes and random seed;
- the same calibration procedure;
- the same information available before each validation game.

This is a paired comparison, not a comparison between unrelated historical reports.

## Development windows and locked holdout

`config/validation_plan.yaml` defines the development folds. The holdout is stored in a
separate block and is not evaluated by an ordinary validation run. Opening it requires
the explicit `--unlock-holdout` flag. The candidate configuration should be frozen
before that flag is used.

The bundled 2026 data currently ends before the complete holdout period. Until the block
is complete, the holdout gate must remain pending.

## Metrics

The framework reports:

- accuracy;
- Brier score;
- log loss;
- ROC AUC;
- expected calibration error (ECE);
- maximum calibration error (MCE);
- prediction coverage;
- per-fold runtime;
- paired bootstrap confidence intervals;
- month, confidence-band, agreement, location, and data-status subgroups when available.

Lower Brier score, log loss, ECE, and MCE are better. Higher accuracy and AUC are better.

## Promotion report

`config/merge_gates.yaml` is evaluated automatically. A gate can be:

- `PASS`: the observed result satisfies the requirement;
- `FAIL`: the observed result violates the requirement;
- `PENDING`: required release evidence does not yet exist.

A pending gate is not a pass. Retrospective improvement alone cannot promote V2.4.
The final holdout, point-in-time provenance, schedule integrity, leakage protection,
prospective sample, and closing-line tracking remain separate release requirements.

## Command

```bash
sports-supermodel-validate
```

Equivalent source-tree command:

```bash
python scripts/run_v2_4_validation.py
```

A faster development smoke run can reduce only the bootstrap count:

```bash
sports-supermodel-validate --bootstrap-iterations 200
```

Do not unlock the holdout during ordinary feature development.

## Output

The default directory is `reports/v2_4_validation/` and contains:

- `walk_forward_predictions.csv`;
- `walk_forward_folds.csv`;
- `calibration.csv`;
- `subgroup_metrics.csv`;
- `summary.json`;
- `promotion_gates.json`;
- `VALIDATION_REPORT.md`.

Each report includes version, commit, data-range, runtime, and data-fingerprint metadata.
