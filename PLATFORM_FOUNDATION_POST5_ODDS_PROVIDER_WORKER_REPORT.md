# V2.4 Platform Foundation Post5 — Licensed Odds and Hosted Worker

## Identity

- Branch: `v2.4-platform-foundation`
- Base: `ebbbe7965d60fb7446b62577415c9b62d6a32b76`
- Package: `2.4.0.dev4+platform.foundation.6`
- Tests: `152 passed`
- Predictive authority: unchanged (`V2.3.3` production, `V2.4 RC2` shadow)

## Delivered

- Added a licensed The Odds API v4 adapter for MLB moneylines, run lines, and game totals.
- Added official-team and start-time matching from provider events to MLB `gamePk`.
- Added provider identity and event/market provenance to canonical quotes.
- Added raw immutable odds snapshots and quota-header reporting.
- Added current-provider snapshots so moved or removed lines do not remain active in rankings.
- Integrated odds refresh into every backend publication without adding odds to simulation identity.
- Added `PRICES_UPDATED` when lines change but baseball inputs and simulations remain unchanged.
- Added `sports-supermodel-odds` for provider-only refreshes.
- Added `sports-supermodel-worker` with 30-minute base, 10-minute near-game, and 60-minute
  overnight cadence.
- Added a Dockerfile, Railway config, and single-service shared-volume MVP launcher.

## Explicit limits

- Requires the operator's licensed provider API key; no sportsbook scraping was added.
- Featured provider markets do not include team totals or player props in this unit.
- File-backed storage requires the web app and worker to remain in one service/volume. Shared
  PostgreSQL/object storage is still required before service separation or horizontal scaling.
- Lineup/roster and external weather provider slots remain unfinished.
