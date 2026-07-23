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

## Phase 2: feature-group sensitivity

Phase 2 adds prediction diagnostics without changing the trained probabilities, score
simulation, ranking, or market calculations. For each registered feature group, the
engine compares the normal seven-model ensemble probability with a counterfactual in
which that group is replaced by medians learned from the chronological training core.

The output is oriented toward the reported pick:

- a positive value means the observed group supports the pick relative to its training
  reference;
- a negative value means the observed group opposes the pick;
- values are probability changes and are shown as percentage points in the browser UI.

These values are **non-causal and non-additive**. Correlated features and model
interactions mean that group effects should not be summed to reconstruct the final
probability. The diagnostic scope is the seven-model winner ensemble before the
separate Poisson score blend and Monte Carlo finalization.

## Phase 3: multi-horizon recent form

Phase 3 adds a three-game window beside the existing explicit previous-game, five-game,
ten-game, twenty-game, and exponentially weighted form inputs. It also adds short-versus-
medium momentum features for wins, runs scored, runs allowed, and run differential.

The feature contract now exposes the following recent-form horizons without using any
future result:

- one game through the existing `last_*` fields;
- three games through `win3`, `rf3`, `ra3`, and `rd3`;
- five, ten, and twenty games through the existing rolling fields;
- exponentially weighted form through the existing `ewm_*` fields;
- three-versus-ten-game momentum through the new `form_*_momentum` fields.

The seven-model ensemble and Poisson score model learn how much weight to assign to the
available horizons. This phase does not claim that a single optimal decay rate has been
identified; explicit walk-forward decay selection remains later V2.4 work.

Historical and future matchup builders use the same state snapshot. Tests verify that a
game's own result cannot enter its pregame features and that the live/future builder
matches the historical pregame calculation.
