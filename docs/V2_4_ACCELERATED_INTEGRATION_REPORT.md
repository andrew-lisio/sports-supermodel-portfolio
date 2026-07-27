# V2.4 Accelerated Integration Verification

## Repository verification

- Source branch: `v2.4-development` at commit `ceda10d`
- Integration branch: `v2.4-accelerated-integration`
- Automated tests: **62 passed**
- Runtime registry: **7 of 7 components present in canonical order**
- Final holdout: **locked and not evaluated**

## Serial-equivalence check

The full five-window matched validation was run twice on the bundled 2026 data with
20 bootstrap iterations: once with the `serial` profile and once with the
`accelerated` profile.

The two runs produced:

- exactly identical `walk_forward_predictions.csv` files across all 1,109 games and
  all 31 columns;
- exactly identical baseline and candidate component probabilities;
- exactly identical fold metrics after excluding runtime-only fields;
- exactly identical summary metrics, bootstrap output, and promotion-gate output.

This establishes behavioral equivalence for the tested data and environment. It does
not replace future regression testing on other supported systems.

## Benchmark from the verification environment

The process had five CPUs available through affinity. End-to-end validation runtime
reported by the application was:

| Profile | Runtime |
|---|---:|
| Serial | 27.06 seconds |
| Accelerated | 23.36 seconds |

That is approximately a **13.7% reduction** for this validation run. Performance will
vary by CPU count, native-library builds, memory bandwidth, operating system, and
workload size. The purpose of the integration is bounded, reproducible concurrency,
not a guaranteed speedup percentage.

## Current validation status

The matched development sample still reports **PENDING** overall. Retrospective gates
pass on the bundled data, but promotion remains blocked by the prospective sample,
closing-line tracking, schedule-integrity evidence, target-leakage evidence,
point-in-time provenance evidence, and the locked final holdout.
