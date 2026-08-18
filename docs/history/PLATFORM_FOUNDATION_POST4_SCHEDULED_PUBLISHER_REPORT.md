# V2.4 Platform Foundation Post4 — Scheduled Backend Publisher

## Identity

- Branch: `v2.4-platform-foundation`
- Base: `2dcdf6d2f60fe5f37035f545ae2c3d4e95d32915`
- Package: `2.4.0.dev4+platform.foundation.5`
- Tests: `142 passed`
- Predictive authority: unchanged (`V2.3.3` production, `V2.4 RC2` shadow)

## Delivered

- Added `sports-supermodel-publish --date YYYY-MM-DD` for worker/cron execution.
- Refreshes currently supported history and pitching datasets before publication.
- Captures the official MLB slate and excludes started, live, final, postponed, cancelled, and
  suspended games.
- Computes stable baseball-input fingerprints and reruns only new or changed games.
- Adds a lock file to prevent overlapping scheduled simulation jobs.
- Stores latest publisher state and immutable per-run reports.
- Runs both model tracks and saves complete score distributions without exposing a public run button.
- Keeps provider/manual odds independent from simulation identity so an odds-only change reprices
  the saved distribution rather than triggering a new simulation.
- Prevents neutral internal evaluator lines from being written as sportsbook quotes or prospective
  market evidence.
- Allows High Probability to display model-only moneyline probabilities when no sportsbook feed has
  been connected yet.

## Explicit limits

This unit does not connect a licensed odds provider. It also does not claim that roster/lineup or
weather provider slots marked `PENDING_PROVIDER` by the refresh report are complete. The publisher
uses the official context already returned by the current MLB capture pipeline and preserves all
existing feature-authority limitations.

## Worker behavior

```powershell
sports-supermodel-publish --date 2026-07-31
```

Expected statuses:

- `PASS`: one or more eligible games were published.
- `SKIPPED_UNCHANGED`: all eligible games already have the current baseball-input fingerprint.
- `NO_PREGAME_GAMES`: no safe pregame games remain to publish.

`--force` intentionally republishes every eligible game for controlled testing. `--skip-refresh`
can be used only when a separate refresh job has already completed successfully.
