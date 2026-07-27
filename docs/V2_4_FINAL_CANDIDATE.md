# V2.4 final candidate

V2.4 is delivered as one squashed implementation commit above the protected rollback
point `ceda10d`. The implementation branch is `v2.4-final-candidate`; `main` remains the
V2.3.3 production branch until every promotion gate passes.

## Runtime contract

Every live slate evaluation runs two independently versioned tracks:

- **Production:** frozen V2.3.3 probabilities, rankings, picks, market edges, and parlays.
- **Shadow:** V2.4 RC1 using the selected recent-form contract plus point-in-time context
  and a self-gated adaptive overlay.

Primary output columns remain V2.3.3. V2.4 fields are prefixed `shadow_`. The evidence
ledger stores both tracks, the exact Git commit, immutable input hashes, market capture,
closing line when later supplied, and settled result.

## Implemented V2.4 improvements

- Seven-model registry enforcement and CPU-budgeted accelerated execution.
- Matched chronological V2.3.3-versus-V2.4 validation with calibration and regression gates.
- Multi-horizon recent form, previous-game context, and selected exponential decay.
- Category-level ensemble sensitivity reporting.
- Hash-chained prospective evidence, CLV, result settlement, and cohort diagnostics.
- Immutable public starting-pitcher payloads and starter-change auditing.
- Immutable advanced context snapshots derived before first pitch from public MLB feeds:
  posted lineup season aggregates, recent reliever workload, public team pitching and
  fielding proxies, weather/roof/wind, and recent travel/time-zone load.
- A bounded, chronological, prospective adaptive overlay. It is `PENDING` until enough
  graded games exist and becomes `ACTIVE` only when its validation Brier score improves
  without a material log-loss regression. Otherwise it preserves the base V2.4 probability.
- Browser and CLI comparison of production and shadow predictions.

## Fail-closed fields

The feature contract supports additional Statcast, injury, advanced defense, catcher,
umpire, and market fields. They remain missing/neutral unless a point-in-time provider
supplies them. The candidate does not backfill them from postgame knowledge or label a
public proxy as an unavailable proprietary/Statcast metric.

## What code-complete does not mean

The final implementation commit is code-complete, not promotion-complete. V2.4 remains
`PENDING` until it accumulates the required prospective cohort, closing-line evidence,
clean schedule/leakage/provenance audits, and a passing locked final holdout. Continued
V2.4 research must use separate versioned cohorts rather than rewriting prior predictions.

## Commands

```bash
pytest -q
sports-supermodel-registry
sports-supermodel-evidence audit
sports-supermodel-starters audit
sports-supermodel-adaptive show
sports-supermodel-validate --profile accelerated --bootstrap-iterations 2000
```

Do not use `--unlock-holdout` until the candidate is frozen and the release-evidence
review explicitly authorizes the final holdout.
