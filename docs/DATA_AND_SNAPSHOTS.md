# Data and snapshots

## Historical data

The prototype 2026 team logs are stored under `data/2026/`. Source and provenance notes are in `data/SOURCE.md`.

The historical logs provide team, opponent, runs, run differential, and starter names. They do not natively preserve official game identifiers or home/away identity. The pipeline attaches those fields from an official or frozen schedule when possible.

## Live inputs

Live evaluation uses two separate categories of input:

1. Public MLB schedule and pregame context obtained by the no-key MLB Stats API client.
2. User-supplied two-way moneylines entered through the local browser app, interactive terminal, CSV, JSON, or Python API.

Private account credentials, balances, sportsbook login information, cookies, and payment information are neither required nor supported.

## Immutable snapshots

Every fetched schedule and pregame context is written to the configured snapshot directory before evaluation. The user-facing defaults write under Git-ignored `runtime/snapshots/`; the tracked `snapshots/` directory contains preserved project-history examples. Snapshot files include capture time, source metadata, identity, and a content-derived digest.

A valid pregame snapshot must be captured before scheduled game start. The store rejects attempts to present post-start information as pregame data.

Accepted user market inputs are stored separately under the `market_input` snapshot kind inside the configured runtime snapshot directory. This makes a run reproducible without mixing public game context and user-entered prices.

## Market-input privacy

Market snapshots may preserve odds obtained from a private or restricted source. Review them before publishing. Do not place account names, balances, credentials, cookies, personal identifiers, or private URLs in an input file.

Generated local inputs should normally live under `user_inputs/`, which is ignored by Git.

## Doubleheaders

Use `game_pk` whenever two games have the same teams and date. The browser app and generated templates supply it automatically. If a user file omits `game_pk` for an ambiguous doubleheader, the workflow rejects the row instead of guessing.

If historical source data cannot distinguish two games, the pipeline excludes the ambiguous record rather than inventing an identity.

## Advanced live feature contract

`config/feature_registry.yaml` identifies fields that are populated historically and fields that are only provider-ready. Provider-ready fields remain neutral when point-in-time historical values are absent.

This avoids retrospective leakage but means a captured live field may not yet influence the fitted probability.
