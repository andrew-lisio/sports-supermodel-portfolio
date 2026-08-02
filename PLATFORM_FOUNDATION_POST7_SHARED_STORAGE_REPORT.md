# Platform Foundation Post7 — Shared Production Storage

## Identity

```text
Branch: v2.4-platform-storage
Package: 2.4.0.dev4+platform.foundation.8
Production model: V2.3.3 unchanged
Shadow model: V2.4 RC2 unchanged
```

## Purpose

Post7 removes the principal filesystem-sharing blocker for a hosted public website. The worker and
read-only web application can now select a shared PostgreSQL backend and S3-compatible object store,
while local development remains file-backed by default.

## Delivered

- Storage settings loaded from environment variables with secret-safe status output.
- Runtime factories for market quotes, simulation snapshots, state, and object artifacts.
- PostgreSQL migration runner and packaged schema.
- PostgreSQL market quote history and transactional current-provider snapshots.
- Provider-snapshot bookkeeping that prevents removed lines from reappearing.
- PostgreSQL simulation metadata with compressed score draws in object storage.
- PostgreSQL shared JSON state for platform refresh and slate publishing.
- PostgreSQL advisory publisher lock for multi-container concurrency control.
- Local and S3-compatible object-store implementations.
- Publisher report mirroring to object storage.
- Hosted evaluation-artifact and raw licensed-odds snapshot persistence.
- Read paths in the website and ranking layers that follow the configured backend.
- `sports-supermodel-storage status` and `sports-supermodel-storage migrate` commands.
- Docker installation of PostgreSQL/S3 dependencies and automatic hosted migration startup.
- Local file mode preserved without requiring PostgreSQL, S3, psycopg, or boto3.

## Database schema

The migration creates the `supermodel` schema and tables for:

```text
schema_migrations
market_quote_history
provider_market_snapshots
current_market_quotes
simulation_snapshots
platform_state
game_publications
series_context_records
evidence_records
freshness_records
```

## Storage behavior

```text
Local development
  structured data -> runtime files
  large artifacts -> runtime/objects
  publisher lock  -> atomic lock file

Hosted shared mode
  structured data -> PostgreSQL
  score draws      -> S3-compatible object storage
  reports/raw odds -> S3-compatible object storage
  publisher lock   -> PostgreSQL advisory lock
```

## Governance

Post7 does not:

- alter any V2.3.3 or V2.4 RC2 feature;
- retrain or recalibrate a model;
- activate the rejected RC3 pitching features;
- modify conflict or series-context thresholds;
- fabricate provider data after an API failure;
- change the private-book screenshot authority rule.

## Validation

```text
169 tests collected
169 passed
Python compileall: PASS
```

New tests cover local and S3 object stores, environment validation, secret-safe configuration,
state persistence, factory compatibility, migration discovery, PostgreSQL market history,
PostgreSQL simulation/object round trips, and cross-worker advisory locking through injected test
connections.

## Remaining infrastructure work

Post7 makes shared storage available but does not yet complete every public-deployment requirement.
Remaining work includes:

- production provider integration for confirmed lineups, rosters, injuries, weather, and roof status;
- final deployment topology with separate web and worker services;
- authentication/admin roles, rate limits, monitoring, backups, and alerting;
- data-license review;
- migration or deterministic rebuilding of legacy MLB feed caches;
- settlement service and complete prospective performance persistence.
