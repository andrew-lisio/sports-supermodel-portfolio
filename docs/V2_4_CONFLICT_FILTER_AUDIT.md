# V2.4 provisional conflict-filter audit

The conflict filter is an abstention and recommendation gate. It does not replace the raw
winner prediction, flip the selection to the opponent, or alter model probabilities.
Every raw prediction remains in the prospective ledger and is graded against the official
outcome.

RC2 post1 adds durable policy metadata and an audit command:

```powershell
sports-supermodel-conflicts
```

The default audit reads `runtime/evidence/prospective.jsonl` and writes
`runtime/evidence/conflict_filter_audit.json`. It reports:

- raw winner accuracy across all graded games;
- accuracy and coverage of games allowed into the recommendation pool;
- raw accuracy of filtered games;
- helpful passes, where the blocked raw pick lost;
- false passes, where the blocked raw pick won;
- performance by exact trigger such as `LOW_PROBABILITY`, `LOW_OVERLAP`,
  `COMPONENT_CONSENSUS_CONFLICT`, and `PROJECTED_SCORE_CONFLICT`.

The audit remains `PENDING` until it contains at least 100 graded games and 40 filtered
games by default. These thresholds are evidence checkpoints, not automatic permission to
retune the filter. Any threshold change must be tested chronologically and applied only to
future cohorts.

Prediction events now record production and shadow raw picks, statuses, reasons,
component-consensus picks, projected-score picks, policy version, and policy mode. This
allows the recommendation gate to be evaluated without erasing or rewriting predictions.

The current policy thresholds are intentionally unchanged after the July 25–28 diagnostic.
That sample was directionally supportive but too small and inconsistent by day to justify
post-hoc retuning.
