# V2.4 Phase 3 Recent-Form Validation

Phase 3 was checked with the repository's five fixed chronological validation windows
using the bundled `data/2026` team logs. The comparison covers 1,109 out-of-fold games.
It is a development check, not evidence of future profitability.

| Version | Accuracy | Brier score | Log loss | AUC |
|---|---:|---:|---:|---:|
| Phase 2 feature set | 54.46% | 0.249539 | 0.692441 | 0.550814 |
| Phase 3 recent-form feature set | 54.46% | 0.249517 | 0.692397 | 0.550951 |

Lower Brier score and log loss are better; higher accuracy and AUC are better. The
changes are extremely small. The result supports keeping the feature set on the V2.4
development branch for further prospective testing, but it does **not** establish a
meaningful performance improvement and is not sufficient to promote V2.4 to `main`.

The validation was run without target-date leakage. Separate unit tests verify that:

- the three-game window contains only completed prior games;
- changing a target game's result cannot change that game's pregame form features;
- historical and future/live feature builders produce the same recent-form snapshot.
