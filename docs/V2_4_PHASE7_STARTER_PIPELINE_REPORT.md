# V2.4 Phase 7 integration report

## Scope

Phase 7 adds a point-in-time starting-pitcher collection and audit pipeline on top of
`v2.4-phase6b-evidence-pipeline`. It leaves the winner models, score model, feature
contract, recent-form alpha, calibration logic, and final holdout unchanged.

## Implemented

- Immutable raw starter-stat snapshots keyed by official `gamePk`, side, and MLB person ID.
- Fail-closed post-start capture protection.
- Correct baseball innings conversion for `.1` and `.2` outs.
- Normalized ERA, WHIP, innings, starts, FIP proxy, K%, BB%, K-BB%, K/9, BB/9,
  HR/9, H/9, and ground-out/air-out fields.
- SHA-256 preservation for raw payloads and immutable envelopes.
- Detection of probable-starter changes across repeated pregame captures.
- Latest-valid-pregame CSV/JSON export for future chronological training.
- Starter IDs and snapshot hashes in prospective prediction evidence.
- Evidence-provenance failure when a supplied starter identity lacks a valid snapshot hash.
- Windows-safe snapshot directory names while retaining canonical identity in the envelope.
- New `sports-supermodel-starters audit` and `sports-supermodel-starters export` commands.

## Validation performed

- Python compilation completed successfully.
- Full repository test suite: **78 passed**.
- `git diff --check`: clean.
- Package wheel built successfully with build isolation disabled.
- Starter CLI smoke test returned `PENDING` with an empty collection and exit code 0.
- A 1,109-game accelerated retrospective smoke run completed with all retrospective
  promotion gates passing and overall status remaining `PENDING`.

The sandbox used older ML dependency versions than the user's verified local environment,
so the sandbox smoke-run probabilities are not substituted for the user's authoritative
2,000-bootstrap result. The predictive modules and feature contract were not changed in
Phase 7.

## Promotion status

**PENDING.** No prospective sample, closing-line record, final holdout, or release gate is
waived by this branch. The new starter data is collection-only until adequate point-in-time
coverage and a separate matched chronological model experiment are completed.
