# V2.4 Platform Foundation Post6 — Series Context and Carryover Layer

## Identity

- Branch: `v2.4-platform-foundation`
- Base: `4558394bf1a4579c2ca641af8e0fa223c4401f3c`
- Package: `2.4.0.dev4+platform.foundation.7`
- Tests: `156 passed`
- Predictive authority: unchanged (`V2.3.3` production, `V2.4 RC2` shadow)

## Problem corrected

The August 2 Kansas City–Colorado analysis contained the previous-game result in the
refreshed history, but the decision layer did not automatically reconstruct and surface
the complete active series. That allowed a modest 53.6% Kansas City lean to appear as an
eligible Top 5 play even though Colorado had won both prior games, outscored Kansas City
15–7, and won the latest game by six runs.

## Delivered

- Added `supermodel.series_context` with fail-closed current-series reconstruction.
- Defines the active series as the consecutive completed games immediately preceding the
  slate in which both clubs faced each other.
- Prevents an older head-to-head series from being reused when either club has played a
  different opponent more recently.
- Handles completed doubleheaders and rescheduled games already represented in official
  completed history.
- Attaches, for every production and shadow evaluation:
  - series status or explicit series opener
  - prior game scores and official `gamePk`
  - series wins and losses
  - cumulative runs and run differential
  - latest winner, loser, and margin
  - latest blowout flag
  - current-series consecutive losses
  - recent bullpen pitch disadvantage
  - previous-day high-leverage bullpen usage
  - closer-availability carryover
- Adds a conservative context-only abstention policy.
- Persists the context in evaluation CSV/JSON, simulation manifests, and prospective
  evidence.
- Displays the series summary and carryover-gate reason on the read-only Today’s Slate
  page.

## Abstention contract

The layer does not alter, recalibrate, or override any model probability. It never flips
the pick to the opponent. It can only stop a pick from being promoted.

Default `PASS — SERIES CONTEXT` conditions:

1. At least two current-series games have been completed.
2. The selected side's model probability is 57% or lower.
3. At least two adverse signals are present:
   - lost at least two games in the active series
   - series run differential of minus six or worse
   - lost the latest game by at least five runs
   - recent bullpen pitch disadvantage of at least 35 pitches
   - at least 20 high-leverage pitches yesterday with closer availability at 0.35 or lower

The raw production and shadow probabilities remain preserved for settlement and future
validation.

## Kansas City–Colorado regression fixture

The test fixture reconstructs:

```text
Colorado leads 2–0
Prior scores: COL 3–1, COL 12–6
Series runs: COL 15, KC 7
Kansas City run differential: -8
Latest margin: KC lost by 6
Bullpen pitch disadvantage: +48 pitches
```

A 53.59% Kansas City pick remains 53.59% but is changed from `ELIGIBLE` to
`PASS — SERIES CONTEXT`.

## Explicit limits

- This is a decision/research layer, not a trained predictive feature.
- Inning-by-inning comeback, walk-off, and extra-inning labels are not yet persisted in
  the canonical completed-history cache. Prior scores and final-margin context are fully
  supported in this unit; richer ending classifications require the next completed-game
  metadata expansion.
- Named reliever availability is not exposed yet. The current layer uses the existing
  point-in-time workload, save/hold/blown-save proxy, and closer-availability fields.
- Same-day Game 1 results in a doubleheader remain outside the previous-day history
  refresh contract and require a separate intraday settlement refresh.
