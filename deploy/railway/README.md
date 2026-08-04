# Railway deployment framework

This repository contains a dormant Railway-compatible deployment framework. It does not deploy
anything by itself.

Before a future launch, complete the public-readiness checklist and configure PostgreSQL,
S3-compatible object storage, provider credentials, and application secrets. The hosted startup
scripts refuse to run until both variables are intentionally configured:

```text
SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED=1
SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK=ENABLE_PUBLIC_SPORTS_SUPERMODEL
```

The current `railway.toml` uses the combined web/worker startup script. Shared PostgreSQL and object
storage are required for a production launch. The site should remain private and undeployed until
the user explicitly approves activation.

See `docs/PUBLIC_READINESS_FOUNDATION.md` for the future activation sequence.
