# V2.4 selected recent-form contract

Phase 5A selected `phase3_full_alpha_025` on the locked chronological development folds.
Phase 5B freezes that result as the active V2.4 **candidate** contract:

- rolling windows: 3, 5, 10, and 20 completed games;
- explicit 3-versus-10 momentum fields: enabled;
- previous-game context: enabled;
- exponentially weighted form alpha: **0.25**.

The frozen V2.3.3 comparison contract remains separate:

- rolling windows: 5, 10, and 20 completed games;
- 3-game and momentum fields: excluded;
- previous-game context: enabled;
- exponentially weighted form alpha: **0.18**.

`src/supermodel/model_contract.py` is the canonical source for these settings. Historical
training, future matchup generation, live evaluation, matched validation, and locked-holdout
validation must use the appropriate named contract rather than relying on an unversioned local
default.

This freeze does **not** promote V2.4 to production. The final holdout and prospective gates
remain locked/pending.
