# V2.4 RC3 dev2 — Pitching backfill resilience hotfix

## Root cause

The RC3 backfill selected game records when MLB's schedule payload reported an abstract game state of `Final`. MLB can use that abstract state for postponed, cancelled, or rescheduled placeholders that were not actually played. `gamePk=823539` resolves to a future August 29, 2026 game and therefore has no completed away-pitcher lines for a March 25–July 28 backfill.

## Changes

- Requires detailed/coded completed status rather than trusting abstract `Final` alone.
- Excludes postponed, cancelled, suspended, rescheduled, and scheduled placeholders.
- Verifies each live feed's official date falls inside the requested backfill range.
- Skips a rescheduled feed when its actual official date is outside the requested range.
- Recovers pitcher order from player game lines when the team-level `pitchers` array is missing but real pitching appearances exist.
- Adds a persistent raw-feed cache under `runtime/cache/mlb_pitching_feeds`.
- Adds visible progress every 25 games so the terminal no longer appears frozen.
- Adds `--no-cache` and `--cache-dir` CLI controls.
- Keeps fail-closed behavior for a genuinely completed in-range game that has no official pitching lines.

## Validation

- 116 tests passed.
- Python compilation passed.
- Git whitespace validation passed.
- Added regression coverage for abstract-final postponed records, out-of-range rescheduled feeds, missing pitcher-order recovery, and feed-cache reuse.

## Identity

- Branch: `v2.4-rc3-pitching-context`
- Base commit: `b7c6a22fbf2f9f9af3e242b85e8e7d1e82f3f68c`
- Package version: `2.4.0.rc3.dev2`
