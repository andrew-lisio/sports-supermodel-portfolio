# V2.5 Public Readiness Foundation

This milestone prepares the repository for a future hosted deployment without creating or
activating public infrastructure.

## Dormant by default

The public deployment framework is disabled unless both variables are set intentionally:

```text
SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED=1
SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK=ENABLE_PUBLIC_SPORTS_SUPERMODEL
```

The deployment shell scripts call `sports-supermodel-public guard` before starting any hosted
web, API, publisher, odds, settlement, or combined service. The production Docker Compose file
also uses the `public` profile, so it is not selected by an ordinary `docker compose up` command.

These safeguards do not change the local workflow. Commands such as `sports-supermodel-ui`,
`sports-supermodel-publish`, and `sports-supermodel-worker --once` can still be used locally.

## Side-effect-free inspection

```powershell
sports-supermodel-public status
sports-supermodel-public plan
sports-supermodel-public readiness
```

These commands only inspect local configuration and print redacted JSON. They do not:

- provision PostgreSQL;
- create an object-storage bucket;
- start a hosted service;
- publish a URL;
- configure DNS or TLS;
- upload runtime artifacts;
- spend provider quota.

A readiness snapshot can be written locally:

```powershell
sports-supermodel-public readiness `
    --output runtime\reports\public_readiness\latest.json
```

## Future activation sequence

When the user explicitly approves deployment:

1. Provision PostgreSQL and S3-compatible object storage.
2. Add provider and application secrets in the hosting platform secret manager.
3. Apply storage migrations and verify a runtime backup.
4. Run the readiness audit in a staging environment.
5. Set the two explicit public-deployment activation variables.
6. Start the `public` Compose profile or the equivalent hosting services.
7. Verify `/healthz`, `/readyz`, worker publishing, odds refresh, and settlement.

The framework does not perform those steps automatically.

## Backup and restore

The storage CLI can create checksummed runtime backups, verify them, and restore them later:

```powershell
sports-supermodel-storage backup `
    --runtime-root runtime `
    --output backups\runtime-backup.tar.gz

sports-supermodel-storage verify-backup `
    --input backups\runtime-backup.tar.gz

sports-supermodel-storage restore `
    --input backups\runtime-backup.tar.gz `
    --runtime-root runtime-restored
```

Restore rejects unsafe archive paths and refuses to overwrite a non-empty destination unless
`--overwrite` is explicitly provided.
