# Validation

## Philosophy

Validation is chronological. Random train/test splits can leak season evolution and are not the default evidence for promotion.

The repository tracks:

- accuracy
- Brier score
- log loss
- ROC AUC
- calibration buckets
- component-level metrics
- schedule-integrity errors
- prospective market tracking when available

## Preserved results

The same-sample V2.3 last-game comparison contains 1,101 chronological out-of-fold games.

| Version | Accuracy | Brier | Log loss | AUC |
|---|---:|---:|---:|---:|
| V2.2.2 baseline | 55.68% | 0.24807 | 0.68944 | 0.56319 |
| V2.3 last-game context | 54.68% | 0.24779 | 0.68887 | 0.56480 |

Interpretation: the last-game block slightly improved calibration and ranking metrics while reducing 0.5-threshold winner accuracy. It remains experimental.

## Promotion gates

The current gate configuration is in `config/merge_gates.yaml`. A candidate should not be promoted merely because it performs well on a small retrospective window. It should preserve schedule integrity, improve probabilistic metrics on broad walk-forward data, and survive prospective evaluation.

## Reproducing tests

```bash
pytest
```

For the broader historical workflow:

```bash
python scripts/run_all.py
python scripts/run_v2_2_validation.py
```

Some historical reports refer to earlier releases and are retained for auditability. They are not the active V2.3.2 output schema.

## Active V2.4 framework

V2.4 Phase 4 adds a matched V2.3.3-versus-V2.4 walk-forward runner, calibration
metrics, paired bootstrap intervals, subgroup reports, a locked holdout, reproducibility
metadata, and automatic promotion-gate evaluation. See
`docs/V2_4_VALIDATION_FRAMEWORK.md`.

Run it with:

```bash
sports-supermodel-validate
```

The final holdout is not part of ordinary development runs and must remain locked until
the candidate configuration is frozen.
