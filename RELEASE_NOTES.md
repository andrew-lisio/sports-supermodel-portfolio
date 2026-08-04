# V2.5 accelerated platform integration

This cumulative development branch packages the planned live-context, totals-candidate,
shared-storage activation, service separation, settlement, validation, public-page, and
launch-hardening work. It does not promote a new prediction model and does not claim that
external providers or hosted infrastructure are already configured. See
`docs/V2_5_ACCELERATED_PLATFORM_INTEGRATION.md`.

---

# V2.4 RC1 implementation notes

V2.4 RC1 is the code-complete candidate, delivered as one commit above rollback commit
`ceda10d`. It does not replace V2.3.3 yet. Live execution keeps V2.3.3 in production
columns and runs V2.4 in a separately versioned shadow track.

The candidate includes accelerated seven-model execution, matched chronological
validation, immutable prospective evidence and starter snapshots, public point-in-time
lineup/bullpen/weather/fielding/travel context, and a self-gated adaptive shadow overlay.
Unavailable point-in-time sources remain neutral and are never filled with hindsight.

Promotion remains `PENDING` until the required prospective games, CLV, integrity,
provenance, calibration, and locked final-holdout gates pass. See
`docs/V2_4_FINAL_CANDIDATE.md`.

---

# V2.3.3 release notes

V2.3.3 is a schedule-integrity hotfix for the open-input, prediction-only application.

## Fixed

The MLB schedule API can return the same official `gamePk` more than once in a multi-day response when a game is postponed, suspended, resumed, or rescheduled. V2.3.2 compared every mutable schedule field and stopped the evaluation when repeated rows differed. V2.3.3 now:

- Uses the game-level `officialDate` when it is available.
- Reconciles repeated rows when the official away and home team IDs match.
- Prefers the most advanced and information-rich representation.
- Retains missing probable-pitcher or venue details from the richer duplicate row.
- Still fails closed when one `gamePk` is attached to different teams.

## Unchanged

- Browser, terminal, CSV, JSON, and Python input methods
- Seven required winner-model components
- Calibrated ensemble and two-sided Poisson model
- 100,000-simulation defaults
- Immutable pregame snapshots and post-start protection
- Prediction-only boundary with no Kelly, bankroll, stake sizing, or exposure logic

## Test status

31 tests pass in the release environment.

## Predictive-performance claim

This hotfix changes schedule parsing and reliability only. It does not claim an improvement in predictive accuracy or profitability.

## 2.4.0.dev4+platform.foundation.6

This platform-only unit connects licensed featured MLB odds and a hosted publication loop. It does
not change either predictive track. The worker reruns games only after baseball-input changes and
reprices saved simulations when sportsbook prices change.

## 2.4.0.dev4+platform.foundation.7

This platform-only unit adds automatic current-series reconstruction and a conservative
carryover abstention gate. It publishes prior series scores, record, run differential,
latest blowout status, bullpen workload, high-leverage usage, and closer availability.
The layer never changes V2.3.3 or V2.4 probabilities and never flips a pick; it can only
label a modest-confidence recommendation `PASS — SERIES CONTEXT` when multiple adverse
signals agree.

## Platform Foundation Post7 — shared storage

Post7 adds optional PostgreSQL/S3 persistence, distributed publisher locking, storage migrations,
and backend-neutral reads for the public site. Local mode remains the default, and no prediction
model or probability changed.
