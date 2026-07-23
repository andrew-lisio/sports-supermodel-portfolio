# V2.4 Feature Engine: Phase 1

V2.4 begins with a structural refactor rather than an immediate probability change.
Every numeric MLB model input is now assigned to exactly one named baseball category.

Current categories include team strength, offense, run prevention, recent form,
starting pitching, bullpen, lineup, injuries, defense, baserunning, rest/travel,
home field, park/umpire, weather, and market information.

## Why this comes first

The registry creates one source of truth for:

- detecting newly added but unclassified features;
- category-level diagnostics and attribution;
- documenting what the model actually uses;
- preventing duplicate feature names;
- building future lineup, bullpen, weather, and pitching modules cleanly.

## Probability compatibility

Phase 1 does **not** reorder, remove, add, or rescale the existing model inputs.  It
only validates and labels them.  Therefore it is intended to preserve V2.3.3 model
behavior while preparing the codebase for later V2.4 features and attribution.
