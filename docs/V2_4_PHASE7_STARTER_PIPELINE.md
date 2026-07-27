# V2.4 Phase 7 — point-in-time starting-pitcher pipeline

Branch: `v2.4-phase7-starter-pipeline`

Phase 7 builds the collection and audit layer required for a future pitcher-specific
model. It does **not** activate new pitcher variables in the trained V2.4 candidate,
promote V2.4, merge into `main`, or unlock the final holdout.

## Immutable starter captures

For every official pregame `gamePk` with a posted probable starter, the live capture now
writes one immutable `mlb_starter_pregame` snapshot per side. Each snapshot contains:

- official `gamePk`, away/home side, team ID, and MLB person ID;
- the scheduled start and UTC capture time;
- the probable-starter identity source;
- the exact public MLB season-stat payload and its SHA-256;
- normalized season ERA, WHIP, innings, games started, FIP proxy, K%, BB%, K-BB%,
  K/9, BB/9, HR/9, H/9, and ground-out/air-out ratio;
- an immutable envelope digest encoded in the filename.

Baseball innings notation is handled correctly: `100.2` means 100 innings and two outs,
not the decimal number 100.2.

A snapshot captured after the official scheduled start is rejected. Missing probable
starters remain explicit point-in-time missingness rather than being filled later with
hindsight.

## Starter changes

A new probable starter creates a new identity (`gamePk:side:pitcherId`) instead of
rewriting an earlier capture. The audit reports the sequence of pitcher IDs observed for
that game and side. The export uses the latest valid capture before first pitch.

## Prediction evidence

Normal live predictions now bind the following artifacts into the evidence hash:

1. the immutable game pregame snapshot;
2. the away and home starter snapshots that existed at prediction time;
3. the user market-input snapshot.

The prediction ledger also stores starter IDs, names, and starter-snapshot SHA-256 values.
The Phase 6B provenance gate fails when a supplied starter identity is not backed by a
valid immutable snapshot digest.

## Audit and export

Audit the local collection:

```powershell
sports-supermodel-starters audit
```

With no collected snapshots, the audit status is `PENDING`. With valid snapshots it is
`PASS`; malformed, tampered, or post-start snapshots produce `FAIL` and a nonzero exit
code.

Export one latest valid pregame row per game and side:

```powershell
sports-supermodel-starters export
```

Defaults:

```text
runtime/evidence/starter_snapshot_audit.json
runtime/evidence/starter_training_rows.csv
```

These local runtime artifacts are Git-ignored.

## Predictive boundary

The existing V2.4 model still uses the previously validated feature contract. The new
starter metrics are collected for future chronological training and validation; they are
not represented as a proven accuracy upgrade. Activation requires sufficient historical
point-in-time coverage, matched walk-forward comparison against V2.3.3, calibration and
subgroup checks, regression gates, prospective shadow evidence, and the separately locked
final holdout.
