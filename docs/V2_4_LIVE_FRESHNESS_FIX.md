# V2.4 RC2 live-history freshness and conflict safeguards

## Confirmed failure mode

The repository seed under `data/2026` ends on 2026-07-19. Before RC2, a live slate
loaded those files, attached official schedule identity, and then built current-form and
starter-state features without appending completed games played after the seed cutoff.
A July 25–27 slate could therefore use last-game and rolling-form state that was six to
eight days old.

## Permanent history refresh

Every normal CLI or UI evaluation now:

1. loads the reproducible repository seed;
2. checks the persistent local cache at `runtime/data/mlb_completed_games.csv`;
3. downloads every newly completed official MLB game through the day before the slate;
4. stores the official schedule response as an immutable snapshot;
5. appends canonical `gamePk`, final score, home/away, venue, and starter labels to the
   runtime cache;
6. rebuilds V2.3.3 production and V2.4 shadow state from the refreshed history;
7. records the checked-through date and number of backfilled games in prediction output
   and the prospective evidence ledger.

Same-day results are never added to a slate's history. If the MLB endpoint fails, or a
prior-date game is still live and not explicitly postponed/suspended, the run fails
closed instead of silently using stale data.

The refresh is automatic on every slate. It can also be preflighted with:

```powershell
sports-supermodel-history --date YYYY-MM-DD
```

## Consensus-conflict policy

The raw ensemble prediction remains unchanged and is retained for accuracy measurement.
RC2 separately decides whether that prediction may appear in the top-pick list.

A game is marked `PASS` rather than `ELIGIBLE` when any of the following is true:

- fewer than four of seven component models support the final side;
- the component-model majority selects the opponent;
- the projected-score side selects the opponent by at least 0.20 runs;
- final win probability is below 53%.

The policy never flips a conflicted game to the opponent. It removes the game from the
top-five pool and reports the exact reasons. If fewer than five games qualify, the system
returns fewer than five instead of forcing weak selections.

## Scope and restraint

RC2 fixes the directly confirmed live-data and decision-policy defects. It does not
claim that every bullpen, injury, lineup, or Statcast field has historical training
coverage. Those point-in-time inputs continue to be captured for shadow evidence and
future validated model work; they are not given unvalidated authority in the production
probability.
