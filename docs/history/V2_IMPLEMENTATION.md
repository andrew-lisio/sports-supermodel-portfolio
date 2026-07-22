# V2 implementation status

## Executable in the historical replay

- Leakage-controlled team and starter state updated only after each date
- Bayesian win rate and Pythagorean run strength
- Rolling 5/10/20-game offense, defense and form
- Exponentially weighted trends
- Rest and 3/7-day schedule density
- Starter history proxies
- Seven independently fitted components: logistic regression, random forest, neural network, XGBoost, LightGBM, CatBoost and Elo/Pythagorean
- Chronological calibration and conservative V1 prior anchoring
- 100,000-trial game simulations
- Append-only feedback/CLV ledger
- Official-schedule lock contract and explicit doubleheader exclusion
- Inning-level starter/bullpen simulation module

## Implemented as point-in-time provider fields but neutral in this replay

The historical team logs do not include point-in-time Statcast, lineups, injuries, bullpens, umpires, weather, travel or market snapshots. V2 implements typed fields and missingness indicators for all of them, but the replay leaves them neutral instead of creating hindsight data. They become active when timestamped snapshots are connected.

This distinction matters: the branch contains the feature architecture, but the validation result is not evidence that every advanced input has already contributed predictive information.
