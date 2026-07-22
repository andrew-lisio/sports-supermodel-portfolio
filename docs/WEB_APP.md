# Local browser application

V2.3.3 includes a Streamlit interface for users who do not want to edit files or use terminal prompts.

## Install

```bash
python -m pip install -e ".[ui]"
```

For contributors:

```bash
python -m pip install -e ".[ui,dev]"
```

## Launch

```bash
sports-supermodel-ui
```

or:

```bash
streamlit run app.py
```

Run the command from the repository root so the default `data/` and Git-ignored `runtime/` paths resolve correctly.

## Workflow

1. Select the MLB slate date.
2. Fetch the official slate.
3. Review official game identity, starters, lineup status, and weather context.
4. Choose American or decimal odds.
5. Enter both sides of each two-way moneyline in the editable table.
6. Uncheck or leave both odds blank to skip a game.
7. Acknowledge the recreational-use notice.
8. Run all models and the configured simulations.
9. Review confidence-first rankings.
10. Download CSV or JSON results.

## Local-only design

The default app runs on the user's own computer. It is not a hosted multi-user service and does not require authentication because it binds to Streamlit's local development server.

Do not expose the development server to the public internet without a separate production deployment design that addresses authentication, authorization, rate limiting, secrets, logging, privacy, security updates, data licensing, jurisdictional restrictions, and legal review.

## Troubleshooting

### Streamlit is missing

```bash
python -m pip install -e ".[ui]"
```

### Historical data directory not found

Run from the repository root or change the sidebar path to the directory containing the season's team logs.

### A game cannot be matched

Regenerate the slate from the official feed and use its `game_pk`. This is especially important for doubleheaders and rescheduled games.

### The game already started

The point-in-time workflow fails closed when selected context was captured after the scheduled start. Capture and evaluate the game before its official start.

### The odds table rejects a row

Both sides must be present. Check the selected format and make sure American odds have absolute value of at least 100 or decimal odds exceed 1.0.
