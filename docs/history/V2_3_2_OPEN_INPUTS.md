# V2.3.2 open-input release

V2.3.2 replaced the chat-only screenshot workflow with structured user input.

## Added

- Local Streamlit interface
- Interactive terminal entry
- CSV and JSON support
- American and decimal odds parsing
- Official-slate template generation
- Shared execution workflow
- Immutable market-input snapshots
- Exact doubleheader matching by `gamePk`

## Unchanged

The predictive feature set and model stack remain V2.3. This release makes the project independently usable and publishable without claiming a new model-performance improvement.

## Removed boundary

The active engine remains prediction-only. Kelly, bankroll, stake sizing, and exposure logic are absent from the active package.
