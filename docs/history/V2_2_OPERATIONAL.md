# V2.2 operational workflow

Branch: `v2.2-operational`

V2.2 turns the experimental V2/V2.1 components into an executable daily MLB
moneyline workflow without modifying the frozen V1 rollback branch.

## What is operational

- Manual private-book moneyline CSV input.
- Free public MLB Stats API schedule, `gamePk`, venue, probable-pitcher and live-feed
  capture with immutable raw snapshots.
- Official historical schedule identity backfill, which activates a trained
  ``team_a_is_home`` feature and excludes unresolvable doubleheader rows.
- Official lineup extraction when batting orders have been posted.
- Public season pitcher-stat parsing and transparent FIP / K-BB proxy fields.
- Leakage-safe future matchup feature construction from completed historical games.
- One fitted seven-component V2 ensemble per slate.
- 100,000-draw score simulation and final probability simulation.
- Confidence ranking that does not use odds or Kelly decisions.
- V1-style output fields: model overlap, private-book price, model probability, fair
  price, simulated mean score, no-vig edge, top-pick rank and component probabilities.
- Separate minimum-return adaptive-Kelly sizing after the top picks are fixed.
- The default staking probability is the model probability itself; Half Kelly supplies the
  conservatism. The older fixed model-overlap haircut is opt-in experimental behavior,
  not the default.
- Explicit bankroll composition: accumulated profit + `alpha * available credit` - open
  exposure.
- Optional two-leg parlay evaluation with a clearly labeled independence assumption.

## Daily command

Prepare a CSV with these columns:

```text
game_date,away_team,home_team,away_odds,home_odds,game_pk
```

`game_pk` is optional in the input, but exact official matching is preferred.

Run:

```bash
PYTHONPATH=src python scripts/evaluate_live_slate.py \
  --date 2026-07-20 \
  --odds private_book_odds.csv \
  --profit 0 \
  --credit 100 \
  --alpha 1 \
  --minimum-return 20 \
  --simulations 100000
```

The command freezes the source payloads under `snapshots/` and writes evaluation CSV
and JSON artifacts under `reports/live/`.

## Minimum-return adaptive-Kelly rule

The private book requires a minimum $20 **total return**, including the original stake.
Therefore the minimum stake is `20 / (1 + net-profit-per-dollar)`, rounded upward to
the nearest cent. At +150 the minimum stake is $8.00; at -150 it is $12.00.

Sizing remains downstream from confidence ranking:

1. Pass when Kelly is nonpositive at the offered price.
2. Use 0.75 Kelly for a top-five pick with at least 6/7 overlap and at least a two-point
   edge over break-even; otherwise use 0.50 Kelly.
3. If the fractional-Kelly stake clears the $20-return floor, use it subject to the
   per-bet bankroll cap.
4. Otherwise use the minimum-return stake when it does not exceed Full Kelly.
5. A qualifying high-confidence pick may use the floor stake up to 1.75x Full Kelly and
   12% of bankroll. This is a disclosed hybrid override, not classical Kelly.
6. Total recommended exposure is capped at 30% of effective bankroll in confidence order.

## What “operational” does not mean

The daily pipeline now runs end to end, but V2 remains experimental rather than a
validated production replacement for V1.

The source team logs did not preserve point-in-time confirmed lineups, injuries,
bullpen availability, weather or advanced Statcast fields. V2.2 now backfills official
home/away identity from the schedule and retrains with it, but the remaining live fields
can only be collected and displayed until enough historical point-in-time snapshots and
outcomes have been accumulated and a new walk-forward validation is completed.

Accordingly:

- official home/away identity is an active model input after schedule backfill;
- the optional extra post-model home-field adjustment still defaults to `0.0`;
- advanced live fields are captured for future retraining and used as report context;
- no provider is represented as historically validated when it was absent from the
  training rows;
- V1 remains the rollback point and V2.2 remains on an experimental branch.

## Executed validation

The V2.2 winner/score blend was executed across 1,109 chronological out-of-fold games.
At the fixed 80/20 blend it produced 55.82% accuracy, a 0.2485 Brier score, 0.6902 log
loss and 0.5611 AUC. See `reports/V2_2_VALIDATION_REPORT.md` for scope and provenance.

The model-quality gates are met on that run, but the branch remains experimental because
the required 500 market-tracked bets and closing-line-value evidence do not yet exist.
