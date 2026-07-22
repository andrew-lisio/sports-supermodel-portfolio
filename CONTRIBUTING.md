# Contributing

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e ".[ui,dev]"
pytest
```

Launch the local interface:

```bash
sports-supermodel-ui
```

## Requirements for model changes

Every new feature or model should include:

- a point-in-time definition
- source and capture-time provenance
- explicit missing-value behavior
- a test against target leakage
- chronological out-of-sample evaluation
- comparison with the current baseline
- documentation of whether the field is historically trained or only captured live

Do not add hidden bankroll or stake-sizing behavior to the prediction engine. Any future decision-support module should be separate, optional, clearly labeled, and reviewed independently.

## Requirements for input and interface changes

Input or UI changes should include:

- validation tests
- doubleheader behavior
- privacy and secret-handling review
- matching behavior based on official `game_pk`
- backward compatibility for documented CSV/JSON formats when practical
- confirmation that the browser and CLI still call the shared workflow

Do not add sportsbook credential collection or embed private API keys.

## Pull requests

Keep changes focused. Include tests, updated documentation, and a concise explanation of data provenance and expected behavior.
