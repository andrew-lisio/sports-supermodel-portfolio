# V2.4 Platform Foundation

This development unit prepares the Sports SuperModel for a public multi-page site without
changing the frozen V2.3.3 production model or the V2.4 RC2 predictive identity.

## Canonical odds schema

`MarketQuote` represents moneylines, run lines, game totals, and team totals from any
licensed provider or a manually entered/private-book price. The schema preserves sportsbook,
line, price, capture time, provider update time, and `gamePk`.

## Pricing engine

The central pricing engine calculates expected ROI, break-even win probability, fair odds,
and a conservative playable-through price. Whole-number markets preserve push probability.
Conflict and freshness flags can block a positive mathematical edge from becoming a surfaced
recommendation.

## Simulation snapshots

`SimulationSnapshot` stores the canonical away/home run vectors from one model/input snapshot.
Changing sportsbooks or entering a custom line reprices the stored distribution and does not
rerun the model. A new 100,000-run simulation is required only after a material baseball input
changes.

## Rankings

- `rank_high_probability`: price-independent raw outcome probability.
- `rank_best_value`: rebuilds the Top 5 for one global sportsbook selector.
- `BEST_AVAILABLE`: chooses the best quote for each market across allowed books before ranking.

## Automatic refresh

`sports-supermodel-refresh --date YYYY-MM-DD` refreshes completed history and point-in-time
pitching context through the day before the slate. Cached pitching feeds mean old games are
not redownloaded, although the chronological feature table is deterministically rebuilt from
the season start.

Schedule/starters, lineup/roster, weather, and sportsbook provider slots are explicitly marked
`PENDING_PROVIDER` until authorized production sources are connected. The command does not
claim those inputs were refreshed.

## Scheduled backend publisher

`sports-supermodel-publish --date YYYY-MM-DD` is the worker-facing publication command. It:

1. refreshes the supported historical datasets;
2. captures the official point-in-time MLB slate;
3. excludes games that have started or are postponed/cancelled/final;
4. fingerprints the model-authoritative historical data and stable baseball context;
5. runs production and shadow simulations only for new or materially changed games;
6. saves the canonical 100,000-draw distributions for the read-only website.

The worker uses neutral internal moneyline placeholders only because the current evaluator expects
a two-way line object. Those placeholders are never written to the market store and never enter the
prospective evidence ledger. Licensed or manually entered quotes remain an independent stream and
reprice saved distributions without changing the simulation-input fingerprint.

The publisher writes an overlap lock at `runtime/state/slate_publisher.lock`, its latest state at
`runtime/state/slate_publisher.json`, and immutable run reports under
`runtime/reports/slate_publisher/<date>/`.

Run it manually for worker testing:

```powershell
sports-supermodel-publish --date 2026-07-31
```

A second invocation with unchanged baseball inputs returns `SKIPPED_UNCHANGED`. Use `--force` only
for controlled development checks. Public website visitors never invoke this command.
