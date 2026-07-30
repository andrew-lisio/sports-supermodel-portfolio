# Railway MVP deployment

This repository now supports a single-service MVP in which the read-only Streamlit site and the
adaptive publisher worker run in one container and share one persistent `runtime` directory.

## Required configuration

1. Connect the GitHub branch in Railway.
2. Add a persistent volume mounted at `/app/runtime`.
3. Add `SPORTS_SUPERMODEL_ODDS_API_KEY` as a sealed variable.
4. Set `SPORTS_SUPERMODEL_ODDS_BOOKMAKERS` if the default
   `draftkings,fanduel,hardrockbet` list should change.
5. Keep `SPORTS_SUPERMODEL_TIMEZONE=America/New_York` unless the slate-date policy changes.
6. Generate a public domain for the service.

`railway.toml` uses the repository Dockerfile and starts `deploy/run-combined.sh`. The script runs:

- `sports-supermodel-worker`, which publishes immediately and then polls every 30 minutes,
  switching to every 10 minutes within two hours of the next scheduled game;
- the read-only Streamlit website on Railway's injected `PORT`.

The publisher reruns 100,000 simulations only when baseball inputs change. An odds-only movement
updates the current provider snapshot and reprices the existing simulations.

## Current deployment boundary

The combined service is an MVP bridge while storage remains file-backed. Do not split the website
and worker into separate Railway services yet: each service would have an independent filesystem
and volume. The next infrastructure unit must add a shared PostgreSQL/object-storage implementation
before web and worker are separated or horizontally scaled.
