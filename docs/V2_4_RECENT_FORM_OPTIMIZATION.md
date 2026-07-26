# V2.4 Recent-Form Optimization

Phase 5 evaluates recent-form structure as an explicit experiment rather than assuming that more rolling windows improve the model.

The optimizer compares the frozen V2.3.3 contract with:

- the full Phase 3 three-, five-, ten-, and twenty-game contract;
- the same contract without momentum features;
- a reduced three-, ten-, and twenty-game contract;
- a contract without explicit previous-game features; and
- slower and faster exponentially weighted decay rates.

Every candidate uses the same chronological development windows. The final holdout remains locked. Selection is conservative: a more complex candidate must improve both Brier score and log loss by configured minimum amounts and remain inside accuracy, AUC, and calibration regression limits.

Run:

```bash
sports-supermodel-optimize-form
```

Generated reports are written to `reports/v2_4_recent_form/` and are ignored by Git. The selected contract is not automatically promoted into production; its result must be reviewed and then frozen in a separate commit.
