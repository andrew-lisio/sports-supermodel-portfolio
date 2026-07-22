# Data and snapshots

## Historical data

The prototype 2026 team logs are stored under `data/2026/`. Source and provenance notes are in `data/SOURCE.md`.

The historical logs provide team, opponent, runs, run differential, and starter names. They do not natively preserve official game identifiers or home/away identity. The pipeline attaches those fields from an official or frozen schedule when possible.

## Live inputs

Live evaluation uses two categories of input:

1. Public MLB schedule and pregame context obtained by the no-key MLB Stats API client.
2. A manual moneyline CSV supplied by the user.

Private account credentials, balances, and sportsbook login information are neither required nor supported.

## Immutable snapshots

Every fetched schedule and pregame context should be written to `snapshots/` before evaluation. Snapshot files include capture time and source metadata.

A valid pregame snapshot must be captured before scheduled game start. The store rejects attempts to present post-start information as pregame data.

## Doubleheaders

Use `game_pk` in the odds CSV whenever two games have the same teams and date. If historical source data cannot distinguish the two games, the pipeline excludes the ambiguous record instead of guessing.

## Advanced live feature contract

`config/feature_registry.yaml` identifies fields that are populated historically and fields that are only provider-ready. Provider-ready fields remain neutral when point-in-time historical values are absent.

This avoids retrospective leakage but means a captured live field may not yet influence the fitted probability.
