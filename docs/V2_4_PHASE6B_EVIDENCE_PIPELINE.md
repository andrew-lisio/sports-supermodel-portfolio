# V2.4 Phase 6B — point-in-time evidence pipeline

Phase 6B converts the remaining release gates from permanent placeholders into auditable,
machine-readable evidence. It does **not** promote V2.4 or unlock the final holdout.

## What is recorded

Every normal live evaluation now appends one `prediction` event per official `gamePk` to
`runtime/evidence/prospective.jsonl`. The event includes:

- the scheduled start and UTC capture time;
- home and away probabilities, the seven-model overlap, and the offered two-way line;
- the package version;
- a SHA-256 derived from the immutable pregame and market snapshots;
- source provenance for schedule, live feed, immutable starter statistics, starter identity, and market input;
- a sequence number, previous-event hash, and content-derived event hash.

The ledger rejects a prediction or closing line recorded after scheduled start. It also
rejects outcome-like fields in prediction payloads.

Closing lines and results are appended as separate events so historical records are never
edited in place.

## Recording closing lines and outcomes

Use official `gamePk` and the scheduled start from the captured slate.

```powershell
sports-supermodel-evidence record-close `
  --game-pk 900001 `
  --scheduled-start 2026-07-27T23:10:00Z `
  --captured-at 2026-07-27T23:08:00Z `
  --away-odds +115 `
  --home-odds -125 `
  --source sportsbook_closing_capture
```

```powershell
sports-supermodel-evidence record-outcome `
  --game-pk 900001 `
  --scheduled-start 2026-07-27T23:10:00Z `
  --recorded-at 2026-07-28T02:45:00Z `
  --home-won 1 `
  --source official_result
```

Or fetch the completed result directly from the MLB live feed:

```powershell
sports-supermodel-evidence record-official-outcome `
  --game-pk 900001 `
  --scheduled-start 2026-07-27T23:10:00Z
```

## Auditing

```powershell
sports-supermodel-evidence audit
```

The command reads `config/evidence.yaml` and writes
`runtime/evidence/evidence_report.json`. The report contains structured evidence for:

- prospective sample count;
- closing-line coverage;
- schedule integrity;
- target-leakage protection;
- point-in-time provenance.

An incomplete sample is `PENDING`, not a false pass and not an automatic failure. A broken
hash chain, post-start pregame record, conflicting identity, missing closing line on a
graded game, target-like prediction field, or missing required provenance is a `FAIL`.

## Feeding evidence into validation

```powershell
sports-supermodel-validate `
  --profile accelerated `
  --bootstrap-iterations 2000 `
  --evidence-report runtime/evidence/evidence_report.json `
  --output-dir reports/v2_4_validation_final
```

The locked holdout remains independent. Do not add `--unlock-holdout` during prospective
collection or feature development.

## Local artifact policy

The default ledger and evidence reports live under `runtime/`, which is Git-ignored. They
may contain user-entered market prices and should be reviewed before being shared.
