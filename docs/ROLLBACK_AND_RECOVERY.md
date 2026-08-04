# Rollback and recovery framework

The public-deployment framework remains dormant until explicitly enabled. These procedures are for
a future staging or hosted deployment.

## Emergency stop

Disable the public startup gate in the hosting environment and restart the services:

```text
SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED=0
SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK=
```

All guarded hosted entry points then exit with `DORMANT`. Local repository commands are unaffected.

## Runtime backup

```powershell
sports-supermodel-storage backup `
    --runtime-root runtime `
    --output backups\runtime-$(Get-Date -Format yyyyMMdd-HHmmss).tar.gz
```

Each new backup contains a checksum manifest. Verify it before migration or release work:

```powershell
sports-supermodel-storage verify-backup --input backups\runtime-backup.tar.gz
```

## Restore rehearsal

Restore to a separate directory first:

```powershell
sports-supermodel-storage restore `
    --input backups\runtime-backup.tar.gz `
    --runtime-root runtime-restore-test
```

The restore command rejects path traversal, links, devices, corrupt checksums, and non-empty target
directories unless `--overwrite` is explicitly supplied.

## Git rollback

Each cumulative milestone uses separate commits. Revert a faulty milestone commit on a repair branch
rather than rewriting shared history:

```powershell
git switch -c v2.5-public-readiness-rollback
git revert <commit>
pytest -q
git push -u origin v2.5-public-readiness-rollback
```

Model governance remains separate from platform rollback. Reverting platform code does not promote
or replace V2.3.3 production or V2.4 RC2 shadow models.
