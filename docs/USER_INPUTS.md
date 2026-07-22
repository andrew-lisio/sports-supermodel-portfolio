# User odds input

V2.3.2 does not require sportsbook screenshots. Users enter or import two-way moneylines through the local browser application, interactive terminal, CSV, JSON, or Python API.

## Why odds remain user-supplied

The public MLB feed provides schedule and game context, not sportsbook market prices. Sportsbook APIs may require paid access, credentials, geographic eligibility, or separate contractual rights. This release therefore keeps market acquisition separate from prediction and accepts structured user input without collecting sportsbook credentials.

## Official-slate template

Generate a CSV:

```bash
sports-supermodel --date 2026-07-22 --template user_inputs/moneylines_2026-07-22.csv
```

Generate JSON:

```bash
sports-supermodel --date 2026-07-22 --template user_inputs/moneylines_2026-07-22.json
```

The generated template includes official `game_pk`, game number, scheduled time, teams, probable starters, lineup status, and available weather context. Only the input columns are required for evaluation.

## Supported fields

| Field | Required | Meaning |
|---|---:|---|
| `game_date` | Yes | Official date in `YYYY-MM-DD` form |
| `game_pk` | Recommended | Official MLB game identifier; required to distinguish same-day doubleheaders |
| `away_team` | Yes | Official away-team abbreviation |
| `home_team` | Yes | Official home-team abbreviation |
| `away_odds` | Yes for included rows | Away moneyline price |
| `home_odds` | Yes for included rows | Home moneyline price |
| `odds_format` | No | `american` by default; `decimal` also accepted |
| `include` or `enabled` | No | Boolean-like row switch; defaults to included |

Extra columns are allowed and ignored by the market parser.

## American odds

Accepted examples:

```text
+125
125
-145
EVEN
EV
PK
```

Values between `-99` and `+99`, including zero, are rejected because they are not standard American moneyline prices.

## Decimal odds

Accepted examples:

```text
2.25
1.67
```

Decimal prices must be finite and greater than `1.0`. They are converted to canonical American odds before market analysis.

## Skipping games

A row is skipped when:

- both odds cells are blank, or
- `include=false`, or
- `enabled=false`.

A row with only one odds cell filled is rejected. The engine needs both sides to compute a complete two-way market and no-vig probabilities.

## Doubleheaders

A same-day doubleheader has two games with identical teams and date. Team names alone are therefore ambiguous. Use the generated template so each row carries the official `game_pk` and game number.

The workflow rejects a duplicate or ambiguous matchup rather than guessing.

## CSV example

```csv
include,game_date,game_pk,away_team,home_team,away_odds,home_odds,odds_format
true,2026-07-22,123456,ATH,AZ,111,-151,american
true,2026-07-22,123457,CIN,SEA,2.34,1.57,decimal
false,2026-07-22,123458,STL,LAA,,,american
```

## JSON example

```json
{
  "moneylines": [
    {
      "include": true,
      "game_date": "2026-07-22",
      "game_pk": 123456,
      "away_team": "ATH",
      "home_team": "AZ",
      "away_odds": 111,
      "home_odds": -151,
      "odds_format": "american"
    }
  ]
}
```

A top-level JSON list is also accepted.

## Interactive terminal

```bash
sports-supermodel --date 2026-07-22 --interactive
```

The program shows one official game at a time. Press Enter or type `skip` at the away-odds prompt to omit a game.

Decimal mode:

```bash
sports-supermodel --date 2026-07-22 --interactive --odds-format decimal
```

## Reproducibility and privacy

Every accepted input set is preserved locally under `snapshots/market_input/` with its capture timestamp and source label. This supports reproducibility but may also preserve private market information. Review generated snapshots before committing them to a public repository.

Never include sportsbook credentials, cookies, account names, balances, personal identifiers, or private URLs. The model does not need them.
