# Shared PostgreSQL and object storage

Platform Foundation Post7 adds a production storage abstraction while preserving the existing
local file workflow.

## Storage modes

### Local mode

Local mode is the default and requires no additional services:

```text
SPORTS_SUPERMODEL_STORAGE_BACKEND=local
SPORTS_SUPERMODEL_OBJECT_BACKEND=local
```

Market history, simulations, state, and object artifacts remain under `runtime/`.

### Hosted shared mode

Hosted deployments can use PostgreSQL for structured state and an S3-compatible object store for
large immutable payloads:

```text
SPORTS_SUPERMODEL_STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://...
SPORTS_SUPERMODEL_OBJECT_BACKEND=s3
SPORTS_SUPERMODEL_S3_BUCKET=...
SPORTS_SUPERMODEL_S3_PREFIX=sports-supermodel
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=...
```

For Cloudflare R2, MinIO, Backblaze B2, or another S3-compatible provider, also configure:

```text
SPORTS_SUPERMODEL_S3_ENDPOINT_URL=https://...
SPORTS_SUPERMODEL_S3_FORCE_PATH_STYLE=1
```

Do not commit database URLs, passwords, access keys, or API keys.

## Installation

Local development still works with:

```powershell
python -m pip install --upgrade -e ".[ui,dev]"
```

To run PostgreSQL/S3 storage locally or in a hosted image:

```powershell
python -m pip install --upgrade -e ".[ui,dev,storage]"
```

The Docker image installs the `storage` extra automatically.

## Migrations

Apply migrations after setting the PostgreSQL environment variables:

```powershell
sports-supermodel-storage migrate
```

The migration runner is idempotent and records each applied migration in
`supermodel.schema_migrations`.

Check sanitized configuration and database health:

```powershell
sports-supermodel-storage status
```

The status output never prints `DATABASE_URL` or credentials.

## Structured PostgreSQL data

The initial schema includes:

- append-only market quote history;
- transactional current provider markets;
- simulation snapshot metadata;
- shared platform/publisher state;
- game publication records;
- series-context records;
- prospective evidence records;
- freshness records;
- migration history.

The market quote implementation preserves removed-line behavior. An empty provider snapshot still
records that a sportsbook was represented, so old provider quotes cannot silently reactivate.

## Object storage

Large immutable artifacts are stored outside PostgreSQL:

- compressed `away_runs` and `home_runs` simulation vectors;
- publisher JSON reports;
- evaluation JSON artifacts in hosted mode;
- raw licensed-odds responses in hosted mode.

Simulation metadata stores the object reference and SHA-256 identity. A sportsbook-price change
continues to reprice the saved distribution without rerunning 100,000 simulations.

## Shared publisher lock

Local mode uses the existing atomic lock file. PostgreSQL mode uses a connection-scoped advisory
lock. This prevents two publisher workers on different containers from running the same critical
section at the same time.

## Runtime factory

The website, publisher, odds refresh, pricing views, and workflow persistence use storage factories.
The selected backend is controlled by environment variables; model probabilities and the seven-model
registry are unchanged.

## Migration boundary

Post7 makes shared market, simulation, state, report, and odds-response storage operational. Some
legacy local caches remain intentionally local, including downloaded MLB feed caches and the current
CSV historical feature inputs. A later data-provider and service-separation unit can move or rebuild
those caches without changing model authority.
