# V2.1 point-in-time data implementation

Branch: `v2.1-point-in-time-data`

This branch is an experimental descendant of `v2-development`. It does not alter the
V1 rollback branch or claim a new validated model result.

## Implemented in this increment

- Canonical MLB game registry keyed by official `gamePk`.
- Preservation of official date, game timestamp, game number, doubleheader flag,
  home/away identity, venue, game status, and probable pitchers.
- Integrity rejection for conflicting records that share a `gamePk`.
- Content-addressed, append-only schedule snapshots.
- Content-addressed, append-only pregame context snapshots keyed by `gamePk`.
- Schedule snapshot provider that enriches `PregameContext` by exact `gamePk`.
- Explicit rejection of ambiguous date/team matching when a doubleheader is present.
- Executable Minimum-Profit Conservative Half-Kelly calculation for a single wager.
- Repository-relative data tests instead of a machine-specific `/mnt/data` path.

## Still pending

- Live network orchestration that fetches and records official schedules.
- Active timestamped Statcast, lineup, bullpen, weather, umpire, travel, and market
  providers. The existing provider classes remain neutral placeholders.
- Mapping immutable pregame snapshots into the V2 model feature matrix.
- Slate-level bankroll allocation with correlation and existing-exposure constraints.
- Prospective V1 versus V2.1 shadow-mode collection and merge-gate evaluation.

## Validation scope

The automated tests exercise the registry, doubleheader identity, immutable snapshot
behavior, schedule provider, staking rules, historical feature construction, and the
inning simulator. They do not rerun the full V2 walk-forward trial or retrospective
100,000-trial replay.
