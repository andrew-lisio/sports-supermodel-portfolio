# Licensed odds provider and adaptive worker

## Provider

The first production adapter targets The Odds API v4 and uses the official `baseball_mlb` odds
endpoint with American prices. The supported featured markets are:

- `h2h` → moneyline
- `spreads` → run line
- `totals` → game total

Team totals and player props are not inferred from these markets. They remain unsupported until a
provider endpoint and a corresponding model distribution are explicitly connected.

Configure the provider through environment variables:

```text
SPORTS_SUPERMODEL_ODDS_API_KEY=<sealed secret>
SPORTS_SUPERMODEL_ODDS_BOOKMAKERS=draftkings,fanduel,hardrockbet
```

The provider response is matched to the official MLB slate and therefore receives the canonical
MLB `gamePk`. Raw provider responses are archived under
`runtime/snapshots/odds/the_odds_api/<date>/`. Canonical quotes are stored under `runtime/markets/`.

Current provider snapshots are separate from append-only line history. When a book moves a total or
spread, the old number remains auditable but is no longer treated as currently playable.

## Commands

Refresh prices without running simulations:

```powershell
sports-supermodel-odds --date 2026-07-31
```

Run one complete central publication cycle:

```powershell
sports-supermodel-publish --date 2026-07-31
```

Run the hosted adaptive loop once for testing:

```powershell
sports-supermodel-worker --once
```

Run continuously:

```powershell
sports-supermodel-worker
```

The worker uses a 30-minute base cadence, a 10-minute cadence within two hours of the next game,
and a 60-minute overnight cadence. It runs immediately when the process starts.

## Identity separation

Baseball-input changes create a new simulation-input fingerprint and rerun the affected game.
Sportsbook-price changes never enter that fingerprint. They update the current quote snapshot and
rebuild the Best Value ranking from the already-published score distribution.
