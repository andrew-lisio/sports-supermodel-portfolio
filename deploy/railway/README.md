# Railway MVP deployment

This repository supports both the original single-service MVP and a shared-storage deployment.
Platform Foundation Post7 adds PostgreSQL for structured state and S3-compatible object storage for
large immutable artifacts. The combined service remains the safest first hosted deployment while
provider and operational hardening continue.

## Required configuration

1. Connect the GitHub branch in Railway.
2. For file-backed mode, add a persistent volume mounted at `/app/runtime`.
3. For shared mode, provision PostgreSQL and set `SPORTS_SUPERMODEL_STORAGE_BACKEND=postgres`
   plus `DATABASE_URL`.
4. For shared score/report storage, set `SPORTS_SUPERMODEL_OBJECT_BACKEND=s3`,
   `SPORTS_SUPERMODEL_S3_BUCKET`, and the provider's AWS/S3 credentials.
5. Add `SPORTS_SUPERMODEL_ODDS_API_KEY` as a sealed variable.
6. Set `SPORTS_SUPERMODEL_ODDS_BOOKMAKERS` if the default
   `draftkings,fanduel,hardrockbet` list should change.
7. Keep `SPORTS_SUPERMODEL_TIMEZONE=America/New_York` unless the slate-date policy changes.
8. Generate a public domain for the service.

`railway.toml` uses the repository Dockerfile and starts `deploy/run-combined.sh`. The script runs:

- `sports-supermodel-worker`, which publishes immediately and then polls every 30 minutes,
  switching to every 10 minutes within two hours of the next scheduled game;
- the read-only Streamlit website on Railway's injected `PORT`.

The publisher reruns 100,000 simulations only when baseball inputs change. An odds-only movement
updates the current provider snapshot and reprices the existing simulations.

## Current deployment boundary

Post7 removes the shared-filesystem requirement for market quotes, simulation metadata/draws,
publisher state, freshness state, reports, and raw odds snapshots when PostgreSQL/S3 mode is enabled.
The combined service remains the recommended first deployment until monitoring, authentication,
provider licensing, and service-specific health checks are complete. Separate web and worker
services are now technically possible only when both shared backends are configured.
