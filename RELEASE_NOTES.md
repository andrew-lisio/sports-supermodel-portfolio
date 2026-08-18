# V2.6 PA generative integration candidate

V2.6 adds a plate-appearance generative simulator as a third, shadow-only simulation track above the V2.5 public-readiness baseline. It does not silently replace the V2.3.3 production model or the V2.4 RC2 shadow model.

Historical point-in-time testing selected PA simulation over the inning-level alternative for score-distribution architecture. On the locked 1,972-game 2025 holdout, PA produced a Brier score of 0.245055 and log loss of 0.683124 versus 0.247568 and 0.688263 for the frozen Poisson benchmark, while also materially improving tail realism. The paired confidence intervals versus Poisson narrowly crossed zero, so optimal PA moneyline authority remains intentionally unproven and conservative.

The candidate also includes Python 3.11/3.12 CI repair, expanded PA tests, live fail-closed input requirements, public-readiness documentation, and a code-first portfolio cleanup that excludes private market artifacts and unverified copied datasets.

See:

- `docs/PA_GENERATIVE_SIMULATOR.md`
- `docs/validation/PA_GENERATIVE_CANONICAL_BACKTEST_2026-08-16.md`
- `docs/validation/PA_GENERATIVE_IMPLEMENTATION_CANDIDATE_REPORT_2026-08-16.md`
- `docs/ARCHITECTURE.md`
- `docs/VALIDATION.md`

Full historical release notes are archived under `docs/history/RELEASE_NOTES_FULL.md`.
