# Local browser interface

Launch the current interface from the repository root:

```powershell
sports-supermodel-ui
```

The application now opens directly into the official slate workflow. It automatically captures the selected date, locks games at or past their scheduled start, and presents moneyline entry as matchup cards instead of a raw editable table.

The primary confidence board shows V2.3.3 production picks alongside the V2.4 RC1 shadow track, including probability, seven-model overlap, disagreement status, and the 100,000-simulation score estimate. Full tables, feature-group sensitivity, downloads, and reproducibility paths remain available under the advanced-results section.

Runtime paths are intentionally fixed to the repository defaults and are not exposed as normal interface controls:

- an approved local historical-data directory (the `data/2026` development cache is not distributed in this repository)
- `runtime/snapshots`
- `runtime/reports`
- `runtime/evidence/prospective.jsonl`
- `runtime/models/v2_4_adaptive_overlay.json`

The interface is local-only and uses the same installed package and Git checkout as the command-line workflow.
